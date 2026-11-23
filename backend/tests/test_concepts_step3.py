"""Concept bindings, step 3: concept words in metric matching, PII mask suggestions,
OpenMetadata glossary import (app/semantic/context.py, concepts.py, om_glossary.py)."""
from types import SimpleNamespace

from app.semantic import context, om_glossary
from app.semantic.concepts import pii_gaps

CONCEPTS = [
    {"name": "고객", "terms": ["customer", "회원"], "pii": True, "parent": None},
    {"name": "플래티넘 고객", "terms": ["vip 고객"], "pii": False, "parent": "고객"},
    {"name": "주문", "terms": ["order"], "pii": False, "parent": None},
]
METRICS = [
    {"name": "customer_count", "label": "고객 수", "synonyms": []},
    {"name": "revenue", "label": "매출", "synonyms": ["매출액"]},
]


def test_alias_map_uses_one_word_terms_only():
    a = context.alias_map(CONCEPTS)
    assert set(a["회원"]) == {"customer", "고객"}
    assert set(a["고객"]) == {"customer", "회원"}
    assert "플래티넘 고객" not in a and "vip 고객" not in a


def test_a_concept_word_matches_a_metric_label():
    a = context.alias_map(CONCEPTS)
    assert context.suggest(METRICS, "지난달 회원 수는?") is None          # without aliases
    assert context.suggest(METRICS, "지난달 회원 수는?", aliases=a)["name"] == "customer_count"
    # the count word still has to be asked for, through the word the question used
    assert context.suggest(METRICS, "회원 목록", aliases=a) is None
    # aliases only add matches: the label itself still matches
    assert context.suggest(METRICS, "고객 수", aliases=a)["name"] == "customer_count"


def test_metric_lines_rank_with_aliases():
    a = context.alias_map(CONCEPTS)
    metrics = [dict(m, version=1, measure="COUNT(*)", base_table="iceberg.default.customers",
                    filters=None, time_column=None) for m in METRICS]
    _, provided = context.metric_lines(metrics, "customer 수", aliases=a)
    assert provided[0] == "customer_count@v1"


def _b(concept, table, column, role="key", status="approved", filter_sql=None):
    return {"concept": concept, "catalog": "iceberg", "namespace": "default", "table": table,
            "column": column, "role": role, "status": status, "filter_sql": filter_sql}


def _mask(catalog, table, column, enabled=True):
    return SimpleNamespace(catalog=catalog, schema="default", table=table, column=column,
                           enabled=enabled)


def test_pii_gaps_lists_unmasked_columns_of_pii_concepts():
    engine = lambda n: {"awsdatacatalog": "iceberg"}.get(n.lower(), n)
    bindings = [
        _b("고객", "customers", "id"),
        _b("고객", "orders", "customer_id"),
        _b("고객", "customers", "email", role="attribute"),
        _b("고객", "customers", "tier", role="filter", filter_sql="tier = 'x'"),
        _b("고객", "payments", "customer_id", status="proposed"),
        _b("주문", "orders", "id"),
    ]
    gaps = pii_gaps(CONCEPTS, bindings, [_mask("AwsDataCatalog", "customers", "email")], engine)
    assert [(g["table"], g["column"], g["key"]) for g in gaps] == [
        ("customers", "id", True), ("orders", "customer_id", True)]


GLOSSARY_JSON = {"data": [
    {"name": "Customer", "displayName": "고객", "fullyQualifiedName": "Biz.Customer",
     "synonyms": ["회원", "buyer"], "tags": [{"tagFQN": "PII.Sensitive"}]},
    {"name": "VIP", "displayName": "플래티넘 고객", "fullyQualifiedName": "Biz.Customer.VIP",
     "parent": {"fullyQualifiedName": "Biz.Customer"}, "synonyms": []},
    {"name": "Refund", "fullyQualifiedName": "Biz.Refund", "description": "환불",
     "synonyms": ["환불"]},
]}

GLOSSARY_CSV = ("parent,name*,displayName,description,synonyms,relatedTerms,references,tags\n"
                ",Customer,고객,,회원;buyer,,,PII.Sensitive\n"
                "Biz.Customer,VIP,플래티넘 고객,,,,,\n")


def test_glossary_json_becomes_concepts():
    cs = {c["name"]: c for c in om_glossary.to_concepts(om_glossary.parse_terms(GLOSSARY_JSON))}
    assert cs["고객"]["terms"] == ["Customer", "회원", "buyer"] and cs["고객"]["pii"] is True
    assert cs["플래티넘 고객"]["parent"] == "고객"
    assert cs["Refund"]["terms"] == ["환불"] and cs["Refund"]["description"] == "환불"


