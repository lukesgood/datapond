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
    assert c["resource"] == ["sales.orders"] and c["hit_count"] == 2
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
