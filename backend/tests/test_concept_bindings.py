"""Concept bindings (app/semantic/concepts.py, app/api/concepts.py, migration 0031).

A concept ("고객") gets tied to columns: keys, attributes, or a segment filter. Suggestions
come from column names and from joins; an administrator approves, a governance:write
author proposes, keys and tokens never write, and readers see only catalogs they may use."""
import asyncio
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import catalog_access
from app import catalog_registry as reg
from app.api import concepts as routes
from app.catalog_registry import CatalogEntry
from app.semantic import concepts

CUSTOMER = {"name": "고객", "terms": ["customer", "회원"]}
ORDER = {"name": "주문", "terms": ["order"]}
SCHEMA = {
    "iceberg.default.customers": [{"name": "id"}, {"name": "tier"}, {"name": "name"}],
    "iceberg.default.orders": [{"name": "id"}, {"name": "customer_id"}, {"name": "amount"}],
    "iceberg.default.payments": [{"name": "id"}, {"name": "buyer"}, {"name": "order_id"}],
}


def bound(concept, table, column, role="key", status="approved", catalog="iceberg"):
    ns, t = table.split(".")
    return {"concept": concept, "catalog": catalog, "namespace": ns, "table": t,
            "column": column, "role": role, "status": status}


# ── suggestions ───────────────────────────────────────────────────────────────

def test_names_suggest_keys_and_a_tables_own_id():
    found = {(p["concept"], p["table"], p["column"]): p for p in concepts.propose([CUSTOMER, ORDER], SCHEMA, [], [])}
    assert found[("고객", "customers", "id")]["role"] == "key"
    assert found[("고객", "orders", "customer_id")]["source"] == "naming"
    assert found[("주문", "payments", "order_id")]["role"] == "key"
    assert found[("주문", "orders", "id")]
    assert ("고객", "customers", "tier") not in found and ("고객", "payments", "buyer") not in found


def test_any_stored_binding_blocks_the_same_suggestion_rejected_included():
    stored = [bound("고객", "default.customers", "id"), bound("고객", "default.orders", "customer_id", status="rejected")]
    keys = {(p["table"], p["column"]) for p in concepts.propose([CUSTOMER], SCHEMA, stored, []) if p["concept"] == "고객"}
    assert ("customers", "id") not in keys and ("orders", "customer_id") not in keys


def test_a_join_carries_an_approved_key_to_its_other_side():
    edges = [{"source": "iceberg.default.payments", "target": "iceberg.default.customers", "evidence": "observed",
              "count": 41, "joins": [{"left_column": "buyer", "right_column": "id", "count": 41}]}]
    found = concepts.propose([CUSTOMER], SCHEMA, [bound("고객", "default.customers", "id")], edges)
    p = next(p for p in found if p["column"] == "buyer")
    assert (p["source"], p["role"]) == ("history", "key") and "41 queries" in p["evidence"]


def test_a_naming_guess_edge_carries_nothing_and_proposed_keys_do_not_spread():
    edges = [{"source": "iceberg.default.payments", "target": "iceberg.default.customers", "evidence": "candidate",
              "joins": [{"left_column": "buyer", "right_column": "id"}]}]
    assert not [p for p in concepts.propose([CUSTOMER], SCHEMA, [bound("고객", "default.customers", "id")], edges)
                if p["column"] == "buyer"]
    observed = [dict(edges[0], evidence="observed")]
    assert not [p for p in concepts.propose([CUSTOMER], SCHEMA, [bound("고객", "default.customers", "id", status="proposed")], observed)
                if p["column"] == "buyer"]


def test_approved_joins_become_edges_under_the_engine_name():
    e = concepts.approved_join_edges([{"catalog": "AwsDataCatalog", "from_table": "default.payments",
                                       "to_table": "default.customers", "on_columns": [["buyer", "id"]]}],
                                     lambda n: "iceberg")
    assert e == [{"source": "iceberg.default.payments", "target": "iceberg.default.customers",
                  "evidence": "approved", "joins": [{"left_column": "buyer", "right_column": "id"}]}]


