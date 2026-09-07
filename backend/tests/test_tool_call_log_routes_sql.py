from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import ai_sql, auth

_REAL_REQUIRE_USER = auth.require_user
USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "eng", "role": "ai_engineer"}


def _app():
    app = FastAPI()
    app.include_router(ai_sql.router, prefix="/api")

    async def _override():
        return USER
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def test_generate_sql_records_generation_only(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(req, user):
        return ai_sql.AskResponse(sql="SELECT 1", explanation="", has_ai=True,
                                  provider="litellm", pii_masked=1)
    monkeypatch.setattr(ai_sql, "_generate_sql_impl", _impl)

    r = TestClient(_app()).post("/api/ai/sql", json={"question": "count orders"})
    assert r.status_code == 200
    c = calls[0]
    assert c["tool"] == "ai.sql" and c["resource_kind"] == "none" and c["resource"] == []
    assert c["hit_count"] == 0 and c["pii_masked"] == 1 and c["outcome"] == "ok"


def test_generate_sql_without_backend_is_degraded(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(req, user):
        return ai_sql.AskResponse(sql="-- no backend", explanation="", has_ai=False,
                                  provider="none", pii_masked=0)
    monkeypatch.setattr(ai_sql, "_generate_sql_impl", _impl)
    TestClient(_app()).post("/api/ai/sql", json={"question": "count orders"})
    assert calls[0]["outcome"] == "degraded"
