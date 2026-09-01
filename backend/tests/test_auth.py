"""Unit tests for the backend authentication module.

These tests exercise authentication and authorization policy without requiring a
running PostgreSQL instance or LDAP server.
"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

import app.api.auth as auth
import app.api.ldap_auth as ldap_auth


USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"


def _run(coro):
    return asyncio.run(coro)


def _async_return(value=None):
    async def _call(*args, **kwargs):
        return value
    return _call


class _FakeConn:
    def __init__(self, *, row=None, rows=None, result="UPDATE 1"):
        self.row = row
        self.rows = rows or []
        self.result = result
        self.fetchrow_calls = []
        self.execute_calls = []

    async def fetchrow(self, query, *args, **kwargs):
        self.fetchrow_calls.append((query, args, kwargs))
        return self.row

    async def fetch(self, query, *args, **kwargs):
        return self.rows

    async def execute(self, query, *args, **kwargs):
        self.execute_calls.append((query, args, kwargs))
        return self.result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self, *args, **kwargs):
        return self.conn


def _patch_pool(monkeypatch, conn):
    monkeypatch.setattr(auth, "_get_pool", _async_return(_FakePool(conn)))


def _user_row(**overrides):
    row = {
        "id": USER_ID,
        "username": "alice",
        "password_hash": "stored-hash",
        "role": "admin",
        "display_name": "Alice",
        "email": "alice@example.com",
        "auth_method": "local",
        "is_active": True,
        "require_password_change": False,
    }
    row.update(overrides)
    return row


def _request(*, user=None, headers=None, method=None, path=None):
    """A request double. `method`/`path` are optional because most dependencies here
    never look at them — but `is_internal_automation_request` does, and it fails
    closed when they are missing, so a test about the internal key has to supply
    them (see test_require_user_or_internal_accepts_the_key_only_on_an_allowed_route).
    """
    state = SimpleNamespace()
    if user is not None:
        state.user = user
    request = SimpleNamespace(state=state, headers=headers or {})
    if method is not None:
        request.method = method
    if path is not None:
        request.url = SimpleNamespace(path=path)
    return request


# Password and token helpers

def test_password_hash_round_trip_and_malformed_hash():
    hashed = auth._hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert auth._verify_password("correct horse battery staple", hashed) is True
    assert auth._verify_password("wrong", hashed) is False
    assert auth._verify_password("password", "not-a-bcrypt-hash") is False


def test_create_token_contains_identity_and_expiry(monkeypatch):
    monkeypatch.setattr(auth, "TOKEN_EXPIRE_HOURS", 3)

    token = auth._create_token(USER_ID, "alice", "admin")
    claims = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])

    assert claims["sub"] == USER_ID
    assert claims["username"] == "alice"
    assert claims["role"] == "admin"
    assert claims["exp"] > datetime.utcnow().timestamp()


# Dependencies and authorization policy

def test_require_user_reuses_middleware_identity(monkeypatch):
    expected = {"id": USER_ID, "username": "alice", "role": "viewer"}

    async def should_not_decode(*args, **kwargs):
        raise AssertionError("middleware identity should avoid a second token decode")

    monkeypatch.setattr(auth, "get_current_user", should_not_decode)

    assert _run(auth.require_user(_request(user=expected), None)) is expected


def test_require_user_rejects_missing_identity(monkeypatch):
    monkeypatch.setattr(auth, "get_current_user", _async_return(None))

    with pytest.raises(HTTPException) as exc:
        _run(auth.require_user(_request(), None))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Not authenticated"
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


def test_require_user_or_internal_accepts_the_key_only_on_an_allowed_route(monkeypatch):
    """The shared key is not a master key. It admits the automation principal on the
    two callback routes in `_INTERNAL_AUTOMATION_ROUTES` and nowhere else, so a key
    that leaks out of an in-cluster scheduler cannot be replayed against the rest of
    the API. Everything outside that allowlist falls through to `require_user`,
    which here has no identity to fall back on and answers 401."""
    monkeypatch.setenv("INTERNAL_API_KEY", "service-secret")
    monkeypatch.setattr(auth, "get_current_user", _async_return(None))
    key = {"X-Internal-Key": "service-secret"}

    service = _run(auth.require_user_or_internal(
        _request(headers=key, method="POST", path="/api/connectors/abc/sync"), None
    ))
    assert service == {
        "id": None,
        "username": "system",
        "role": "admin",
        "internal": True,
    }

    # Same valid key, a route that is not on the allowlist: no admission.
    for method, path in (("POST", "/api/queries/execute"), ("GET", "/api/connectors/abc/sync")):
        with pytest.raises(HTTPException) as exc:
            _run(auth.require_user_or_internal(
                _request(headers=key, method=method, path=path), None))
        assert exc.value.status_code == 401

    # And a request whose method/path cannot be read at all fails closed rather
    # than being treated as an allowed route.
    with pytest.raises(HTTPException):
        _run(auth.require_user_or_internal(_request(headers=key), None))

    assert auth._internal_request(_request(headers={"X-Internal-Key": "wrong"})) is False
    assert auth._internal_request(_request(headers={"X-Internal-Key": ""})) is False


def test_require_admin_rejects_viewer_and_accepts_admin():
    admin = {"id": USER_ID, "role": "admin"}
    assert _run(auth.require_admin(admin)) is admin

    with pytest.raises(HTTPException) as exc:
        _run(auth.require_admin({"id": USER_ID, "role": "viewer"}))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Admin required"


# Login behavior

def test_login_with_local_password_returns_user_and_signed_token(monkeypatch):
    row = _user_row(require_password_change=True)
    _patch_pool(monkeypatch, _FakeConn(row=row))
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(auth, "_verify_password", lambda password, hashed: password == "secret")

    response = _run(auth.login(auth.LoginRequest(username="alice", password="secret")))
    claims = jwt.decode(response.access_token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])

    assert response.token_type == "bearer"
    assert response.user == {
        "id": USER_ID,
        "username": "alice",
        "display_name": "Alice",
        "email": "alice@example.com",
        "role": "admin",
        "require_password_change": True,
    }
    assert claims["sub"] == USER_ID


def test_wrong_local_password_never_falls_through_to_ldap(monkeypatch):
    _patch_pool(monkeypatch, _FakeConn(row=_user_row()))
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(auth, "_verify_password", lambda *args: False)

    def should_not_check_ldap():
        raise AssertionError("LDAP must not shadow an existing local account")

    monkeypatch.setattr(ldap_auth, "ldap_enabled", should_not_check_ldap)

    with pytest.raises(HTTPException) as exc:
        _run(auth.login(auth.LoginRequest(username="alice", password="wrong")))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid username or password"


def test_login_provisions_successful_ldap_user(monkeypatch):
    ldap_row = _user_row(
        username="directory-user",
        auth_method="ldap",
        password_hash=None,
        role="viewer",
    )
    _patch_pool(monkeypatch, _FakeConn(row=None))
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(ldap_auth, "ldap_enabled", lambda: True)
    monkeypatch.setattr(
        ldap_auth,
        "ldap_authenticate",
        lambda username, password: {
            "username": username,
            "email": "directory@example.com",
            "display_name": "Directory User",
            "role": "viewer",
        },
    )
    monkeypatch.setattr(auth, "_upsert_ldap_user", _async_return(ldap_row))

    response = _run(auth.login(
        auth.LoginRequest(username="directory-user", password="directory-password")
    ))

    assert response.user["username"] == "directory-user"
    assert response.user["role"] == "viewer"


def test_login_rejects_unknown_user_when_ldap_disabled(monkeypatch):
    _patch_pool(monkeypatch, _FakeConn(row=None))
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(ldap_auth, "ldap_enabled", lambda: False)

    with pytest.raises(HTTPException) as exc:
        _run(auth.login(auth.LoginRequest(username="missing", password="wrong")))
    assert exc.value.status_code == 401


# Audit-stream wiring: login/logout write best-effort rows into auth_audit_log so the
# unified audit stream (Governance → Activity) has a real auth source.

def _audit_inserts(conn):
    return [c for c in conn.execute_calls if "auth_audit_log" in c[0]]


def test_successful_login_writes_login_success_audit_event(monkeypatch):
    conn = _FakeConn(row=_user_row())
    _patch_pool(monkeypatch, conn)
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(auth, "_verify_password", lambda password, hashed: True)

    _run(auth.login(auth.LoginRequest(username="alice", password="secret")))

    inserts = _audit_inserts(conn)
    assert len(inserts) == 1
    query, args, _ = inserts[0]
    assert "login_success" in args               # event_type
    assert "alice@example.com" in args           # user_email (denormalized actor)
    assert "success" in args


def test_failed_login_writes_login_failure_audit_event(monkeypatch):
    conn = _FakeConn(row=_user_row())
    _patch_pool(monkeypatch, conn)
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(auth, "_verify_password", lambda *args: False)
    monkeypatch.setattr(ldap_auth, "ldap_enabled", lambda: False)

    with pytest.raises(HTTPException):
        _run(auth.login(auth.LoginRequest(username="alice", password="wrong")))

    inserts = _audit_inserts(conn)
    assert len(inserts) == 1
    _, args, _ = inserts[0]
    assert "login_failure" in args
    assert "alice" in args                        # attempted username recorded as actor
    assert "failure" in args


def test_record_auth_event_never_raises_when_audit_write_fails(monkeypatch):
    # An audit-write failure must never propagate — authentication cannot be blocked
    # by the audit layer.
    async def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(auth, "_get_pool", _boom)
    # Returns cleanly despite the pool failure.
    _run(auth.record_auth_event("login_success", user_id=USER_ID, user_email="a@b.c"))


def test_record_auth_event_captures_ip_and_user_agent(monkeypatch):
    # The shared writer (also used by WebAuthn/OIDC success paths) pulls ip_address and
    # user_agent off the request and inserts the audit columns in the expected order.
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)
    req = SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.7"),
        headers={"user-agent": "pytest-agent/1.0"},
    )

    _run(auth.record_auth_event(
        "login_success", user_id=USER_ID, user_email="a@b.c", request=req,
    ))

    query, args, _ = _audit_inserts(conn)[0]
    assert "auth_audit_log" in query
    # (event_type, user_id, user_email, ip_address, user_agent, result, failure_reason, details)
    assert args[0] == "login_success"
    assert args[2] == "a@b.c"
    assert args[3] == "203.0.113.7"
    assert args[4] == "pytest-agent/1.0"


def test_logout_writes_audit_event_when_identity_present(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)
    req = _request(user={"id": USER_ID, "username": "alice", "role": "admin"})

    _run(auth.logout(req))

    inserts = _audit_inserts(conn)
    assert len(inserts) == 1
    _, args, _ = inserts[0]
    assert "logout" in args
    assert "alice" in args


def test_logout_is_noop_without_identity(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)

    result = _run(auth.logout(_request()))

    assert result == {"message": "Logged out"}
    assert _audit_inserts(conn) == []


# Password and user-management endpoints

def test_setup_password_rejects_short_password_without_db_access(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("DB should not be opened")),
    )

    with pytest.raises(HTTPException) as exc:
        _run(auth.setup_password(
            auth.SetupRequest(username="bob", password="short"),
            {"id": USER_ID, "role": "admin"},
        ))
    assert exc.value.status_code == 400


def test_setup_password_forces_change_on_next_login(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)
    monkeypatch.setattr(auth, "_hash_password", lambda password: "new-hash")

    result = _run(auth.setup_password(
        auth.SetupRequest(username="bob", password="long-enough", display_name="Bob"),
        {"id": USER_ID, "role": "admin"},
    ))

    query, args, _ = conn.execute_calls[0]
    assert "require_password_change = true" in query
    # Five arguments, not four: $5 is the caller-supplied real email, kept separate
    # from $1 so the ON CONFLICT branch can COALESCE(NULLIF($5, ''), users.email)
    # and leave an existing user's real address alone when none was supplied. This
    # request supplies none, so $5 is the empty string and $1 falls back to the
    # synthetic address a new user gets.
    assert args == ("bob@datapond.local", "bob", "new-hash", "Bob", "")
    assert result == {"message": "Password set for 'bob'"}


def test_change_password_updates_hash_and_clears_reset_flag(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)
    monkeypatch.setattr(auth, "_hash_password", lambda password: "changed-hash")

    result = _run(auth.change_password(
        {"new_password": "new-password"}, {"id": USER_ID, "role": "viewer"}
    ))

    query, args, _ = conn.execute_calls[0]
    assert "require_password_change=false" in query
    assert args[0] == "changed-hash"
    assert str(args[1]) == USER_ID
    assert result == {"message": "Password changed successfully"}


def test_list_users_normalizes_attributes_and_display_names(monkeypatch):
    created = datetime(2026, 7, 16, 1, 2, 3)
    rows = [
        {
            "id": USER_ID,
            "username": "alice",
            "email": None,
            "display_name": None,
            "role": "admin",
            "is_active": True,
            "require_password_change": False,
            "attributes": json.dumps({"department": "engineering"}),
            "created_at": created,
        },
        {
            "id": OTHER_USER_ID,
            "username": "bob",
            "email": "bob@example.com",
            "display_name": "Bob",
            "role": "viewer",
            "is_active": False,
            "require_password_change": True,
            "attributes": "invalid-json",
            "created_at": None,
        },
    ]
    _patch_pool(monkeypatch, _FakeConn(rows=rows))

    result = _run(auth.list_users({"id": USER_ID, "role": "admin"}))

    assert result[0]["display_name"] == "alice"
    assert result[0]["email"] == ""
    assert result[0]["attributes"] == {"department": "engineering"}
    assert result[0]["created_at"] == "2026-07-16T01:02:03Z"
    assert result[1]["attributes"] == {}
    assert result[1]["created_at"] is None


def test_update_user_builds_allowed_fields_and_syncs_role(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)

    result = _run(auth.update_user(
        OTHER_USER_ID,
        {
            "role": "viewer",
            "is_active": 0,
            "attributes": {"region": "ap-northeast-2"},
            "ignored": "value",
        },
        {"id": USER_ID, "role": "admin"},
    ))

    update_query, update_args, _ = conn.execute_calls[0]
    assert "role = $1" in update_query
    assert "is_active = $2" in update_query
    assert "attributes = $3::jsonb" in update_query
    assert "ignored" not in update_query
    assert update_args[:3] == ("viewer", False, '{"region": "ap-northeast-2"}')
    assert "DELETE FROM user_roles" in conn.execute_calls[1][0]
    assert "INSERT INTO user_roles" in conn.execute_calls[2][0]
    assert result == {"message": "User updated"}


def test_update_user_accepts_every_assignable_role_and_syncs_user_roles(monkeypatch):
    """The console offering only admin/viewer was a UI limitation, not an API one:
    PATCH /auth/users/{id} already accepts all seven roles in ASSIGNABLE_ROLES and
    already syncs user_roles — this test pins that so the settings-page rewrite
    (frontend/lib/user-roles.ts, app/settings/page.tsx) can rely on it rather than
    the route needing to change too. 0007_seed_roles.sql seeds `roles` with exactly
    these names, so the INSERT ... SELECT ... FROM roles WHERE name = $2 this issues
    finds a row for every one of them instead of silently binding nobody."""
    from app.permissions import ASSIGNABLE_ROLES

    for role in ASSIGNABLE_ROLES:
        conn = _FakeConn()
        _patch_pool(monkeypatch, conn)

        result = _run(auth.update_user(
            OTHER_USER_ID, {"role": role}, {"id": USER_ID, "role": "admin"},
        ))

        assert result == {"message": "User updated"}
        update_query, update_args, _ = conn.execute_calls[0]
        assert "role = $1" in update_query
        assert update_args[0] == role
        assert "DELETE FROM user_roles" in conn.execute_calls[1][0]
        insert_query, insert_args, _ = conn.execute_calls[2]
        assert "INSERT INTO user_roles" in insert_query
        assert "SELECT $1, id FROM roles WHERE name = $2" in insert_query
        assert insert_args[1] == role


def test_update_user_refuses_a_role_outside_assignable_roles(monkeypatch):
    from app.permissions import ASSIGNABLE_ROLES

    outside_role = "superuser"
    assert outside_role not in ASSIGNABLE_ROLES

    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)

    with pytest.raises(HTTPException) as exc:
        _run(auth.update_user(
            OTHER_USER_ID, {"role": outside_role}, {"id": USER_ID, "role": "admin"},
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail == "Nothing to update"
    assert conn.execute_calls == []


def test_update_user_rejects_empty_or_invalid_fields(monkeypatch):
    _patch_pool(monkeypatch, _FakeConn())

    with pytest.raises(HTTPException) as exc:
        _run(auth.update_user(
            OTHER_USER_ID,
            {"role": "owner", "attributes": "not-an-object"},
            {"id": USER_ID, "role": "admin"},
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail == "Nothing to update"


def test_delete_user_rejects_self_and_reports_missing_user(monkeypatch):
    admin = {"id": USER_ID, "role": "admin"}
    with pytest.raises(HTTPException) as exc:
        _run(auth.delete_user(USER_ID, admin))
    assert exc.value.status_code == 400

    _patch_pool(monkeypatch, _FakeConn(result="DELETE 0"))
    with pytest.raises(HTTPException) as exc:
        _run(auth.delete_user(OTHER_USER_ID, admin))
    assert exc.value.status_code == 404
    assert exc.value.detail == "User not found"
