"""
Unit tests: connector collect-side data-integrity fixes.

Two classes of bug are pinned here:

1. Non-SSE POST /connectors/{id}/sync (app.api.connectors.trigger_sync) used to run
   incremental syncs WITHOUT loading the stored watermark and WITHOUT persisting the
   returned max_value — so every run re-read the whole source table and appended,
   compounding row duplication. It also INSERTed a fresh job row every run instead of
   upserting by (connection, table). These tests pin: the watermark is loaded and
   forwarded, the new watermark is persisted via UPDATE, and no duplicate row is INSERTed.

2. (The pandas database path these tests also covered is gone: Trino-backed sources
   sync through Trino, tests/test_trino_sync_statements.py and
   tests/test_trino_source_sync.py pin the bound watermark and PII masking there.)
"""
import asyncio
import uuid
from datetime import datetime

from app.connectors.base import ConnectorType, SyncMode, SyncStatus, SyncJobStatus


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── FIX #1: non-SSE trigger_sync watermark load + persist ─────────────────────

class _StoreConn:
    """Fake asyncpg connection backed by a shared dict store."""
    def __init__(self, store):
        self.store = store

    async def fetchval(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT id FROM connector_sync_jobs"):
            return self.store.get("existing_id")
        return None  # partition_spec / key_columns / pii_columns loaders

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        if "SELECT incremental_column, last_value" in s:
            return self.store.get("watermark_row")
        if "FROM connector_connections" in s:
            # D2's ownership gate (app/api/source_access.resolve) runs before the sync
            # does. owner_id NULL is the state of every connector that predates 0006,
            # which is what the caller below is exercising.
            return {"id": args[0], "owner_id": None, "member_role": None}
        return None

    async def fetch(self, sql, *args):
        return []

    async def execute(self, sql, *args):
        self.store["executes"].append((" ".join(sql.split()), args))
        return "UPDATE 1"


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, store):
        self.store = store

    def acquire(self):
        return _Acquire(_StoreConn(self.store))


# Holds connector:write, is not an admin — the role that manages connectors, and the
# one D2 must keep working on an unowned (pre-0006) connector.
SYNC_USER = {"id": "00000000-0000-0000-0000-0000000000e1", "role": "data_engineer"}


def _afn(retval):
    async def f(*a, **k):
        return retval
    return f


def _patch_api(monkeypatch, store, capture):
    from app.api import connectors as C
    monkeypatch.setattr(C, "get_db_pool", _afn(_FakePool(store)))
    monkeypatch.setattr(C, "_get_connector_instance", _afn(object()))

    async def fake_swr(connector, on_retry=None, **kwargs):
        capture.update(kwargs)
        return SyncJobStatus(
            job_id=None, status=SyncStatus.SUCCESS,
            started_at=datetime.utcnow(), completed_at=datetime.utcnow(),
            rows_processed=7, rows_failed=0, metadata={"max_value": "2024-06-30"})

    monkeypatch.setattr(C, "_sync_with_retry", fake_swr)
    return C


def test_non_sse_incremental_loads_watermark_and_updates(monkeypatch):
    store = {
        "watermark_row": {"incremental_column": "updated_at", "last_value": "2024-01-01"},
        "existing_id": uuid.uuid4(),   # a job row already exists → UPDATE, not INSERT
        "executes": [],
    }
    capture = {}
    C = _patch_api(monkeypatch, store, capture)

    req = C.SyncRequest(source_table="events", sync_mode=SyncMode.INCREMENTAL)
    res = _run(C.trigger_sync("11111111-1111-1111-1111-111111111111", req, SYNC_USER))

    assert res["rows_processed"] == 7
    # the stored watermark is loaded and forwarded to the sync (was never loaded before)
    assert capture["last_value"] == "2024-01-01"
    assert capture["incremental_column"] == "updated_at"
    assert capture["sync_mode"] == SyncMode.INCREMENTAL

    upd = [e for e in store["executes"] if e[0].startswith("UPDATE connector_sync_jobs")]
    ins = [e for e in store["executes"] if e[0].startswith("INSERT INTO connector_sync_jobs")]
    assert upd and not ins                         # upsert, never a duplicate row
    # the returned max_value is persisted as the new watermark
    assert any(a == "2024-06-30" for a in upd[0][1])


def test_non_sse_incremental_without_column_falls_back_to_full(monkeypatch):
    # No incremental_column configured anywhere → must not run a key-less append
    # (which duplicates); fall back to full overwrite like the SSE path.
    store = {
        "watermark_row": {"incremental_column": None, "last_value": None},
        "existing_id": None,           # no prior job row → INSERT
        "executes": [],
    }
    capture = {}
    C = _patch_api(monkeypatch, store, capture)

    req = C.SyncRequest(source_table="events", sync_mode=SyncMode.INCREMENTAL)
    _run(C.trigger_sync("11111111-1111-1111-1111-111111111111", req, SYNC_USER))

    assert capture["sync_mode"] == SyncMode.FULL
    assert capture["last_value"] is None
