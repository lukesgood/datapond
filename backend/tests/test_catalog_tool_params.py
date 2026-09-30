"""`catalog` on the chat/MCP read tools and on the gateway OpenAPI (multi-catalog P3).

Every read tool that names a table or a namespace takes an optional `catalog`. A
catalog the caller may not use answers exactly as one that does not exist, and a
tool that lists across catalogs leaves hidden ones out.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import catalog_access
from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry
from app.chat import executors
from app.chat.analysis import catalog as chat_catalog

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "auditor"}


def _run(coro):
    return asyncio.run(coro)


class _R:
    def __init__(self, tree):
        self.tree = tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]


READERS = {"iceberg": _R({"sales": ["orders"]}),
           "finance": _R({"ledger": ["entries", "orders_fx"]})}


@pytest.fixture(autouse=True)
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    catalog_access.set_grants({"finance": [("user", BOB["id"])]})
    monkeypatch.setattr(chat_catalog, "get_catalog_reader",
                        lambda name=None: READERS[reg.resolve(name).name])
    yield
    reg.reset()
    catalog_access.reset()


def _unknown_text(fn, params, user):
    with pytest.raises(reg.UnknownCatalog) as e:
        _run(fn(params, user))
    return str(e.value)


# ── find_tables ──────────────────────────────────────────────────────────────

def test_find_tables_can_be_limited_to_one_catalog():
    find = executors.EXECUTORS["catalog.find_tables"]
    out = _run(find({"query": "orders", "catalog": "finance"}, BOB))
    assert out["tables"] == ["finance.ledger.orders_fx"]
    out = _run(find({"query": "orders", "catalog": "iceberg"}, BOB))
    assert out["tables"] == ["sales.orders"]


def test_find_tables_in_a_hidden_catalog_is_an_unknown_catalog():
    find = executors.EXECUTORS["catalog.find_tables"]
    hidden = _unknown_text(find, {"query": "orders", "catalog": "finance"}, ALICE)
    unknown = _unknown_text(find, {"query": "orders", "catalog": "nope"}, ALICE)
    assert hidden == unknown.replace("nope", "finance")


# ── governance reads ─────────────────────────────────────────────────────────

def _policies(monkeypatch):
    from app.rls import loader
    pols = [SimpleNamespace(id="p1", catalog="iceberg", schema="sales", table="orders",
                            filter_expression="region = 'kr'", role_map={"viewer": False}),
            SimpleNamespace(id="p2", catalog="finance", schema="ledger", table="entries",
                            filter_expression="1=1", role_map={"auditor": False})]
    masks = [SimpleNamespace(id="m1", catalog="finance", schema="ledger", table="entries",
                             column="memo", masking_type="redact")]

    async def _p():
        return pols

    async def _m():
        return masks
    monkeypatch.setattr(loader, "load_policies", _p)
    monkeypatch.setattr(loader, "load_masks", _m)


def test_explain_policy_leaves_out_hidden_catalogs(monkeypatch):
    _policies(monkeypatch)
    explain = executors.EXECUTORS["governance.explain_policy"]
    out = _run(explain({}, ALICE))
    assert [p["id"] for p in out["row_filters"]] == ["p1"] and out["column_masks"] == []
    out = _run(explain({}, BOB))
    assert [p["id"] for p in out["row_filters"]] == ["p1", "p2"]


def test_explain_policy_for_a_hidden_catalog_is_an_unknown_catalog(monkeypatch):
    _policies(monkeypatch)
    explain = executors.EXECUTORS["governance.explain_policy"]
    hidden = _unknown_text(explain, {"catalog": "finance"}, ALICE)
    unknown = _unknown_text(explain, {"catalog": "nope"}, ALICE)
    assert hidden == unknown.replace("nope", "finance")
    out = _run(explain({"catalog": "finance"}, BOB))
    assert [p["id"] for p in out["row_filters"]] == ["p2"]


def _coverage(monkeypatch):
    async def _fake(user=None):
        return {"total": 3,
                "covered": ["finance.ledger.entries", "iceberg.sales.orders"],
                "covered_count": 2,
                "uncovered": ["finance.ledger.orders_fx"], "uncovered_count": 1,
                "orphaned_policies": [],
                "would_block_under_default_deny": ["finance.ledger.orders_fx"],
                "rls_enabled": True}
    monkeypatch.setattr("app.api.governance.rls_coverage", _fake)


def test_policy_coverage_takes_a_catalog_and_hides_hidden_ones(monkeypatch):
    _coverage(monkeypatch)
    cov = executors.EXECUTORS["governance.policy_coverage"]
    out = _run(cov({}, ALICE))["coverage"]
    assert out["covered"] == ["iceberg.sales.orders"] and out["uncovered"] == []
    assert (out["total"], out["covered_count"], out["uncovered_count"]) == (1, 1, 0)
    out = _run(cov({"catalog": "finance"}, BOB))["coverage"]
    assert out["covered"] == ["finance.ledger.entries"]
    assert out["uncovered"] == ["finance.ledger.orders_fx"] and out["total"] == 2
    assert out["rls_enabled"] is True
    hidden = _unknown_text(cov, {"catalog": "finance"}, ALICE)
    assert "finance" in hidden and "Known catalogs: iceberg." in hidden


# ── generate_sql ─────────────────────────────────────────────────────────────

SCHEMA = ("Available tables (catalog: iceberg):\n  sales.orders(id bigint)\n"
          "Available tables (catalog: finance):\n  ledger.entries(id bigint)")


def test_the_schema_offered_can_be_one_catalogs():
    from app.api.ai_sql import _schema_for_catalog
    fin = reg.resolve("finance")
    assert "ledger.entries" in _schema_for_catalog(SCHEMA, fin, "iceberg")
    assert "sales.orders" not in _schema_for_catalog(SCHEMA, fin, "iceberg")
    dflt = reg.resolve(None)
    out = _schema_for_catalog(SCHEMA, dflt, "iceberg")
    assert "sales.orders" in out and "ledger" not in out


def test_generate_sql_in_a_hidden_catalog_is_a_404_unknown_catalog(monkeypatch):
    from app.api import ai_sql
    monkeypatch.setattr(ai_sql, "_get_schema_context", lambda: SCHEMA)
    with pytest.raises(HTTPException) as hidden:
        _run(ai_sql._generate_sql_impl(ai_sql.AskRequest(question="x", catalog="finance"),
                                       ALICE))
    with pytest.raises(HTTPException) as unknown:
        _run(ai_sql._generate_sql_impl(ai_sql.AskRequest(question="x", catalog="nope"),
                                       ALICE))
    assert hidden.value.status_code == unknown.value.status_code == 404
    assert hidden.value.detail == unknown.value.detail.replace("nope", "finance")


def test_the_generate_sql_tool_passes_the_catalog(monkeypatch):
    seen = {}

    async def _fake(req, user=None):
        seen["catalog"] = req.catalog
        return SimpleNamespace(sql="SELECT 1", explanation="", validated=True,
                               needs_input=False)
    monkeypatch.setattr("app.api.ai_sql.generate_sql", _fake)
    _run(executors.EXECUTORS["query.generate_sql"]({"question": "q", "catalog": "finance"},
                                                    BOB))
    assert seen["catalog"] == "finance"


# ── what the tools advertise ─────────────────────────────────────────────────

@pytest.mark.parametrize("tool", [
    "catalog_describe_table", "catalog_find_tables", "catalog_explain_relationships",
    "governance_explain_policy", "governance_policy_coverage", "query_generate_sql",
])
def test_mcp_descriptors_offer_an_optional_catalog(tool):
    from app.chat.actions import REGISTRY
    from app.mcp import tools
    perms = {a.permission for a in REGISTRY.values()}
    caps = {a.capability: True for a in REGISTRY.values() if a.capability}
    d = {x["name"]: x for x in tools.descriptors(perms, caps)}[tool]
    prop = d["inputSchema"]["properties"]["catalog"]
    assert prop.get("description")
    assert "catalog" not in d["inputSchema"]["required"]


def test_the_gateway_openapi_offers_catalog_on_generate_sql():
    import main
    from app.tool_openapi import build_tool_openapi
    spec = build_tool_openapi(main.app, "https://dp.example.com",
                              {"ai:generate", "query:run", "knowledge:read"})
    schema = spec["paths"]["/api/ai/sql"]["post"]["requestBody"]["content"][
        "application/json"]["schema"]
    prop = schema["properties"]["catalog"]
    assert prop["type"] == "string" and prop.get("description")
    assert "anyOf" not in prop and "catalog" not in schema.get("required", [])
