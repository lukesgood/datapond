"""Governance reads name each table's real catalog.

rls_coverage stamped every table with one env catalog, so a policy on
finance.ledger.entries looked orphaned and the table it protects looked uncovered —
or, worse, a table of the second catalog looked covered by the first's policy.
"""
import asyncio
from types import SimpleNamespace

import pytest

from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry


def _run(coro):
    return asyncio.run(coro)


class _Reader:
    def __init__(self, tree):
        self.tree = tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]


READERS = {"iceberg": _Reader({"sales": ["orders"]}),
           "finance": _Reader({"ledger": ["entries"]})}


@pytest.fixture
def two_catalogs(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    import app.api.catalog_backend as cb
    monkeypatch.setattr(cb, "get_catalog_reader",
                        lambda name=None: READERS[reg.resolve(name).name])
    yield
    reg.reset()


def _policy(catalog, schema, table):
    return SimpleNamespace(catalog=catalog, schema=schema, table=table)


def test_coverage_names_each_tables_own_catalog(two_catalogs, monkeypatch):
    from app.api import governance
    from app.rls import loader

    async def policies():
        return [_policy("finance", "ledger", "entries")]

    async def masks():
        return []

    monkeypatch.setattr(loader, "load_policies", policies)
    monkeypatch.setattr(loader, "load_masks", masks)
    out = _run(governance.rls_coverage(user=None))
    assert out["covered"] == ["finance.ledger.entries"]
    assert out["uncovered"] == ["iceberg.sales.orders"]
    assert out["orphaned_policies"] == []
    assert out["catalog_error"] is None


def test_the_rls_default_catalog_comes_from_the_registry_when_it_has_rows(monkeypatch):
    from app.rls.engine import _default_catalog
    monkeypatch.setenv("RLS_DEFAULT_CATALOG", "iceberg")
    assert _default_catalog() == "iceberg"
    reg.set_entries([CatalogEntry(name="lake", kind="polaris", engine_catalog="lake",
                                  is_default=True)])
    try:
        assert _default_catalog() == "lake"
    finally:
        reg.reset()
    # And env again once the registry is forgotten: the fallback is unchanged.
    assert _default_catalog() == "iceberg"


def test_the_trino_pii_scan_reads_the_default_catalog(monkeypatch):
    from app.api import governance
    reg.set_entries([CatalogEntry(name="lake", kind="polaris", engine_catalog="lake",
                                  is_default=True)])
    seen = {}

    class _Cur:
        def execute(self, sql):
            seen["sql"] = sql

        def fetchall(self):
            return []

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass

    def connect(**kw):
        seen["catalog"] = kw.get("catalog")
        return _Conn()

    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "polaris")
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    monkeypatch.setattr(governance, "TRINO_AVAILABLE", True)
    monkeypatch.setattr(governance, "trino_connect", connect, raising=False)
    try:
        assert governance._scan_pii_tables() == []
    finally:
        reg.reset()
    assert seen["catalog"] == "lake"
    assert "FROM lake.information_schema.columns" in seen["sql"]
