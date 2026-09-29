"""The assistant's catalog and policy reads take a catalog and report it.

describe_table and find_tables read the default catalog only; with a second catalog
the assistant described the default's table under the other's name, and could never
find a table that lived only in the second.
"""
import asyncio
from types import SimpleNamespace

import pytest

from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry
from app.chat import executors
from app.chat.analysis import catalog as chat_catalog

USER = {"id": "u-1", "username": "ada", "role": "admin"}


def _run(coro):
    return asyncio.run(coro)


class _R:
    def __init__(self, name, tree):
        self.name, self.tree = name, tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]

    def get_columns(self, ns, t):
        return [{"name": f"{self.name}_id", "type": "bigint"}]


READERS = {"iceberg": _R("iceberg", {"sales": ["orders"]}),
           "finance": _R("finance", {"ledger": ["entries", "orders_fx"]})}


@pytest.fixture(autouse=True)
def two_catalogs(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    reader = lambda name=None: READERS[reg.resolve(name).name]  # noqa: E731
    monkeypatch.setattr(chat_catalog, "get_catalog_reader", reader)
    import app.api.catalog_backend as cb
    monkeypatch.setattr(cb, "get_catalog_reader", reader)
    yield
    reg.reset()


def test_describe_table_reads_the_catalog_it_names():
    out = _run(executors.EXECUTORS["catalog.describe_table"](
        {"catalog": "finance", "namespace": "ledger", "table": "entries"}, USER))
    assert out["catalog"] == "finance"
    assert out["table"] == "finance.ledger.entries"
    assert out["columns"][0]["name"] == "finance_id"


def test_describe_table_defaults_to_the_default_catalog():
    out = _run(executors.EXECUTORS["catalog.describe_table"](
        {"namespace": "sales", "table": "orders"}, USER))
    assert out["catalog"] == "iceberg"
    assert out["table"] == "sales.orders"


def test_describe_table_refuses_an_unknown_catalog():
    with pytest.raises(ValueError):
        _run(executors.EXECUTORS["catalog.describe_table"](
            {"catalog": "nope", "namespace": "sales", "table": "orders"}, USER))


def test_find_tables_searches_every_catalog_and_names_non_default_ones():
    out = _run(executors.EXECUTORS["catalog.find_tables"]({"query": "orders"}, USER))
    assert set(out["tables"]) == {"sales.orders", "finance.ledger.orders_fx"}


def test_the_catalog_is_part_of_the_action_schemas():
    from app.chat.analysis.catalog import RelationshipQuery, TableRef
    from app.chat.analysis.governance import PolicyQuery
    for model in (TableRef, RelationshipQuery, PolicyQuery):
        assert "catalog" in model.model_json_schema()["properties"]
        assert "catalog" not in model.model_json_schema().get("required", [])


def test_explain_relationships_filters_by_a_table_in_its_catalog(monkeypatch):
    import app.api.queries as q
    schema = {
        "iceberg.sales.orders": [{"name": "account_id", "type": "bigint"}],
        "finance.ledger.accounts": [{"name": "id", "type": "bigint"}],
    }
    monkeypatch.setattr(q, "_catalog_schema_for_graph", lambda: schema)
    out = _run(executors.EXECUTORS["catalog.explain_relationships"](
        {"table": "sales.orders"}, USER))
    assert len(out["relationships"]) == 1
    none = _run(executors.EXECUTORS["catalog.explain_relationships"](
        {"table": "sales.orders", "catalog": "finance"}, USER))
    assert none["relationships"] == []


def test_explain_policy_reports_and_filters_by_catalog(monkeypatch):
    from app.rls import loader

    def pol(i, cat):
        return SimpleNamespace(id=i, catalog=cat, schema="sales", table="orders",
                               filter_expression="1=1", role_map={})

    async def policies():
        return [pol("a", "iceberg"), pol("b", "finance")]

    async def masks():
        return []

    monkeypatch.setattr(loader, "load_policies", policies)
    monkeypatch.setattr(loader, "load_masks", masks)
    run = executors.EXECUTORS["governance.explain_policy"]
    everything = _run(run({}, USER))
    assert {(p["catalog"], p["id"]) for p in everything["row_filters"]} == {
        ("iceberg", "a"), ("finance", "b")}
    only = _run(run({"table": "sales.orders", "catalog": "finance"}, USER))
    assert [p["id"] for p in only["row_filters"]] == ["b"]
