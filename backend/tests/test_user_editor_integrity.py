"""The user editor cannot quietly break what other routes guarantee.

- `external_id` is what an IdP token is matched on (app/oauth_rs.py). Set through the
  user editor it skipped the checks `PUT /service-accounts/{id}/oauth-client` makes:
  one client per service account, and one subject per user. Two rows sharing a
  subject meant a token resolved to whichever the database returned first.
- A role change and its `user_roles` sync were two statements with the second's
  failure swallowed, so RLS role resolution could silently drift from `users.role`.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.auth as auth

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ID = "00000000-0000-0000-0000-000000000002"
ADMIN = {"id": USER_ID, "role": "admin"}


class _Conn:
    def __init__(self, *, target="local", subject_taken=False, fail_on=None):
        self.target, self.subject_taken, self.fail_on = target, subject_taken, fail_on
        self.executed, self.transactions = [], 0

    async def fetchrow(self, sql, *args):
        if "auth_method FROM users" in sql:
            return {"auth_method": self.target}
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if "external_id" in sql:
            return 1 if self.subject_taken else None
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("database refused")
        self.executed.append(sql)
        return "UPDATE 1"

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                conn.transactions += 1

            async def __aexit__(self, *exc):
                return False
        return _Tx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install(monkeypatch, conn):
    class _Pool:
        def acquire(self, *a, **k):
            return conn

    async def _pool():
        return _Pool()
    monkeypatch.setattr(auth, "_get_pool", _pool)


def test_a_service_account_s_subject_is_set_only_by_linking_its_client(monkeypatch):
    conn = _Conn(target="service")
    _install(monkeypatch, conn)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.update_user(OTHER_ID, {"external_id": "agent-client"}, ADMIN))
    assert exc.value.status_code == 400
    assert "oauth-client" in exc.value.detail
    assert conn.executed == []


def test_a_subject_another_user_holds_is_refused(monkeypatch):
    conn = _Conn(subject_taken=True)
    _install(monkeypatch, conn)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.update_user(OTHER_ID, {"external_id": "entra-oid"}, ADMIN))
    assert exc.value.status_code == 409
    assert conn.executed == []


def test_a_person_s_subject_can_be_set_and_cleared(monkeypatch):
    for value in ("entra-oid", None):
        conn = _Conn()
        _install(monkeypatch, conn)
        asyncio.run(auth.update_user(OTHER_ID, {"external_id": value}, ADMIN))
        assert any("external_id = $1" in sql for sql in conn.executed)


def test_a_role_change_and_its_user_roles_sync_are_one_transaction(monkeypatch):
    conn = _Conn()
    _install(monkeypatch, conn)
    asyncio.run(auth.update_user(OTHER_ID, {"role": "viewer"}, ADMIN))
    assert conn.transactions == 1


def test_a_failed_user_roles_sync_is_not_swallowed(monkeypatch):
    conn = _Conn(fail_on="INSERT INTO user_roles")
    _install(monkeypatch, conn)
    with pytest.raises(RuntimeError):
        asyncio.run(auth.update_user(OTHER_ID, {"role": "viewer"}, ADMIN))