def test_plural_folding():
    assert [concepts.singular(x) for x in ("customers", "categories", "addresses", "status", "class",
                                           "warehouses", "boxes", "branches", "courses")] == \
        ["customer", "category", "address", "statu", "class", "warehouse", "box", "branch", "course"]


# ── migration ─────────────────────────────────────────────────────────────────

def test_the_migration_chains_and_keeps_one_row_per_binding():
    py = Path(__file__).resolve().parents[1] / "migrations/versions/0031_concept_bindings.py"
    spec = importlib.util.spec_from_file_location("m0031", py)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.down_revision == "0030_connector_pause_audit" and len(m.revision) <= 32
    sql = py.with_suffix(".sql").read_text()
    assert "REFERENCES public.ontology_concepts(id) ON DELETE CASCADE" in sql
    assert re.search(r"UNIQUE INDEX IF NOT EXISTS concept_bindings_one", sql)
    assert "CHECK ((role = 'filter') = (filter_sql IS NOT NULL))" in sql


# ── routes ────────────────────────────────────────────────────────────────────

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
AUTHOR = {"id": "00000000-0000-0000-0000-000000000002", "username": "kim", "role": "data_engineer",
          "permissions": ["catalog:read", "governance:write"]}
READER = {"id": "00000000-0000-0000-0000-000000000003", "username": "lee", "role": "business_analyst",
          "permissions": ["catalog:read"]}
COLUMNS = {"default.customers": ["id", "tier", "name"], "default.orders": ["id", "customer_id", "amount"]}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("FEATURE_ONTOLOGY", "true")
    reg.set_entries([CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True),
                     CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake")])
    db = {"rows": [], "audit": []}

    async def _pool():
        return object()
    monkeypatch.setattr(routes, "_pool", _pool)

    async def concept_id(pool, name):
        return {"고객": "c1", "VIP 고객": "c2"}.get(name)
    async def upsert(pool, **kw):
        for r in db["rows"]:
            if all(r[k] == kw[k] for k in ("concept_id", "catalog", "namespace", "table", "column", "role", "filter_sql")):
                r["status"] = kw["status"]
                return r["id"]
        db["rows"].append(dict(kw, id=len(db["rows"]) + 1))
        return len(db["rows"])
    async def get_binding(pool, bid):
        r = next((r for r in db["rows"] if r["id"] == bid), None)
        return r and dict(r, concept="고객")
    async def decide(pool, bid, *, from_status, to_status, actor_id, actor_name):
        r = next((r for r in db["rows"] if r["id"] == bid), None)
        if not r or r["status"] != from_status:
            return False
        r["status"] = to_status
        return True
    async def list_bindings(pool, statuses=None):
        rows = [dict(r, concept="고객") for r in db["rows"]]
        return [r for r in rows if not statuses or r["status"] in statuses]
    async def load_concepts(pool):
        return [CUSTOMER]
    for name, fn in (("concept_id", concept_id), ("upsert_binding", upsert), ("get_binding", get_binding),
                     ("decide", decide), ("list_bindings", list_bindings)):
        monkeypatch.setattr(routes.concept_store, name, fn)
    monkeypatch.setattr(routes, "load_concepts", load_concepts)
    import app.api.semantic as semantic
    monkeypatch.setattr(semantic, "_columns", lambda entry, table: COLUMNS.get(table))

    async def record(**kw):
        db["audit"].append(kw["reason"])
    monkeypatch.setattr(routes.security_audit, "record", record)
    yield db
    reg.reset()


def _create(user, **body):
    base = {"concept": "고객", "catalog": "iceberg", "table": "default.customers", "column": "id", "role": "key"}
    return asyncio.run(routes.create_binding(routes.BindingBody(**{**base, **body}), user=user))


def test_an_administrators_binding_is_approved_and_audited(world):
    out = _create(ADMIN)
    assert out["status"] == "approved"
    assert world["rows"][0]["catalog"] == "iceberg" and world["audit"]


def test_the_registry_name_is_stored_as_the_engine_name(world):
    _create(ADMIN, catalog="AwsDataCatalog")
    assert world["rows"][0]["catalog"] == "iceberg"


def test_an_author_proposes_and_a_reader_cannot(world):
    assert _create(AUTHOR, status="approved")["status"] == "proposed"
    assert world["audit"] == []
    with pytest.raises(HTTPException) as e:
        _create(READER)
    assert e.value.status_code == 403


def test_a_key_never_writes(world):
    key = dict(ADMIN, auth_method="service", permissions=["catalog:read", "governance:write"])
    with pytest.raises(HTTPException) as e:
        _create(key)
    assert e.value.status_code == 403


def test_unknown_column_and_concept_are_refused(world):
    with pytest.raises(HTTPException) as e:
        _create(ADMIN, column="nope")
    assert e.value.detail["field"] == "column"
    with pytest.raises(HTTPException) as e:
        _create(ADMIN, concept="없는개념")
    assert e.value.detail["field"] == "concept"


def test_a_segment_needs_a_valid_condition_on_its_table(world):
    with pytest.raises(HTTPException) as e:
        _create(ADMIN, concept="VIP 고객", column="tier", role="filter")
    assert e.value.detail["field"] == "filter_sql"
    with pytest.raises(HTTPException) as e:
        _create(ADMIN, concept="VIP 고객", column="tier", role="filter", filter_sql="(SELECT 1) = 1")
    assert e.value.detail["field"] == "filter_sql"
    with pytest.raises(HTTPException) as e:
        _create(ADMIN, concept="VIP 고객", column="tier", role="filter", filter_sql="region = 'KR'")
    assert e.value.detail["field"] == "filter_sql"
    assert _create(ADMIN, concept="VIP 고객", column="tier", role="filter", filter_sql="tier = 'VIP'")["status"] == "approved"
    with pytest.raises(HTTPException):
        _create(ADMIN, column="id", role="key", filter_sql="tier = 'VIP'")


def test_a_rejected_suggestion_is_stored_and_can_be_approved_later(world):
    assert _create(ADMIN, status="rejected", table="default.orders", column="customer_id")["status"] == "rejected"
    assert _create(ADMIN, table="default.orders", column="customer_id")["status"] == "approved"
    assert len(world["rows"]) == 1


def test_approve_reject_and_retire_move_only_from_the_right_state(world):
    bid = _create(AUTHOR)["id"]
    assert asyncio.run(routes.approve_binding(bid, admin=ADMIN))["status"] == "approved"
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.reject_binding(bid, admin=ADMIN))
    assert e.value.status_code == 409
    assert asyncio.run(routes.retire_binding(bid, admin=ADMIN))["status"] == "retired"
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.approve_binding(99, admin=ADMIN))
    assert e.value.status_code == 404


