"""The catalog list says what each table is (usability review 2026-11-20): a read-only
mirror and of what, the source connection that syncs it, and whether it is a live source
database table. All advisory — without the database the list is names only."""
import asyncio
from datetime import datetime

import pytest

import app.api.catalog as catalog
from app import catalog_registry as reg
from app import table_links
from app.catalog_registry import CatalogEntry

VIEWER = {"id": "11111111-1111-1111-1111-111111111111", "role": "admin"}


class _Reader:
    def __init__(self, tree):
        self.tree = tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]


READERS = {
    "AwsDataCatalog": _Reader({"default": ["orders", "events"]}),
    "polaris_lake": _Reader({"default": ["orders"]}),
    "src_shop": _Reader({"public": ["carts"]}),
}


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        return [{"connection_id": "c1", "name": "Shop DB", "source_table": "public.orders",
                 "target_table": "datapond.default.public.orders", "target_catalog": None,
                 "last_run_at": datetime(2026, 11, 20, 3, 0), "rows_synced": 6000,
                 "last_run_status": "success"}]


class _Pool:
    def acquire(self):
        return _Conn()


@pytest.fixture
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake"),
        CatalogEntry(name="src_shop", kind="trino_source", engine_catalog="src_shop"),
    ])
    monkeypatch.setattr(catalog, "get_catalog_reader", lambda name=None: READERS[reg.resolve(name).name])
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")

    async def _pool():
        return _Pool()
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _pool)

    async def _load(pool, force=False):
        return table_links.Links({("polaris_lake", "default", "orders"): ("iceberg", "default", "orders")})
    monkeypatch.setattr(table_links, "load", _load)
    yield
    reg.reset()


def _tables():
    res = asyncio.run(catalog.list_all_tables(user=VIEWER))
    return {(t.catalog, t.namespace, t.name): t for t in res.tables}


def test_mirror_sync_source_and_live_are_reported(world):
    t = _tables()
    assert t[("polaris_lake", "default", "orders")].mirror_of == "iceberg.default.orders"
    assert t[("iceberg", "default", "orders")].mirror_of is None
    s = t[("iceberg", "default", "orders")].synced_from
    assert s["connection"] == "Shop DB" and s["rows"] == 6000
    assert s["last_run_at"].endswith("+00:00")      # stored naive UTC, sent as UTC
    assert t[("iceberg", "default", "events")].synced_from is None
    carts = t[("src_shop", "public", "carts")]
    assert carts.live is True and carts.table_type == "source"
    assert t[("iceberg", "default", "events")].live is False


def test_without_the_database_the_list_is_names_only(world, monkeypatch):
    import app.api.connectors as connectors

    async def _broken():
        raise RuntimeError("no database")
    monkeypatch.setattr(connectors, "get_db_pool", _broken)
    t = _tables()
    assert len(t) == 4
    assert all(x.mirror_of is None and x.synced_from is None for x in t.values())
