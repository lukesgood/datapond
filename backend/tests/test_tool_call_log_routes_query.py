from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import auth, queries
from app.api.queries import QueryResult

_REAL_REQUIRE_USER = auth.require_user
USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "ana",
        "role": "business_analyst"}


def _app():
    app = FastAPI()
    app.include_router(queries.router, prefix="/api")

    async def _override():
        return USER
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    app.dependency_overrides[queries.get_db] = lambda: None
    return app


import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def registry():
    from app import catalog_registry as reg
    from app.catalog_registry import CatalogEntry
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    yield
    reg.reset()


def test_the_row_names_the_tables_the_resolved_statement_reads(monkeypatch):
    """A bare name is recorded as the table it resolved to, catalog included — also
    when the statement is then refused — and request_text stays what was sent."""
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(request, db, user):
        queries._note_resolved("SELECT * FROM sales.orders JOIN finance.gl.entries e ON 1=1")
        raise HTTPException(403, "no")
    monkeypatch.setattr(queries, "_execute_query_impl", _impl)
    r = TestClient(_app()).post("/api/queries/execute",
                                json={"query": "SELECT * FROM orders JOIN finance.gl.entries e ON 1=1"})
    assert r.status_code == 403
    c = calls[0]
    assert c["resource"] == ["finance.gl.entries", "iceberg.sales.orders"]
    assert c["outcome"] == "refused"
    assert c["request_text"] == "SELECT * FROM orders JOIN finance.gl.entries e ON 1=1"


def test_execute_records_tables_and_row_count(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(request, db, user):
        return QueryResult(columns=["n"], rows=[[1], [2]], execution_time_ms=3.0,
                           row_count=2, truncated=False)
    monkeypatch.setattr(queries, "_execute_query_impl", _impl)

    r = TestClient(_app()).post("/api/queries/execute",
                                json={"query": "SELECT count(*) FROM sales.orders",
                                      "save_history": False})
    assert r.status_code == 200
    c = calls[0]
    assert c["tool"] == "query.execute" and c["resource_kind"] == "tables"
    assert c["resource"] == ["iceberg.sales.orders"] and c["hit_count"] == 2
    assert c["outcome"] == "ok"


def test_save_history_false_does_not_skip_the_log(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(request, db, user):
        return QueryResult(columns=[], rows=[], execution_time_ms=1.0, row_count=0,
                           truncated=False)
    monkeypatch.setattr(queries, "_execute_query_impl", _impl)
    TestClient(_app()).post("/api/queries/execute",
                            json={"query": "SELECT 1", "save_history": False})
    assert len(calls) == 1


def test_request_text_is_masked_even_under_block_mode(monkeypatch):
    """PII_GUARDRAIL_MODE=block returns the ORIGINAL text to the caller (pii_ko.apply
    contract) — the log must still never receive it raw."""
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "block")
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(request, db, user):
        return QueryResult(columns=["n"], rows=[[1]], execution_time_ms=1.0,
                           row_count=1, truncated=False)
    monkeypatch.setattr(queries, "_execute_query_impl", _impl)

    r = TestClient(_app()).post(
        "/api/queries/execute",
        json={"query": "SELECT * FROM t WHERE phone = '010-1234-5678'"})
    assert r.status_code == 200
    assert "010-1234-5678" not in calls[0]["request_text"]