def test_readers_see_only_catalogs_they_may_use(world, monkeypatch):
    _create(ADMIN)
    world["rows"].append(dict(world["rows"][0], id=2, catalog="polaris_lake"))

    async def access(user):
        return catalog_access.CatalogAccess(grants={"polaris_lake": frozenset({("role", "admin")})},
                                            user_id=user["id"], role=user["role"])
    monkeypatch.setattr(routes.catalog_access, "for_caller", access)
    out = asyncio.run(routes.list_concepts_with_bindings(user=READER))
    assert [b["catalog"] for b in out["bindings"]] == ["iceberg"]
    assert out["viewer"] == {"can_approve": False, "can_propose": False}


def test_off_without_the_ontology_capability(world, monkeypatch):
    monkeypatch.setenv("FEATURE_ONTOLOGY", "")
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.list_concepts_with_bindings(user=ADMIN))
    assert e.value.status_code == 404


# ── step 2: context for /ai/sql, read actions, column chips ───────────────────

from app.semantic import concept_context as ctx

VISIBLE = [
    {"name": "고객", "terms": ["customer", "회원"], "parent": None, "pii": True, "bindings": [
        {"catalog": "iceberg", "namespace": "default", "table": "customers", "column": "id", "role": "key", "filter_sql": None},
        {"catalog": "iceberg", "namespace": "default", "table": "orders", "column": "customer_id", "role": "key", "filter_sql": None}]},
    {"name": "플래티넘 고객", "terms": [], "parent": "고객", "pii": False, "bindings": [
        {"catalog": "iceberg", "namespace": "default", "table": "customers", "column": "tier", "role": "filter", "filter_sql": "tier = 'platinum'"}]},
    {"name": "주문", "terms": ["order"], "parent": None, "pii": False, "bindings": [
        {"catalog": "iceberg", "namespace": "default", "table": "orders", "column": "id", "role": "key", "filter_sql": None}]},
    {"name": "환불", "terms": ["refund"], "parent": None, "pii": False, "bindings": []},
]


