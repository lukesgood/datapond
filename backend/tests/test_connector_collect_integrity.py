"""
Unit tests: connector collect-side data-integrity fixes.

Two classes of bug are pinned here:

1. Non-SSE POST /connectors/{id}/sync (app.api.connectors.trigger_sync) used to run
   incremental syncs WITHOUT loading the stored watermark and WITHOUT persisting the
   returned max_value — so every run re-read the whole source table and appended,
   compounding row duplication. It also INSERTed a fresh job row every run instead of
   upserting by (connection, table). These tests pin: the watermark is loaded and
   forwarded, the new watermark is persisted via UPDATE, and no duplicate row is INSERTed.

2. DatabaseURLConnector.sync_to_iceberg (app.connectors.database) accepted
   pii_columns/key_columns but ignored them, blind-appended the whole table in one
   pandas read, and string-interpolated the incremental predicate (SQL injection).
   These tests pin: PII/key columns and chunking now flow through the shared
   _read_write_chunked helper, and the watermark value is bound as a parameter.
"""
import asyncio
import sys
import types
import uuid
from datetime import datetime

import pandas as pd

from app.connectors import database
from app.connectors.database import DatabaseURLConnector, DatabaseURLConfig
from app.connectors.base import ConnectorType, SyncMode, SyncStatus, SyncJobStatus


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── FIX #2: DatabaseURLConnector.sync_to_iceberg ─────────────────────────────

class _RecordingWriter:
    """Stand-in for write_dataframe_to_iceberg — records the call, returns row count."""
    def __init__(self):
        self.calls = []

    def __call__(self, df, table_name, mode="overwrite", on_step=None,
                 partition_spec=None, join_cols=None):
        self.calls.append({"rows": len(df), "table": table_name, "mode": mode,
                           "join_cols": join_cols})
        return len(df)


def _patch_writer(monkeypatch):
    """Inject a fake app.connectors.iceberg_writer so the lazy import inside
    _read_write_chunked resolves to our recorder (no pyarrow/pyiceberg needed)."""
    w = _RecordingWriter()
    fake = types.ModuleType("app.connectors.iceberg_writer")
    fake.write_dataframe_to_iceberg = w
    monkeypatch.setitem(sys.modules, "app.connectors.iceberg_writer", fake)
    return w


class _FakeConn:
    """Minimal DB connection: enter/exit no-op, ignores what it's handed."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def connect(self):
        return self

    def execution_options(self, **kw):
        return _FakeConn()


def test_read_write_chunked_binds_params_and_upserts(monkeypatch):
    # _read_write_chunked must: stream via chunksize, bind params (not interpolate),
    # upsert when key_columns + append mode, and track the watermark max.
    w = _patch_writer(monkeypatch)
    df = pd.DataFrame({"id": [1, 2], "ts": [10, 20]})
    captured = {}

    def fake_read_sql(sql, conn=None, chunksize=None, params=None):
        captured["sql"] = sql
        captured["chunksize"] = chunksize
        captured["params"] = params
        return iter([df])

    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    rows, max_value = database._read_write_chunked(
        _FakeEngine(), 'SELECT * FROM "t" WHERE "ts" > :last_value', "t",
        "append", "ts", key_columns=["id"], params={"last_value": 5})

    assert rows == 2
    assert max_value == "20"                       # watermark derived from the chunk
    assert captured["params"] == {"last_value": 5}  # value bound, never interpolated
    assert captured["chunksize"] == database.INGEST_CHUNK_SIZE  # streamed, not full load
    assert w.calls[0]["mode"] == "upsert" and w.calls[0]["join_cols"] == ["id"]
    # params present → query is wrapped as a bound SQLAlchemy text() statement
    from sqlalchemy.sql.elements import TextClause
    assert isinstance(captured["sql"], TextClause)


def _dburl_connector():
    return DatabaseURLConnector(DatabaseURLConfig(
        name="d", connector_type=ConnectorType.DATABASE_URL,
        database_url="sqlite:///:memory:"))


def test_dburl_incremental_parameterizes_and_forwards_columns(monkeypatch):
    captured = {}

    def fake_rwc(engine, query, source_table, write_mode, incremental_column,
                 on_step=None, partition_spec=None, key_columns=None,
                 pii_columns=None, chunk_size=database.INGEST_CHUNK_SIZE, params=None):
        captured.update(query=query, source_table=source_table, write_mode=write_mode,
                        incremental_column=incremental_column, key_columns=key_columns,
                        pii_columns=pii_columns, params=params)
        return 5, "2024-06-30"

    monkeypatch.setattr(database, "_read_write_chunked", fake_rwc)

    st = _run(_dburl_connector().sync_to_iceberg(
        "public.events", "iceberg.default.events",
        sync_mode=SyncMode.INCREMENTAL, incremental_column="updated_at",
        last_value="2024-01-01", key_columns=["id"], pii_columns=["email"]))

    assert st.status == SyncStatus.SUCCESS and st.rows_processed == 5
    assert st.metadata["max_value"] == "2024-06-30"
    # SQL injection fix: the watermark value is bound, never in the SQL text
    assert captured["params"] == {"last_value": "2024-01-01"}
    assert ":last_value" in captured["query"]
    assert "2024-01-01" not in captured["query"]
    # PII + key columns are actually forwarded now (were silently dropped before)
    assert captured["key_columns"] == ["id"] and captured["pii_columns"] == ["email"]
    assert captured["write_mode"] == "append"
    assert captured["source_table"] == "events"   # writes to the bare table name


def test_dburl_full_mode_overwrites_no_params(monkeypatch):
    captured = {}

    def fake_rwc(engine, query, source_table, write_mode, incremental_column,
                 on_step=None, partition_spec=None, key_columns=None,
                 pii_columns=None, chunk_size=database.INGEST_CHUNK_SIZE, params=None):
        captured.update(write_mode=write_mode, params=params, query=query)
        return 3, None

    monkeypatch.setattr(database, "_read_write_chunked", fake_rwc)

    st = _run(_dburl_connector().sync_to_iceberg(
        "events", "iceberg.default.events", sync_mode=SyncMode.FULL))

    assert st.status == SyncStatus.SUCCESS and st.rows_processed == 3
    assert captured["write_mode"] == "overwrite"
    assert captured["params"] is None
    assert "WHERE" not in captured["query"]


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