def test_glossary_csv_export_becomes_concepts():
    cs = {c["name"]: c for c in om_glossary.to_concepts(om_glossary.parse_terms(GLOSSARY_CSV))}
    assert cs["고객"]["terms"] == ["Customer", "회원", "buyer"] and cs["고객"]["pii"]
    assert cs["플래티넘 고객"]["parent"] == "고객"     # short CSV parent matched by last part


def test_tagged_columns_become_proposals_and_known_ones_are_skipped():
    terms = om_glossary.parse_terms(GLOSSARY_JSON)
    tables = [
        {"fullyQualifiedName": "datapond-trino.iceberg.default.orders", "columns": [
            {"name": "customer_id", "tags": [{"tagFQN": "Biz.Customer", "source": "Glossary"}]},
            {"name": "note", "tags": [{"tagFQN": "PII.Sensitive", "source": "Classification"}]},
            {"name": "buyer_email", "tags": [{"tagFQN": "biz.customer", "source": "Glossary"}]},
        ]},
        {"fullyQualifiedName": "other.unknown_db.s.t", "columns": [
            {"name": "x", "tags": [{"tagFQN": "Biz.Customer", "source": "Glossary"}]}]},
    ]
    found = om_glossary.proposals_from_tables(
        tables, om_glossary.term_index(terms), lambda n: "iceberg" if n == "iceberg" else None)
    assert [(p["concept"], p["table"], p["column"], p["role"]) for p in found] == [
        ("고객", "orders", "customer_id", "key"), ("고객", "orders", "buyer_email", "attribute")]
    rejected = [dict(_b("고객", "orders", "customer_id"), status="rejected")]
    assert [p["column"] for p in om_glossary.new_proposals(found, rejected)] == ["buyer_email"]


def test_quoted_fqn_parts():
    assert om_glossary._fqn_parts('svc."db.x".s.t') == ["svc", "db.x", "s", "t"]


# ── routes ──────────────────────────────────────────────────────────────────────
import asyncio

import pytest
from fastapi import HTTPException

from app.api import concepts as routes
from tests.test_concept_bindings import ADMIN, world  # noqa: F401  (fixture)


def test_a_pull_needs_the_add_on_and_an_upload_does_not(world, monkeypatch):
    monkeypatch.delenv("FEATURE_OPENMETADATA", raising=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.import_openmetadata(routes.GlossaryImport(), admin=ADMIN))
    assert e.value.status_code == 409

    saved = []
    async def save(pool, cs):
        saved.extend(cs)
        return {"created": [c["name"] for c in cs], "terms_added": 0, "pii_differs": []}
    monkeypatch.setattr(om_glossary, "save_concepts", save)
    out = asyncio.run(routes.import_openmetadata(routes.GlossaryImport(glossary=GLOSSARY_CSV), admin=ADMIN))
    assert out["source"] == "upload" and out["bindings_proposed"] == 0
    assert [c["name"] for c in saved] == ["고객", "플래티넘 고객"]
    assert "glossary import" in world["audit"][-1]


def test_a_pull_proposes_tagged_columns_and_approves_none(world, monkeypatch):
    monkeypatch.setenv("FEATURE_OPENMETADATA", "true")
    async def pull():
        return GLOSSARY_JSON["data"], [{"fullyQualifiedName": "datapond-trino.iceberg.default.orders", "columns": [
            {"name": "customer_id", "tags": [{"tagFQN": "Biz.Customer", "source": "Glossary"}]}]}]
    async def save(pool, cs):
        return {"created": [], "terms_added": 0, "pii_differs": []}
    monkeypatch.setattr(om_glossary, "pull", pull)
    monkeypatch.setattr(om_glossary, "save_concepts", save)
    out = asyncio.run(routes.import_openmetadata(routes.GlossaryImport(), admin=ADMIN))
    assert out["bindings_proposed"] == 1
    row = world["rows"][-1]
    assert (row["table"], row["column"], row["status"], row["source"]) == ("orders", "customer_id", "proposed", "openmetadata")
    # a second pull proposes nothing new
    assert asyncio.run(routes.import_openmetadata(routes.GlossaryImport(), admin=ADMIN))["bindings_proposed"] == 0


def test_pii_gaps_route_lists_unmasked_pii_columns(world, monkeypatch):
    from app.rls import loader
    async def masks():
        return []
    monkeypatch.setattr(loader, "load_masks", masks)
    async def pii_concepts(pool):
        return [{"name": "고객", "terms": [], "pii": True}]
    monkeypatch.setattr(routes, "load_concepts", pii_concepts)
    asyncio.run(routes.create_binding(routes.BindingBody(concept="고객", catalog="iceberg",
                                                         table="default.orders", column="customer_id", role="key"), user=ADMIN))
    out = asyncio.run(routes.pii_gaps(user=ADMIN))
    assert [(g["table"], g["column"]) for g in out["gaps"]] == [("orders", "customer_id")]
