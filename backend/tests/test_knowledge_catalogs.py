"""Knowledge reads a source table from the catalog it names.

`_read_iceberg_docs` always read the engine's default prefix, and the sink and the
lineage graph matched on (namespace, table) alone — so a collection fed from
finance.sales.orders was re-embedded from, marked stale by, and drawn downstream of
the default catalog's sales.orders.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.ai_vectors as v
from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry


@pytest.fixture(autouse=True)
def two_catalogs():
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance_trino"),
    ])
    yield
    reg.reset()


def _src(**kw):
    return v.SourceIngest(type="iceberg", schema="sales", table="orders",
                          text_column="note", **kw)


def test_source_group_names_only_a_non_default_catalog():
    """Existing chunks were stored under the two-part group; the default keeps it so a
    re-embed still replaces them instead of duplicating."""
    assert v._source_group(_src()) == "iceberg:sales.orders.note"
    assert v._source_group(_src(catalog="iceberg")) == "iceberg:sales.orders.note"
    assert v._source_group(_src(catalog="finance")) == "iceberg:finance.sales.orders.note"


def test_the_stored_schedule_names_only_a_non_default_catalog():
    assert "catalog" not in v._stored_source(_src(catalog="ICEBERG"))
    assert v._stored_source(_src(catalog="finance"))["catalog"] == "finance"
    assert v._stored_source(_src())["schema"] == "sales"


def _capture_trino(monkeypatch):
    captured = {}

    class _Eng:
        ai_table_prefix = "iceberg"

    class _Cur:
        def execute(self, sql):
            captured["sql"] = sql

        def fetchall(self):
            return [("hello",)]

    class _TConn:
        def cursor(self):
            return _Cur()

    import app.api.query_engine as qe
    import app.api.trino_util as tu
    monkeypatch.setattr(qe, "get_engine", lambda: _Eng())
    monkeypatch.setattr(tu, "trino_conn", lambda timeout=60: _TConn())
    return captured


def test_a_non_default_catalog_is_read_from_its_engine_catalog(monkeypatch):
    captured = _capture_trino(monkeypatch)
    docs = v._read_iceberg_docs("sales", "orders", "note", 10, catalog="finance")
    assert 'FROM finance_trino."sales"."orders"' in captured["sql"]
    assert docs[0][0] == "finance_trino.sales.orders.note"


def test_the_default_catalog_reads_as_before(monkeypatch):
    captured = _capture_trino(monkeypatch)
    v._read_iceberg_docs("sales", "orders", "note", 10)
    assert 'FROM iceberg."sales"."orders"' in captured["sql"]


def test_an_unknown_catalog_is_refused_before_anything_is_read():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(v._refresh_from_source(None, "cid", _src(catalog="nope")))
    assert exc.value.status_code == 400


# ── catalog grants (multi-catalog P3) ─────────────────────────────────────────
# Reading a hidden catalog's column into a collection the caller can search would read
# the catalog by another door; the ingest routes answer it as an unknown catalog.

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "role": "ai_engineer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "role": "ai_engineer"}


class _KConn:
    def __init__(self):
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        self.executed.append(sql)


class _KPool:
    def __init__(self):
        self.conn = _KConn()

    def acquire(self, timeout=None):
        return self.conn


@pytest.fixture
def ingest_world(monkeypatch):
    from app import catalog_access
    catalog_access.set_grants({"finance": [("user", BOB["id"])]})
    pool, refreshed = _KPool(), []

    async def _get_pool():
        return pool

    async def _coll(c, name, user, write=False):
        return "cid"

    async def _refresh(p, coll_id, src):
        refreshed.append(src.catalog)
        return {"documents": 0}
    monkeypatch.setattr(v, "get_db_pool", _get_pool)
    monkeypatch.setattr(v, "_collection_id", _coll)
    monkeypatch.setattr(v, "_refresh_from_source", _refresh)
    monkeypatch.setattr(v, "set_actor", lambda user: None)
    return pool, refreshed


def test_ingest_source_from_a_hidden_catalog_is_404_like_an_unknown_one(ingest_world):
    _, refreshed = ingest_world
    with pytest.raises(HTTPException) as hidden:
        asyncio.run(v.ingest_source("docs", _src(catalog="finance"), ALICE))
    with pytest.raises(HTTPException) as unknown:
        asyncio.run(v.ingest_source("docs", _src(catalog="nope"), ALICE))
    assert hidden.value.status_code == unknown.value.status_code == 404
    assert hidden.value.detail == "Unknown catalog 'finance'. Known catalogs: iceberg."
    assert refreshed == []
    asyncio.run(v.ingest_source("docs", _src(catalog="finance"), BOB))
    assert refreshed == ["finance"]


def test_a_schedule_on_a_hidden_catalog_is_404_and_not_stored(ingest_world):
    pool, _ = ingest_world
    with pytest.raises(HTTPException) as exc:
        asyncio.run(v.schedule_ingest(
            "docs", v.ScheduleRequest(source=_src(catalog="finance")), ALICE))
    assert exc.value.status_code == 404
    assert pool.conn.executed == []
    asyncio.run(v.schedule_ingest(
        "docs", v.ScheduleRequest(source=_src(catalog="finance")), BOB))
    assert any("refresh_source" in sql for sql in pool.conn.executed)


def test_the_internal_automation_principal_reads_any_catalog(ingest_world):
    _, refreshed = ingest_world
    internal = {"id": None, "username": "system", "role": "admin", "internal": True}
    asyncio.run(v.ingest_source("docs", _src(catalog="finance"), internal))
    assert refreshed == ["finance"]


# ── lineage ──────────────────────────────────────────────────────────────────

def _conn():
    return {"id": "c1", "name": "crm", "connector_type": "postgresql"}


def _job():
    return {"connection_id": "c1", "source_table": "public.orders",
            "target_table": "datapond.sales.orders", "last_run_status": "success"}


def _coll(name, catalog=None):
    src = {"type": "iceberg", "schema": "sales", "table": "orders"}
    if catalog:
        src["catalog"] = catalog
    return {"name": name, "refresh_source": src, "refresh_enabled": True}


def test_a_collection_of_another_catalog_is_not_downstream_of_a_default_sync():
    out = v.build_lineage([_conn()], [_job()],
                          [_coll("default-kb"), _coll("finance-kb", "finance")],
                          default_catalog="iceberg")
    targets = {e["target"] for e in out["edges"]}
    assert "collection:default-kb" in targets
    assert "collection:finance-kb" not in targets


def test_a_collection_naming_the_default_catalog_still_matches():
    out = v.build_lineage([_conn()], [_job()], [_coll("kb", "ICEBERG")],
                          default_catalog="iceberg")
    assert any(e["target"] == "collection:kb" for e in out["edges"])


# ── sink invalidation ────────────────────────────────────────────────────────

def test_sink_invalidation_matches_only_default_catalog_sources(monkeypatch):
    """Connector syncs write to the default catalog; a collection reading another
    catalog's table of the same name must not be marked stale by them."""
    import app.api.connectors as c

    class _Conn:
        def __init__(self):
            self.sink = []

        async def execute(self, sql, *a):
            self.sink.append((sql, a))
            return "UPDATE 1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

    class _Pool:
        def __init__(self, conn):
            self.c = conn

        def acquire(self):
            return self.c

    monkeypatch.setenv("RAG_SINK_ENABLED", "true")
    conn = _Conn()
    asyncio.run(c._invalidate_sink_collections(
        _Pool(conn), [("orders", "datapond.sales.orders", True, 1, None)]))
    sql, args = conn.sink[0]
    assert "refresh_source->>'catalog' IS NULL" in sql
    assert "lower(refresh_source->>'catalog') = ANY($3::text[])" in sql
    assert sorted(args[2]) == ["iceberg"]
