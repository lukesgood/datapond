"""
Unit tests for per-request token re-validation (JWT revocation via DB recheck).

A JWT is valid for 24h and is otherwise unrevocable, so get_current_user re-checks
the live users row on every request: a deactivated / deleted / role-changed account
must lose access before the token expires, while a transient DB error must NOT 401
every request (fail-open on infra, fail-closed on a definitive "revoked" answer).
"""
import asyncio
import uuid

from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

import app.api.auth as auth


VALID_UID = "00000000-0000-0000-0000-000000000001"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeConn:
    def __init__(self, row, raise_exc=None):
        self._row = row
        self._raise = raise_exc

    async def fetchrow(self, *a, **k):
        if self._raise:
            raise self._raise
        return self._row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, row, raise_exc=None):
        self._row = row
        self._raise = raise_exc

    def acquire(self):
        return _FakeConn(self._row, self._raise)


def _patch_pool(monkeypatch, row=None, raise_exc=None):
    async def _get_pool():
        return _FakePool(row, raise_exc)
    monkeypatch.setattr(auth, "_get_pool", _get_pool)


def _claims(role="admin", uid=VALID_UID):
    return {"id": uid, "username": "alice", "role": role}


# ── _recheck_user ────────────────────────────────────────────────────────────

def test_recheck_rejects_disabled_user(monkeypatch):
    _patch_pool(monkeypatch, row={"is_active": False, "role": "admin"})
    assert _run(auth._recheck_user(VALID_UID, _claims())) is None


def test_recheck_rejects_deleted_user(monkeypatch):
    _patch_pool(monkeypatch, row=None)   # no row = deleted
    assert _run(auth._recheck_user(VALID_UID, _claims())) is None


def test_recheck_refreshes_role_from_db(monkeypatch):
    # token says admin, DB says viewer -> downgrade takes effect immediately
    _patch_pool(monkeypatch, row={"is_active": True, "role": "viewer"})
    out = _run(auth._recheck_user(VALID_UID, _claims(role="admin")))
    assert out is not None and out["role"] == "viewer"


def test_recheck_fails_open_on_db_error(monkeypatch):
    # a transient DB blip must not 401 a valid, unexpired token
    _patch_pool(monkeypatch, raise_exc=RuntimeError("pool down"))
    out = _run(auth._recheck_user(VALID_UID, _claims(role="admin")))
    assert out is not None and out["role"] == "admin"


def test_recheck_rejects_malformed_sub(monkeypatch):
    _patch_pool(monkeypatch, row={"is_active": True, "role": "admin"})
    assert _run(auth._recheck_user("not-a-uuid", _claims(uid="not-a-uuid"))) is None


# ── get_current_user integration ─────────────────────────────────────────────

def _token(role="admin", uid=VALID_UID):
    return jwt.encode({"sub": uid, "username": "alice", "role": role},
                      auth.SECRET_KEY, algorithm=auth.ALGORITHM)


def _creds(tok):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)


def test_get_current_user_no_credentials():
    assert _run(auth.get_current_user(None)) is None


def test_get_current_user_rechecks_and_rejects_disabled(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_DB_RECHECK", True)
    _patch_pool(monkeypatch, row={"is_active": False, "role": "admin"})
    assert _run(auth.get_current_user(_creds(_token()))) is None


def test_get_current_user_recheck_disabled_skips_db(monkeypatch):
    # AUTH_DB_RECHECK off -> trust the token claims, never touch the DB
    monkeypatch.setattr(auth, "AUTH_DB_RECHECK", False)
    def _boom():
        raise AssertionError("_get_pool must not be called when recheck is off")
    monkeypatch.setattr(auth, "_get_pool", _boom)
    out = _run(auth.get_current_user(_creds(_token(role="admin"))))
    assert out is not None and out["role"] == "admin"
