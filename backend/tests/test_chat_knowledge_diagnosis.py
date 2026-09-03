"""Is this collection still worth querying?

The embedding-model check is why this action exists. A collection embedded with one
model and queried through another degrades retrieval silently: nothing errors, nothing
is logged, and the only symptom is worse answers.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.chat.analysis import knowledge as mod


def _run(c):
    return asyncio.run(c)


class _Conn:
    def __init__(self, row, chunks):
        self._row, self._chunks = row, chunks

    async def fetchrow(self, *a):
        return self._row

    async def fetchval(self, *a):
        return self._chunks


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _install(monkeypatch, row, chunks=100, model="embed"):
    pool = _Pool(_Conn(row, chunks))

    async def _get_pool():
        return pool

    monkeypatch.setattr("app.api.auth._get_pool", _get_pool)
    monkeypatch.setattr("app.api.ai_vectors._embed_model", lambda: model)


def test_a_model_mismatch_is_a_bad_signal(monkeypatch):
    _install(monkeypatch, {"id": "c1", "embed_model": "titan-v1", "refresh_enabled": True,
                           "refresh_interval_minutes": 60, "last_refreshed_at": None,
                           "last_refresh_status": "ok", "owner_id": "u1"},
             model="titan-v2")
    out = _run(mod.diagnose_collection({"collection": "handbook"}, {"id": "u1"}))
    bad = [s for s in out["signals"] if s["severity"] == "bad"]
    assert any("embed" in s["statement"].lower() for s in bad)
    assert out["facts"]["embed_model"] == "titan-v1"


def test_an_empty_collection_is_flagged(monkeypatch):
    _install(monkeypatch, {"id": "c1", "embed_model": "embed", "refresh_enabled": False,
                           "refresh_interval_minutes": None, "last_refreshed_at": None,
                           "last_refresh_status": None, "owner_id": "u1"}, chunks=0)
    out = _run(mod.diagnose_collection({"collection": "handbook"}, {"id": "u1"}))
    assert any(s["severity"] == "bad" for s in out["signals"])
    assert out["facts"]["chunks"] == 0


def test_a_collection_with_no_schedule_says_so_rather_than_calling_it_stale(monkeypatch):
    """Not scheduled is a choice, not a fault. Reporting it as staleness would train
    people to ignore the staleness signal."""
    _install(monkeypatch, {"id": "c1", "embed_model": "embed", "refresh_enabled": False,
                           "refresh_interval_minutes": None, "last_refreshed_at": None,
                           "last_refresh_status": None, "owner_id": "u1"})
    out = _run(mod.diagnose_collection({"collection": "handbook"}, {"id": "u1"}))
    assert any("not scheduled" in r.lower() for r in out["not_checked"])
    assert not any("stale" in s["statement"].lower() for s in out["signals"])


def test_an_unknown_collection_is_refused_not_diagnosed(monkeypatch):
    """No row at all: `_collection_id` (the same gate every route in
    app/api/ai_vectors.py runs before touching an existing collection) raises 404
    before diagnosis ever runs."""
    _install(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        _run(mod.diagnose_collection({"collection": "nope"}, {"id": "u1"}))
    assert exc.value.status_code == 404


# ── Critical 1: diagnose_collection must not bypass the collection access gate ──
# Before the fix this executor read `ai_collections` straight off the pool, by name,
# with no ownership/membership predicate — and `knowledge:read` is in `_READ_BASELINE`
# in app/permissions.py, so every role (including `viewer`) could name any collection
# at all and learn whether it exists, its embedding model, chunk count, refresh
# schedule and last refresh status. It must now go through the same `_collection_id`
# gate every other route in app/api/ai_vectors.py calls, and a caller who may not read
# the collection must get that gate's access failure, never a diagnosis.

def test_a_caller_who_may_not_read_the_collection_gets_the_access_failure(monkeypatch):
    """Owned by someone else, no membership grant, no admin role: `may_read` says no,
    and the caller must see that refusal — not a diagnosis built from a row they were
    never allowed to see."""
    _install(monkeypatch, {"id": "c1", "embed_model": "embed", "refresh_enabled": True,
                           "refresh_interval_minutes": 60, "last_refreshed_at": None,
                           "last_refresh_status": "ok", "owner_id": "someone-else"})
    with pytest.raises(HTTPException) as exc:
        _run(mod.diagnose_collection({"collection": "handbook"},
                                     {"id": "u1", "role": "viewer"}))
    assert exc.value.status_code == 403
