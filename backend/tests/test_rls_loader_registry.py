"""Policies and the catalog registry come from the same database; a policy whose
catalog is a registry name (AwsDataCatalog, 2.4 alias) can only be matched once the
registry has been read. Loading policies therefore makes sure the registry is loaded
too, so a boot where policies arrived first does not run them unmatched (fail-open)."""
import asyncio

import pytest

from app import catalog_registry as reg
from app.rls import loader


class _Conn:
    def __init__(self, rows): self._rows = rows
    async def fetch(self, *_a): return self._rows
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, rows): self._rows = rows; self._closed = False
    def acquire(self): return _Conn(self._rows)


_ROW = {"id": "p1", "catalog_name": "AwsDataCatalog", "schema_name": "sales", "table_name": "orders",
        "filter_expression": "region = 'x'", "priority": 0, "enabled": True,
        "role_name": None, "is_exempt": None}


@pytest.fixture(autouse=True)
def _clean():
    reg.reset(); yield; reg.reset()


def test_loading_policies_loads_the_registry_when_it_has_no_rows_yet(monkeypatch):
    calls = []
    async def fake_pool(): return _Pool([_ROW])
    async def fake_load(pool, *, force=False, timeout=5.0):
        calls.append(force)
        reg.set_entries([reg.CatalogEntry(name="AwsDataCatalog", kind="glue",
                                          engine_catalog="iceberg", is_default=True)])
        return reg.entries()
    monkeypatch.setattr(loader, "_get_pool", fake_pool)
    monkeypatch.setattr(reg, "load", fake_load)
    pols = asyncio.run(loader.load_policies())
    assert [p.catalog for p in pols] == ["AwsDataCatalog"]
    assert calls == [True]
    assert reg.canonical_catalog("AwsDataCatalog") == "iceberg"


def test_loading_policies_does_not_reload_a_registry_the_database_already_filled(monkeypatch):
    reg.set_entries([reg.CatalogEntry(name="iceberg", kind="glue", engine_catalog="iceberg", is_default=True)])
    calls = []
    async def fake_pool(): return _Pool([_ROW])
    async def fake_load(pool, *, force=False, timeout=5.0): calls.append(force); return reg.entries()
    monkeypatch.setattr(loader, "_get_pool", fake_pool)
    monkeypatch.setattr(reg, "load", fake_load)
    asyncio.run(loader.load_policies())
    assert calls == []


def test_an_unresolvable_policy_catalog_is_logged_not_dropped(monkeypatch, caplog):
    reg.set_entries([reg.CatalogEntry(name="iceberg", kind="glue", engine_catalog="iceberg", is_default=True)])
    async def fake_pool(): return _Pool([_ROW])
    monkeypatch.setattr(loader, "_get_pool", fake_pool)
    with caplog.at_level("WARNING"):
        pols = asyncio.run(loader.load_policies())
    assert len(pols) == 1
    assert any("AwsDataCatalog" in r.getMessage() and "p1" in r.getMessage() for r in caplog.records)
