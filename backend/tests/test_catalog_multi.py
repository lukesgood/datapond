"""The catalog routes honour the catalog they are asked about, and say which one answered.

`/catalog/columns`, `/catalog/tables/{ns}/{t}` and `/preview` accepted `catalog` and
ignored it; `/catalog/tables` and `/catalog/schemas` labelled every table with the
default. With a second catalog each of those returned another catalog's data under a
name that looked right.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.catalog as catalog
import app.api.queries as queries
from app import catalog_registry as reg
from app.api.queries import QueryResult
from app.catalog_registry import CatalogEntry


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

    def reader(name=None):
        return READERS[reg.resolve(name).name]

    monkeypatch.setattr(catalog, "get_catalog_reader", reader)
    import app.api.catalog_backend as cb
    monkeypatch.setattr(cb, "get_catalog_reader", reader)
    # No Valkey in unit tests; refuse fast instead of resolving a cluster name.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    yield
    reg.reset()


def test_tables_come_from_every_catalog_labelled_with_their_own():
    res = _run(catalog.list_all_tables())
    got = {(t.catalog, t.namespace, t.name) for t in res.tables}
    assert got == {("iceberg", "sales", "orders"), ("finance", "ledger", "entries")}


def test_namespaces_carry_their_catalog():
    res = _run(catalog.list_all_namespaces())
    assert {(n.catalog, n.name) for n in res.namespaces} == {
        ("iceberg", "sales"), ("finance", "ledger")}


def test_table_details_read_the_catalog_asked_for():
    res = _run(catalog.get_table_details("ledger", "entries", catalog="finance"))
    assert res.columns[0].name == "finance_col"
    assert res.catalog == "finance"
    assert res.location == "s3://finance/ledger/entries"


def test_table_details_default_to_the_default_catalog():
    res = _run(catalog.get_table_details("sales", "orders"))
    assert res.columns[0].name == "iceberg_col"
    assert res.catalog == "iceberg"


def test_an_unknown_catalog_is_a_400_not_a_default():
    with pytest.raises(HTTPException) as exc:
        _run(catalog.get_table_details("sales", "orders", catalog="nope"))
    assert exc.value.status_code == 400


def _preview(monkeypatch, **kw):
    seen = {}

    async def governed(request, db, user):
        seen["sql"] = request.query
        return QueryResult(columns=[], rows=[], execution_time_ms=0, row_count=0)

    monkeypatch.setattr(catalog, "execute_query", governed)
    _run(catalog.preview_table(limit=10, db=None, user={"id": "u"}, **kw))
    return seen["sql"]


def test_a_preview_of_another_catalog_names_it(monkeypatch):
    sql = _preview(monkeypatch, namespace="ledger", table="entries", catalog="finance")
    assert sql == "SELECT * FROM finance.ledger.entries LIMIT 10"


def test_a_preview_of_the_default_catalog_stays_two_part(monkeypatch):
    sql = _preview(monkeypatch, namespace="sales", table="orders", catalog="iceberg")
    assert sql == "SELECT * FROM sales.orders LIMIT 10"


def test_a_preview_of_an_unknown_catalog_is_refused(monkeypatch):
    async def governed(*a, **k):
        raise AssertionError("must not run")
    monkeypatch.setattr(catalog, "execute_query", governed)
    with pytest.raises(HTTPException) as exc:
        _run(catalog.preview_table("sales", "orders", catalog="nope", limit=10,
                                   db=None, user={"id": "u"}))
    assert exc.value.status_code == 400


def test_the_schema_tree_has_one_node_per_catalog():
    tree = _run(queries.get_catalog_schemas())
    names = [c.name for c in tree.catalogs]
    assert names == ["iceberg", "finance"]
    fin = tree.catalogs[1]
    assert fin.schemas[0].name == "ledger" and fin.schemas[0].tables[0].name == "entries"


def test_columns_are_read_from_their_catalog():
    cols = _run(queries.get_table_columns("finance", "ledger", "entries"))
    assert cols[0].name == "finance_col"


def test_columns_of_an_unknown_catalog_are_refused():
    with pytest.raises(HTTPException) as exc:
        _run(queries.get_table_columns("nope", "ledger", "entries"))
    assert exc.value.status_code == 400
