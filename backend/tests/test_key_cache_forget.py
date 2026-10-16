"""Disabling or re-roling a service account takes effect on this replica at once.

A key is resolved from the database and cached for `_KEY_CACHE_TTL` seconds per replica.
Without dropping the account's entries, the replica that served "disable this agent"
kept answering the agent's calls for up to that long; other replicas still do, which is
why the console says "within 30 seconds".
"""
import asyncio
import time

import pytest

import app.api.auth as auth

BOT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "role": "admin"}


def _identity(user_id):
    return {"id": user_id, "username": "svc-x", "role": "ai_engineer", "auth_method": "service"}


@pytest.fixture(autouse=True)
def _cache():
    auth._KEY_CACHE.clear()
    yield
    auth._KEY_CACHE.clear()


def _seed():
    now = time.monotonic()
    auth._KEY_CACHE["bot-1"] = (_identity(BOT), now)
    auth._KEY_CACHE["bot-2"] = (_identity(BOT.upper()), now)
    auth._KEY_CACHE["other"] = (_identity(OTHER), now)
    auth._KEY_CACHE["invalid"] = (None, now)        # a known-bad key has no identity


def test_forget_only_that_user():
    _seed()
    assert auth.forget_cached_keys_for(BOT) == 2
    assert set(auth._KEY_CACHE) == {"other", "invalid"}
    assert auth.forget_cached_keys_for(BOT) == 0


class _Conn:
    def __init__(self):
        self.executed = []

    async def fetchrow(self, sql, *args):
        return {"auth_method": "service"}

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "UPDATE 1"

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False
        return _Tx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch(monkeypatch, conn):
    class _Pool:
        def acquire(self, *a, **k):
            return conn

    async def _pool():
        return _Pool()
    monkeypatch.setattr(auth, "_get_pool", _pool)


def test_patch_role_drops_cached_keys(monkeypatch):
    conn = _Conn()
    _patch(monkeypatch, conn)
    _seed()
    asyncio.run(auth.update_user(BOT, {"role": "viewer"}, ADMIN))
    assert set(auth._KEY_CACHE) == {"other", "invalid"}


def test_patch_is_active_drops_cached_keys(monkeypatch):
    _patch(monkeypatch, _Conn())
    _seed()
    asyncio.run(auth.update_user(BOT, {"is_active": False}, ADMIN))
    assert set(auth._KEY_CACHE) == {"other", "invalid"}


def test_patch_of_something_else_leaves_the_cache(monkeypatch):
    _patch(monkeypatch, _Conn())
    _seed()
    asyncio.run(auth.update_user(BOT, {"display_name": "Bot"}, ADMIN))
    assert len(auth._KEY_CACHE) == 4
