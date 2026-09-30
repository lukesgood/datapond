"""Catalog grants in the AI SQL prompt (multi-catalog P3).

The schema context is built and cached for every catalog; a caller is shown only the
catalogs it may use, and a generated statement that names another is not validated
against the engine (EXPLAIN would describe what exists there).
"""
import asyncio

import pytest

import app.api.ai_sql as m
from app import catalog_access, tool_call_log
from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "auditor"}
ADMIN = {"id": "33333333-3333-3333-3333-333333333333", "username": "root", "role": "admin"}

SCHEMA = ("Available tables (catalog: iceberg):\n"
          "  iceberg.sales.orders: id (int)\n"
          "Available tables (catalog: finance):\n"
          "  finance.ledger.entries: amount (double)")


@pytest.fixture(autouse=True)
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    catalog_access.set_grants({"finance": [("role", "auditor")]})
    monkeypatch.setenv("QUERY_ENGINE", "trino")

    async def _record(**kw):
        return None
    monkeypatch.setattr(tool_call_log, "record", _record)
    yield
    reg.reset()


def _ctx(user):
    return m._schema_for_caller(SCHEMA, asyncio.run(catalog_access.for_caller(user)))


def test_an_open_catalog_prompt_is_unchanged():
    catalog_access.set_grants({})
    assert _ctx(ALICE) == SCHEMA


def test_a_hidden_catalog_is_left_out_of_the_prompt():
    ctx = _ctx(ALICE)
    assert "finance" not in ctx and "iceberg.sales.orders" in ctx


def test_a_granted_role_and_an_admin_keep_it():
    assert _ctx(BOB) == SCHEMA
    assert _ctx(ADMIN) == SCHEMA


def test_nothing_visible_reads_as_an_empty_catalog():
    catalog_access.set_grants({"finance": [("role", "auditor")],
                               "iceberg": [("role", "auditor")]})
    assert _ctx(ALICE) == "No tables found in the catalog."


def test_the_prompt_and_the_validation_see_only_the_callers_catalogs(monkeypatch):
    prompts, validated = [], []
    monkeypatch.setattr(m, "_cfg", lambda: {
        "litellm_url": "http://litellm:4000", "litellm_model": "default", "master_key": ""})
    monkeypatch.setattr(m, "_get_schema_context", lambda: SCHEMA)
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")
    monkeypatch.setattr(m, "validate_sql", lambda sql: validated.append(sql) or (True, None))
    monkeypatch.setattr(m, "_validation_enabled", lambda: True, raising=False)

    def _llm(system, messages):
        prompts.append(system)
        return '{"sql": "SELECT * FROM finance.ledger.entries", "explanation": "x"}'
    monkeypatch.setattr(m, "_call_litellm", _llm)

    res = asyncio.run(m.generate_sql(m.AskRequest(question="ledger"), user=ALICE))
    assert "finance" not in prompts[0]
    assert validated == [], "EXPLAIN ran against a catalog the caller may not use"
    assert res.validated is False and "may not use" in (res.validation_error or "")
