"""Catalog grants on the catalog routes (multi-catalog P3).

A catalog a caller may not use is absent from every listing — namespaces, tables, the
schema tree (which the Knowledge picker reads), the relationship graph, /api/catalogs —
and a detail route answers it exactly as it answers a catalog that does not exist.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.catalog as catalog
import app.api.catalog_admin as catalog_admin
import app.api.queries as queries
from app import catalog_access
from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "auditor"}
ADMIN = {"id": "33333333-3333-3333-3333-333333333333", "username": "root", "role": "admin"}
ADMIN_KEY = {**ADMIN, "auth_method": "service"}


def _run(coro):
    return asyncio.run(coro)


class _Reader:
    def __init__(self, name, tree):
        self.name, self.tree = name, tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]

    def get_columns(self, ns, t):
        return [{"name": f"{self.name}_col", "type": "varchar", "nullable": True}]

    def get_location(self, ns, t):
        return f"s3://{self.name}/{ns}/{t}"

    def row_count(self, ns, t):
        return 3


READERS = {
    "iceberg": _Reader("iceberg", {"sales": ["orders"]}),
    "finance": _Reader("finance", {"ledger": ["entries"]}),
}


@pytest.fixture(autouse=True)
def two_catalogs(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    catalog_access.set_grants({"finance": [("user", BOB["id"])]})

    def reader(name=None):
        return READERS[reg.resolve(name).name]

    monkeypatch.setattr(catalog, "get_catalog_reader", reader)
    import app.api.catalog_backend as cb
    monkeypatch.setattr(cb, "get_catalog_reader", reader)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    yield
    reg.reset()


def _catalogs_in_tables(user):
    return {t.catalog for t in _run(catalog.list_all_tables(user=user)).tables}


def test_an_open_catalog_is_listed_for_everyone():
    catalog_access.set_grants({})
    assert _catalogs_in_tables(ALICE) == {"iceberg", "finance"}


def test_a_restricted_catalog_is_left_out_of_the_listings():
    assert _catalogs_in_tables(ALICE) == {"iceberg"}
    assert {n.catalog for n in _run(catalog.list_all_namespaces(user=ALICE)).namespaces} \
        == {"iceberg"}
    tree = _run(queries.get_catalog_schemas(user=ALICE))
    assert [c.name for c in tree.catalogs] == ["iceberg"]


@pytest.mark.parametrize("who,grants", [
    (BOB, {"finance": [("user", BOB["id"])]}),
    (BOB, {"finance": [("role", "auditor")]}),
    (ADMIN, {"finance": [("user", BOB["id"])]}),
])
def test_a_grant_or_an_admin_session_lists_it(who, grants):
    catalog_access.set_grants(grants)
    assert _catalogs_in_tables(who) == {"iceberg", "finance"}
    assert [c.name for c in _run(queries.get_catalog_schemas(user=who)).catalogs] == \
        ["iceberg", "finance"]


def test_an_admin_accounts_key_without_a_grant_does_not_list_it():
    assert _catalogs_in_tables(ADMIN_KEY) == {"iceberg"}


def test_a_cached_schema_tree_is_filtered_per_caller(monkeypatch):
    import sys
    import types
    cached = queries.CatalogTree(catalogs=[
        queries.Catalog(name="iceberg", schemas=[]),
        queries.Catalog(name="finance", schemas=[])]).model_dump_json()

    class _Redis:
        @classmethod
        def from_url(cls, *a, **k):
            return cls()

        def get(self, key):
            return cached

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_Redis))
    assert [c.name for c in _run(queries.get_catalog_schemas(user=ALICE)).catalogs] == \
        ["iceberg"]
    assert [c.name for c in _run(queries.get_catalog_schemas(user=BOB)).catalogs] == \
        ["iceberg", "finance"]


# ── detail: a hidden catalog is an unknown one ────────────────────────────────

def _status_and_detail(coro):
    with pytest.raises(HTTPException) as exc:
        _run(coro)
    return exc.value.status_code, exc.value.detail


def test_table_detail_of_a_hidden_catalog_is_the_unknown_catalog_404():
    hidden = _status_and_detail(
        catalog.get_table_details("ledger", "entries", catalog="finance", user=ALICE))
    unknown = _status_and_detail(
        catalog.get_table_details("ledger", "entries", catalog="nope", user=ALICE))
    assert hidden[0] == unknown[0] == 404
    assert hidden[1] == unknown[1].replace("nope", "finance")
    assert hidden[1] == "Unknown catalog 'finance'. Known catalogs: iceberg."


def test_columns_and_preview_of_a_hidden_catalog_are_404(monkeypatch):
    status, detail = _status_and_detail(
        queries.get_table_columns("finance", "ledger", "entries", user=ALICE))
    assert status == 404 and "Known catalogs: iceberg." in detail

    async def must_not_run(*a, **k):
        raise AssertionError("the preview must not run")
    monkeypatch.setattr(catalog, "execute_query", must_not_run)
    status, _ = _status_and_detail(catalog.preview_table(
        "ledger", "entries", catalog="finance", limit=10, db=None, user=ALICE))
    assert status == 404


def test_detail_of_a_granted_catalog_answers():
    res = _run(catalog.get_table_details("ledger", "entries", catalog="finance", user=BOB))
    assert res.catalog == "finance"
    cols = _run(queries.get_table_columns("finance", "ledger", "entries", user=BOB))
    assert cols[0].name == "finance_col"


def test_grants_that_cannot_be_read_hide_every_catalog(monkeypatch):
    catalog_access.reset()

    async def _broken():
        raise ConnectionError("database is gone")
    monkeypatch.setattr(catalog_access, "_pool", _broken)
    assert _catalogs_in_tables(ALICE) == set()
    assert _status_and_detail(
        catalog.get_table_details("sales", "orders", user=ALICE))[0] == 404
    assert _catalogs_in_tables(ADMIN) == {"iceberg", "finance"}


def test_a_database_before_the_grants_table_lists_everything(monkeypatch):
    catalog_access.reset()

    class UndefinedTableError(Exception):
        sqlstate = "42P01"

    async def _missing():
        raise UndefinedTableError('relation "catalog_grants" does not exist')
    monkeypatch.setattr(catalog_access, "_pool", _missing)
    assert _catalogs_in_tables(ALICE) == {"iceberg", "finance"}


# ── the relationship graph ───────────────────────────────────────────────────

def test_the_relationship_graph_drops_hidden_catalogs(monkeypatch):
    class _Q:
        def filter(self, *a, **k): return self
        def order_by(self, *a, **k): return self
        def limit(self, n): return self
        def all(self):
            return [("SELECT * FROM sales.orders o JOIN finance.ledger.entries e "
                     "ON o.id = e.order_id",),
                    ("SELECT * FROM sales.orders o JOIN sales.customers c "
                     "ON o.cust_id = c.id",)]

    class _DB:
        def query(self, *cols):
            return _Q()

    monkeypatch.setattr(queries, "_catalog_schema_for_graph", lambda: {})
    g = _run(queries.catalog_relationships(days=30, db=_DB(), user=ALICE))
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"iceberg.sales.orders", "iceberg.sales.customers"}
    assert all(not e["source"].startswith("finance.") and not e["target"].startswith("finance.")
               for e in g["edges"])
    g = _run(queries.catalog_relationships(days=30, db=_DB(), user=BOB))
    assert "finance.ledger.entries" in {n["id"] for n in g["nodes"]}


# ── /api/catalogs ────────────────────────────────────────────────────────────

def test_the_catalog_list_shows_a_non_admin_only_what_it_may_use(monkeypatch):
    async def _pool():
        return object()

    async def _load(pool, force=False, timeout=5.0):
        return reg.entries()
    monkeypatch.setattr(catalog_admin, "_pool", _pool)
    monkeypatch.setattr(catalog_admin.catalog_registry, "load", _load)
    names = lambda user: [c["name"] for c in _run(catalog_admin.list_catalogs(user=user))["catalogs"]]
    assert names(ALICE) == ["iceberg"]
    assert names(BOB) == ["iceberg", "finance"]
    assert names(ADMIN) == ["iceberg", "finance"]
    assert names(ADMIN_KEY) == ["iceberg"]
