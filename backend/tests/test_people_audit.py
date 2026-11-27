"""Deleting a person and changing a role or activation are audited (2026-11-27: a
deleted administrator left no trace; Governance → Activity showed sign-ins only)."""
import asyncio
import uuid
from types import SimpleNamespace

import app.api.auth as auth

UID = str(uuid.uuid4())


class _Conn:
    def __init__(self, row, result="DELETE 1"):
        self.row, self.result = row, result

    async def fetchrow(self, sql, *a):
        return self.row

    async def fetchval(self, sql, *a):
        return None

    async def execute(self, sql, *a):
        return self.result

    def transaction(self):
        class _T:
            async def __aenter__(s):
                return self

            async def __aexit__(s, *e):
                return False
        return _T()


def _setup(monkeypatch, conn):
    class _Acq:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *e):
            return False

    async def _pool():
        return SimpleNamespace(acquire=lambda: _Acq())
    events = []

    async def _event(kind, **kw):
        events.append((kind, kw))
    monkeypatch.setattr(auth, "_get_pool", _pool)
    monkeypatch.setattr(auth, "record_auth_event", _event)
    monkeypatch.setattr(auth, "forget_cached_keys_for", lambda *_: None)
    return events


ADMIN = {"id": str(uuid.uuid4()), "username": "luke"}


def test_a_deletion_records_who_was_deleted_and_by_whom(monkeypatch):
    events = _setup(monkeypatch, _Conn({"username": "caio", "email": "caio@x", "role": "admin"}))
    asyncio.run(auth.delete_user(UID, admin=ADMIN))
    kind, kw = events[0]
    assert kind == "user_deleted"
    assert kw["user_email"] == "caio@x"
    assert kw["details"] == {"by": "luke", "user_id": UID, "username": "caio", "role": "admin"}


def test_deactivation_and_role_changes_are_recorded(monkeypatch):
    events = _setup(monkeypatch, _Conn({"auth_method": "local"}, result="UPDATE 1"))
    asyncio.run(auth.update_user(UID, {"is_active": False}, admin=ADMIN))
    asyncio.run(auth.update_user(UID, {"role": "viewer"}, admin=ADMIN))
    asyncio.run(auth.update_user(UID, {"display_name": "C"}, admin=ADMIN))
    assert [e[0] for e in events] == ["account_deactivated", "role_assigned", "user_updated"]
    assert events[1][1]["details"]["role"] == "viewer"
