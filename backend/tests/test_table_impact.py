"""Data Map step 4: what depends on a table (app/table_impact.py + GET /catalog/impact)."""
import asyncio

import pytest

from app import table_impact as ti


def canon(c):
    return {"awsdatacatalog": "iceberg"}.get(c.lower(), c)


def test_table_id_folds_alias_and_case():
    assert ti.table_id("AwsDataCatalog.Default.Orders", canon) == "iceberg.default.orders"
    assert ti.table_id('"iceberg"."default"."orders"', canon) == "iceberg.default.orders"
    assert ti.table_id("default.orders", canon) is None
    assert ti.table_id("", canon) is None


METRICS = [{"name": "revenue", "label": "Revenue", "version": 3, "base_table": "iceberg.default.orders"},
           {"name": "customer_count", "label": "Customers", "version": 1, "base_table": "iceberg.default.customers"}]
BINDINGS = [
    {"concept": "주문", "catalog": "AwsDataCatalog", "namespace": "default", "table": "orders", "column": "id", "role": "key"},
    {"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "orders", "column": "customer_id", "role": "key"},
    {"concept": "취소 주문", "catalog": "iceberg", "namespace": "default", "table": "orders", "column": "status",
     "role": "filter", "filter_sql": "status = 'cancelled'"},
    {"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "customers", "column": "id", "role": "key"},
]
DASHBOARDS = [{"id": "d1", "name": "Weekly orders", "tables": ["iceberg.default.orders"]},
              {"id": "d2", "name": "Joined", "tables": ["AwsDataCatalog.default.orders", "iceberg.default.customers"]},
              {"id": "d3", "name": "Elsewhere", "tables": ["iceberg.default.invoices"]}]
CALLS = [{"table": "iceberg.default.orders", "actor": "kim", "kind": "human", "n": 20},
         {"table": "AwsDataCatalog.default.orders", "actor": "kim", "kind": "human", "n": 5},
         {"table": "iceberg.default.orders", "actor": "agent-a", "kind": "service", "n": 41},
         {"table": "iceberg.default.orders", "actor": "lee", "kind": "human", "n": 2},
         {"table": "iceberg.default.invoices", "actor": "lee", "kind": "human", "n": 9}]


def run(show=True, tables=("iceberg.default.orders",)):
    return ti.impact(tables, metrics=METRICS, bindings=BINDINGS, dashboards=DASHBOARDS,
                     calls=CALLS, canonical=canon, show_callers=show)


def test_impact_gathers_all_four_kinds_across_aliases():
    o = run()["iceberg.default.orders"]
    assert [m["name"] for m in o["metrics"]] == ["revenue"]
    assert [(c["concept"], c["column"]) for c in o["concepts"]] == [
        ("고객", "customer_id"), ("주문", "id"), ("취소 주문", "status")]
    assert [d["id"] for d in o["dashboards"]] == ["d2", "d1"]          # by name: Joined, Weekly
    q = o["queries"]
    assert (q["calls"], q["people"], q["services"], q["service_calls"]) == (68, 2, 1, 41)
    assert q["callers"][0] == {"name": "agent-a", "kind": "service", "calls": 41}
    assert q["callers"][1] == {"name": "kim", "kind": "human", "calls": 25}


def test_callers_named_only_for_governance_readers():
    q = run(show=False)["iceberg.default.orders"]["queries"]
    assert q["calls"] == 68 and q["callers"] == []


def test_several_tables_and_an_unknown_one():
    out = run(tables=["iceberg.default.orders", "AwsDataCatalog.default.customers", "iceberg.default.none", "bad"])
    assert set(out) == {"iceberg.default.orders", "iceberg.default.customers", "iceberg.default.none"}
    assert [m["name"] for m in out["iceberg.default.customers"]["metrics"]] == ["customer_count"]
    assert out["iceberg.default.none"]["queries"]["calls"] == 0


# --- the route ------------------------------------------------------------------

class _Conn:
    def __init__(self, sent):
        self.sent = sent

    async def fetch(self, sql, *args):
        self.sent.append((sql, args))
        if "FROM dashboards" in sql:
            return [{"id": "d1", "name": "Weekly orders", "query_text": "SELECT * FROM iceberg.default.orders"}]
        return [{"table": "iceberg.default.orders", "actor": "kim", "kind": "human", "n": 3}]


class _Pool:
    def __init__(self, sent):
        self.sent = sent

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self):
                return _Conn(pool.sent)

            async def __aexit__(self, *a):
                return False
        return Ctx()


@pytest.fixture
def route(monkeypatch):
    import app.api.catalog as catalog
    import app.api.connectors as connectors
    import app.api.ontology as ontology
    from app.semantic import concept_store, context

    class Access:
        def allows_sql_catalog(self, c):
            return c == "iceberg"

    sent = []

    async def for_caller(user):
        return Access()

    async def pool():
        return _Pool(sent)

    async def metrics(user):
        return METRICS

    async def bindings(p, statuses):
        return BINDINGS

    monkeypatch.setattr(catalog.catalog_access, "for_caller", for_caller)
    monkeypatch.setattr(catalog.catalog_registry, "canonical_catalog", canon)
    monkeypatch.setattr(connectors, "get_db_pool", pool)
    monkeypatch.setattr(context, "for_caller", metrics)
    monkeypatch.setattr(ontology, "ontology_enabled", lambda: True)
    monkeypatch.setattr(concept_store, "list_bindings", bindings)
    return catalog, sent


def test_route_limits_to_allowed_catalogs_and_hides_names_from_viewers(route):
    catalog, sent = route
    viewer = {"id": "00000000-0000-0000-0000-000000000001", "role": "viewer"}
    out = asyncio.run(catalog.table_impact(table=["iceberg.default.orders", "finance.sales.invoices"], user=viewer))
    assert list(out["tables"]) == ["iceberg.default.orders"]
    o = out["tables"]["iceberg.default.orders"]
    assert o["dashboards"] == [{"id": "d1", "name": "Weekly orders"}]
    assert o["queries"]["calls"] == 3 and o["queries"]["callers"] == []
    dash_sql, dash_args = next(s for s in sent if "FROM dashboards" in s[0])
    assert "is_public" in dash_sql and dash_args == (viewer["id"],)


def test_route_names_callers_for_admin_and_refuses_too_many(route):
    catalog, _ = route
    admin = {"id": "00000000-0000-0000-0000-000000000002", "role": "admin"}
    out = asyncio.run(catalog.table_impact(table=["iceberg.default.orders"], user=admin))
    assert out["tables"]["iceberg.default.orders"]["queries"]["callers"][0]["name"] == "kim"
    with pytest.raises(catalog.HTTPException) as e:
        asyncio.run(catalog.table_impact(table=[f"iceberg.default.t{i}" for i in range(13)], user=admin))
    assert e.value.status_code == 400
    assert asyncio.run(catalog.table_impact(table=[], user=admin)) == {"tables": {}, "days": 30}
