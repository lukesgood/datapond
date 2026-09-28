"""A credential handed to software cannot turn itself into more than it was issued as.

Two kinds of credential leave a person's hands: a `dp_sk_` API key, and an access
token from the customer's IdP (app/oauth_rs.py). Both carry a permission set narrower
than the account's role, and that narrowing is the whole promise. Three paths used to
undo it:

- `/auth/change-password` accepted either credential, and login would then issue a
  session for any row with a password — a session with the full role, no scopes, no
  per-key rate limit, and one that outlives revoking the key.
- `require_admin` / `require_human` refused API keys but not IdP tokens, so a token
  scoped to `knowledge:read` on an admin account could mint service-account keys and
  approve its own assistant actions.
- `/catalog/tables/{ns}/{t}/preview` read raw rows with no permission, RLS, masking or
  audit — everything `/queries/execute` enforces.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.auth as auth
from app.chat import gate

USER_ID = "00000000-0000-0000-0000-000000000001"

API_KEY = {"id": USER_ID, "username": "svc-bot", "role": "admin",
           "auth_method": "service", "api_key_id": "k1",
           "permissions": ["knowledge:read"]}
IDP_TOKEN = {"id": USER_ID, "username": "ada", "role": "admin",
             "auth_method": "oidc", "oauth": True,
             "permissions": ["knowledge:read"]}
SESSION = {"id": USER_ID, "username": "ada", "role": "admin"}


def _run(coro):
    return asyncio.run(coro)


def _async_return(value=None):
    async def _call(*args, **kwargs):
        return value
    return _call


class _Conn:
    def __init__(self, *, row=None, result="UPDATE 1"):
        self.row = row
        self.result = result
        self.execute_calls = []

    async def fetchrow(self, query, *args, **kwargs):
        return self.row

    async def execute(self, query, *args, **kwargs):
        self.execute_calls.append((query, args))
        return self.result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_pool(monkeypatch, conn):
    pool = SimpleNamespace(acquire=lambda *a, **k: conn)
    monkeypatch.setattr(auth, "_get_pool", _async_return(pool))


# ── change-password ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("principal", [API_KEY, IDP_TOKEN], ids=["api-key", "idp-token"])
def test_a_delegated_credential_cannot_set_a_password(monkeypatch, principal):
    conn = _Conn()
    _patch_pool(monkeypatch, conn)
    with pytest.raises(HTTPException) as exc:
        _run(auth.change_password({"new_password": "long-enough"}, principal))
    assert exc.value.status_code == 403
    assert conn.execute_calls == []


def test_a_session_may_only_set_a_password_on_a_local_account(monkeypatch):
    conn = _Conn(result="UPDATE 0")   # the row is ldap / oidc / service
    _patch_pool(monkeypatch, conn)
    with pytest.raises(HTTPException) as exc:
        _run(auth.change_password({"new_password": "long-enough"}, SESSION))
    assert exc.value.status_code == 403
    query, _ = conn.execute_calls[0]
    assert "auth_method = 'local'" in query


# ── login ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method", ["service", "oidc"])
def test_login_refuses_an_account_that_does_not_sign_in_with_a_password(monkeypatch, method):
    row = {"id": USER_ID, "username": "svc-bot", "password_hash": "h", "role": "admin",
           "display_name": None, "email": None, "auth_method": method,
           "is_active": True, "require_password_change": False}
    _patch_pool(monkeypatch, _Conn(row=row))
    monkeypatch.setattr(auth, "_ensure_admin_exists", _async_return())
    monkeypatch.setattr(auth, "_verify_password", lambda *a: True)
    monkeypatch.setattr(auth, "record_auth_event", _async_return())
    with pytest.raises(HTTPException) as exc:
        _run(auth.login(auth.LoginRequest(username="svc-bot", password="right")))
    assert exc.value.status_code == 401


# ── admin and human-only guards ───────────────────────────────────────────────

@pytest.mark.parametrize("principal", [API_KEY, IDP_TOKEN], ids=["api-key", "idp-token"])
def test_require_admin_refuses_a_delegated_credential_on_an_admin_account(principal):
    with pytest.raises(HTTPException) as exc:
        _run(auth.require_admin(principal))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("principal", [API_KEY, IDP_TOKEN], ids=["api-key", "idp-token"])
def test_require_human_refuses_a_delegated_credential(principal):
    with pytest.raises(HTTPException) as exc:
        _run(auth.require_human(user=principal))
    assert exc.value.status_code == 403


def test_an_admin_session_still_passes_both_guards():
    assert _run(auth.require_admin(SESSION)) is SESSION
    assert _run(auth.require_human(user=SESSION)) is SESSION


def test_the_approval_gate_refuses_an_idp_token(monkeypatch):
    class _Store:
        async def get(self, _id):
            return {"status": "proposed", "user_id": USER_ID, "action_id": "x"}
    monkeypatch.setattr(gate, "_require_owner", lambda inv, user: None)
    monkeypatch.setattr(gate, "_audit", _async_return())
    with pytest.raises(gate.ActionRefused):
        _run(gate.approve("inv-1", user=IDP_TOKEN, store=_Store()))
