"""The owner/mirror rule on /queries/execute (app/table_links.py): a write to a mirror is
refused with 409 naming the owner, and a read of a mirror runs against the owner — under
the owner catalog's grant."""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.queries as q
from app import catalog_access, table_links
from app import catalog_registry as reg
from app.api.table_resolver import CatalogIndex
from app.catalog_registry import CatalogEntry

WRITER = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "data_engineer",
          "permissions": ["query:run", "query:write"]}
READER = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "viewer",
          "permissions": ["query:run"]}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Req:
    def __init__(self, query):
        self.query, self.save_history, self.origin = query, False, "ui"


class _Engine:
    rls_dialect = "trino"
    default_catalog = "iceberg"
    default_schema = "default"

    def __init__(self):
        self.ran = []

    def execute(self, sql, user):
        self.ran.append(sql)
        return [[1]], ["n"]

    def map_error(self, e):
        return "error", str(e), 500


@pytest.fixture
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="glue", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake"),
    ])
    catalog_access.set_grants({})
    table_links.set_links(table_links.Links.from_rows([{
        "mirror_catalog": "polaris_lake", "mirror_schema": "default", "mirror_table": "orders",
        "owner_catalog": "iceberg", "owner_schema": "default", "owner_table": "orders"}]))

    async def _load(pool, force=False):
        return table_links.current()
    monkeypatch.setattr(table_links, "load", _load)

    async def _pool():
        return object()
    monkeypatch.setattr(q, "_links_pool", _pool, raising=False)
    engine = _Engine()
    monkeypatch.setattr(q, "get_engine", lambda: engine)
    monkeypatch.setattr(q, "get_catalog_index", lambda: CatalogIndex(
        namespaces=("default",), tables={"orders": ("default",)}, default_catalog="iceberg"))
    audited = []

    async def _record(**kw):
        audited.append(kw)
    monkeypatch.setattr(q.security_audit, "record", _record)
    monkeypatch.setattr(q, "RLS_ENABLED", False)
    yield engine, audited
    table_links.set_links(table_links.Links())
    reg.reset()


@pytest.mark.parametrize("sql", [
    "INSERT INTO polaris_lake.default.orders VALUES (1)",
    "DELETE FROM polaris_lake.default.orders",
    "DROP TABLE polaris_lake.default.orders",
    "ALTER TABLE polaris_lake.default.orders ADD COLUMN c varchar",
])
def test_a_write_to_a_mirror_is_refused_with_409_and_audited(world, sql):
    engine, audited = world
    with pytest.raises(HTTPException) as e:
        _run(q._execute_query_impl(_Req(sql), db=None, user=WRITER))
    assert e.value.status_code == 409
    assert "iceberg.default.orders" in e.value.detail
    assert engine.ran == [], "nothing reached the engine"
    assert audited and audited[-1]["outcome"] == "denied"


def test_a_write_to_the_owner_runs(world):
    engine, _ = world
    _run(q._execute_query_impl(_Req("INSERT INTO iceberg.default.orders VALUES (1)"), db=None, user=WRITER))
    assert engine.ran and "iceberg.default.orders" in engine.ran[0]


def test_a_read_of_the_mirror_runs_against_the_owner(world):
    engine, _ = world
    _run(q._execute_query_impl(_Req("SELECT count(*) FROM polaris_lake.default.orders"), db=None, user=READER))
    assert "polaris_lake" not in engine.ran[0].lower() and "iceberg.default.orders" in engine.ran[0].lower()


def test_the_owner_catalog_grant_decides_a_mirror_read(world):
    """Granted on the mirror catalog, not on the owner's: a mirror must not be a way around
    the owner's grant."""
    engine, _ = world
    catalog_access.set_grants({"iceberg": [("role", "data_engineer")]})
    with pytest.raises(HTTPException) as e:
        _run(q._execute_query_impl(_Req("SELECT count(*) FROM polaris_lake.default.orders"), db=None, user=READER))
    assert e.value.status_code == 403 and engine.ran == []
