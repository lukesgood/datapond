"""Catalog grants on the query path (multi-catalog P3).

After bare names are resolved and before RLS, every table a statement names is placed
in its catalog (three parts name it, two or one mean the default). A catalog the
caller may not use refuses the statement with a 403 and a security audit row, and the
refusal does not say which catalog. The resolver itself never matches a bare name in
a hidden catalog, so the ambiguity error cannot list one either.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.queries as q
from app import catalog_access
from app import catalog_registry as reg
from app.api.table_resolver import CatalogIndex
from app.catalog_registry import CatalogEntry

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer",
         "permissions": ["query:run"]}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob",
       "role": "business_analyst", "permissions": ["query:run"]}
ADMIN = {"id": "33333333-3333-3333-3333-333333333333", "username": "root", "role": "admin"}
ADMIN_KEY = {**ADMIN, "auth_method": "service", "permissions": ["query:run"]}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Req:
    def __init__(self, query):
        self.query, self.save_history, self.origin = query, False, "ui"


class _Engine:
    rls_dialect = "trino"
    default_catalog = "iceberg"
    default_schema = "default"

    def __init__(self):
        self.ran = []

    def execute(self, sql, user):
        self.ran.append(sql)
        return [[1]], ["n"]

    def map_error(self, e):
        return "error", str(e), 500


@pytest.fixture
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    catalog_access.set_grants({"finance": [("role", "business_analyst")]})
    engine = _Engine()
    monkeypatch.setattr(q, "get_engine", lambda: engine)
    monkeypatch.setattr(q, "get_catalog_index", lambda: CatalogIndex(
        namespaces=("sales", "finance.gl"),
        tables={"orders": ("sales",), "entries": (("finance", "gl"),),
                "accounts": ("sales", ("finance", "gl"))},
        default_catalog="iceberg"))
    audited = []

    async def _record(**kw):
        audited.append(kw)
    monkeypatch.setattr(q.security_audit, "record", _record)
    monkeypatch.setattr(q, "RLS_ENABLED", False)
    yield engine, audited
    reg.reset()


def test_an_open_catalog_runs_as_before(world):
    engine, audited = world
    res = _run(q._execute_query_impl(_Req("SELECT * FROM orders"), db=None, user=ALICE))
    assert res.row_count == 1 and "sales.orders" in engine.ran[0]
    assert audited == []


def test_a_three_part_name_in_a_hidden_catalog_is_refused_and_audited(world):
    engine, audited = world
    with pytest.raises(HTTPException) as exc:
        _run(q._execute_query_impl(_Req("SELECT * FROM finance.gl.entries"),
                                   db=None, user=ALICE))
    assert exc.value.status_code == 403
    assert "finance" not in exc.value.detail and "entries" not in exc.value.detail
    assert engine.ran == []
    assert [(a["permission"], a["outcome"], a["route"]) for a in audited] == [
        ("catalog:use", "denied", "/api/queries/execute")]
    assert "finance" not in audited[0]["reason"]


def test_a_hidden_catalog_inside_a_subquery_is_refused(world):
    with pytest.raises(HTTPException) as exc:
        _run(q._execute_query_impl(
            _Req("SELECT * FROM sales.orders WHERE id IN (SELECT id FROM finance.gl.entries)"),
            db=None, user=ALICE))
    assert exc.value.status_code == 403


def test_a_granted_role_runs_it(world):
    engine, _ = world
    _run(q._execute_query_impl(_Req("SELECT * FROM finance.gl.entries"), db=None, user=BOB))
    assert engine.ran


def test_a_signed_in_admin_runs_it(world):
    engine, _ = world
    _run(q._execute_query_impl(_Req("SELECT * FROM finance.gl.entries"), db=None, user=ADMIN))
    assert engine.ran


def test_an_admin_accounts_key_without_a_grant_is_refused(world):
    with pytest.raises(HTTPException) as exc:
        _run(q._execute_query_impl(_Req("SELECT * FROM finance.gl.entries"),
                                   db=None, user=ADMIN_KEY))
    assert exc.value.status_code == 403


def test_a_bare_name_only_in_a_hidden_catalog_is_not_found_without_candidates(world):
    with pytest.raises(HTTPException) as exc:
        _run(q._execute_query_impl(_Req("SELECT * FROM entries"), db=None, user=ALICE))
    assert exc.value.status_code == 400
    assert "not found" in exc.value.detail
    assert "finance" not in exc.value.detail and "gl" not in exc.value.detail.split("'")[2]


def test_a_bare_name_also_in_a_hidden_catalog_resolves_to_the_visible_one(world):
    engine, _ = world
    _run(q._execute_query_impl(_Req("SELECT * FROM accounts"), db=None, user=ALICE))
    assert "sales.accounts" in engine.ran[0]
    # ... while a caller who may use both is told it is ambiguous, as before.
    with pytest.raises(HTTPException) as exc:
        _run(q._execute_query_impl(_Req("SELECT * FROM accounts"), db=None, user=BOB))
    assert "finance.gl.accounts" in exc.value.detail


def test_grants_that_cannot_be_read_refuse_every_statement(world, monkeypatch):
    engine, audited = world
    catalog_access.reset()

    async def _broken():
        raise ConnectionError("database is gone")
    monkeypatch.setattr(catalog_access, "_pool", _broken)
    with pytest.raises(HTTPException) as exc:
        _run(q._execute_query_impl(_Req("SELECT * FROM sales.orders"), db=None, user=ALICE))
    assert exc.value.status_code == 403 and engine.ran == []


def test_execute_logs_the_refusal_as_refused(world, monkeypatch):
    calls = []

    async def _log(**kw):
        calls.append(kw)
    monkeypatch.setattr(q.tool_call_log, "record", _log)
    with pytest.raises(HTTPException):
        _run(q.execute_query(_Req("SELECT * FROM finance.gl.entries"), db=None, user=ALICE))
    assert calls[0]["outcome"] == "refused"


# ── /queries/plan: EXPLAIN describes what a statement reads ───────────────────

class _PlanReq:
    def __init__(self, sql):
        self.sql, self.deep = sql, False


def test_plan_of_a_hidden_catalog_is_refused(world, monkeypatch):
    _, audited = world
    monkeypatch.setattr(q, "explain_statement",
                        lambda *a, **k: pytest.fail("EXPLAIN must not run"))
    with pytest.raises(HTTPException) as exc:
        _run(q.review_plan(_PlanReq("SELECT * FROM finance.gl.entries"), user=ALICE))
    assert exc.value.status_code == 403
    assert audited[0]["route"] == "/api/queries/plan"


# ── the assistant's / MCP's query preview ─────────────────────────────────────

def test_the_chat_preview_of_a_hidden_catalog_is_refused_without_explaining(world, monkeypatch):
    from app.api import query_engine, table_resolver
    from app.chat.analysis import query as chat_query
    engine, _ = world
    monkeypatch.setattr(query_engine, "get_engine", lambda: engine)
    monkeypatch.setattr(table_resolver, "get_catalog_index", q.get_catalog_index)
    monkeypatch.setattr(chat_query, "explain_statement",
                        lambda *a, **k: pytest.fail("EXPLAIN must not run"))
    out = _run(chat_query.preview_query_run({"sql": "SELECT * FROM finance.gl.entries"}, ALICE))
    assert out["validated"] is False and "may not use" in out["error"]
    out = _run(chat_query.explain_plan({"sql": "SELECT * FROM entries"}, ALICE))
    assert out["validated"] is False and "finance" not in out["error"]