def test_the_question_picks_its_concepts_longest_first_particles_ignored():
    names = [c["name"] for c in ctx.matched(VISIBLE, "플래티넘 고객의 지난달 주문은 몇 건?")]
    assert names == ["플래티넘 고객", "고객", "주문"]
    assert ctx.matched(VISIBLE, "환불 건수") == []          # no approved binding, nothing to give
    assert ctx.matched(VISIBLE, "전체 매출") == []


def test_the_prompt_block_names_keys_and_segments_and_reports_what_it_gave():
    block, provided = ctx.concept_lines(VISIBLE, "플래티넘 고객 주문")
    assert "- 플래티넘 고객: segment iceberg.default.customers WHERE tier = 'platinum'" in block
    assert "- 고객 (customer, 회원): key iceberg.default.customers.id, iceberg.default.orders.customer_id" in block
    assert block.rstrip().endswith(ctx.RULE)
    assert provided[0] == {"name": "플래티넘 고객", "uses": ["iceberg.default.customers WHERE tier = 'platinum'"]}
    assert ctx.concept_lines(VISIBLE, "hello") == ("", [])


def test_column_chips_for_one_table():
    cols = ctx.for_table(VISIBLE, "iceberg", "default", "customers")
    assert cols["id"] == [{"concept": "고객", "role": "key", "filter_sql": None, "pii": True}]
    assert cols["tier"][0]["concept"] == "플래티넘 고객"
    assert ctx.for_table(VISIBLE, "polaris_lake", "default", "customers") == {}


def test_describe_finds_by_term_and_lists_narrower(monkeypatch):
    async def fake(user):
        return VISIBLE
    monkeypatch.setattr(ctx, "for_caller", fake)
    d = asyncio.run(ctx.describe_visible(ADMIN, "customer"))
    assert d["name"] == "고객" and d["narrower"] == ["플래티넘 고객"]
    assert d["bindings"][1]["text"] == "iceberg.default.orders.customer_id"
    assert [c["bindings"] for c in asyncio.run(ctx.list_visible(ADMIN))] == [2, 1, 1, 0]
    with pytest.raises(HTTPException):
        asyncio.run(ctx.describe_visible(ADMIN, "없음"))


def test_for_caller_drops_bindings_on_hidden_catalogs(monkeypatch):
    monkeypatch.setenv("FEATURE_ONTOLOGY", "true")
    import app.api.connectors as connectors
    import app.api.ontology as ontology

    async def pool():
        return object()
    async def bindings(p, statuses=None):
        return [{"concept": "고객", "catalog": c, "namespace": "default", "table": "customers", "column": "id",
                 "role": "key", "filter_sql": None} for c in ("iceberg", "polaris_lake")]
    async def concepts_(p):
        return [{"name": "고객", "terms": [], "parent": None, "pii": True, "description": None}]
    async def access(user):
        return catalog_access.CatalogAccess(grants={"polaris_lake": frozenset({("role", "admin")})},
                                            user_id=user["id"], role=user["role"])
    reg.set_entries([CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True),
                     CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake")])
    monkeypatch.setattr(connectors, "get_db_pool", pool)
    monkeypatch.setattr(ctx.__dict__.get("concept_store") or __import__("app.semantic.concept_store", fromlist=["x"]), "list_bindings", bindings)
    monkeypatch.setattr(ontology, "load_concepts", concepts_)
    monkeypatch.setattr(catalog_access, "for_caller", access)
    try:
        got = asyncio.run(ctx.for_caller(READER))
        assert [b["catalog"] for b in got[0]["bindings"]] == ["iceberg"]
        monkeypatch.setenv("FEATURE_ONTOLOGY", "")
        assert asyncio.run(ctx.for_caller(READER)) == []
    finally:
        reg.reset()
