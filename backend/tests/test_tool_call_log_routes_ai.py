"""search/rag wrappers record one tool_call_log row per successful call and re-raise
on failure. The bodies are stubbed; only the wrapper contract is under test."""
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import ai_vectors, auth

_REAL_REQUIRE_USER = auth.require_user
USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "eng", "role": "ai_engineer"}


def _app():
    app = FastAPI()
    app.include_router(ai_vectors.router, prefix="/api")

    async def _override():
        return USER
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def _capture(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)
    return calls


def test_search_records_hits_and_sources(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        return {"collection": req.collection, "query": req.query, "pii_masked": 2,
                "concepts": [], "results": [{"source": "b.md"}, {"source": "a.md"}]}
    monkeypatch.setattr(ai_vectors, "_search_impl", _impl)

    r = TestClient(_app()).post("/api/ai/search", json={"collection": "faq", "query": "hi"})
    assert r.status_code == 200
    assert len(calls) == 1
    c = calls[0]
    assert c["tool"] == "ai.search" and c["resource_kind"] == "collection"
    assert c["resource"] == ["faq"] and c["hit_count"] == 2
    assert c["citation_sources"] == ["b.md", "a.md"] and c["pii_masked"] == 2
    assert c["outcome"] == "ok" and isinstance(c["duration_ms"], int)


def test_rag_without_answer_is_degraded(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        return {"answer": "", "citations": [{"source": "x.md"}], "has_ai": False,
                "pii_masked": 0, "concepts": []}
    monkeypatch.setattr(ai_vectors, "_rag_impl", _impl)

    r = TestClient(_app()).post("/api/ai/rag", json={"collection": "faq", "question": "why"})
    assert r.status_code == 200
    assert calls[0]["tool"] == "ai.rag" and calls[0]["outcome"] == "degraded"
    assert calls[0]["hit_count"] == 1


def test_failure_is_recorded_as_error_and_reraised(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        raise HTTPException(403, "not a member")
    monkeypatch.setattr(ai_vectors, "_search_impl", _impl)

    r = TestClient(_app()).post("/api/ai/search", json={"collection": "faq", "query": "hi"})
    assert r.status_code == 403
    assert calls[0]["outcome"] == "error" and calls[0]["hit_count"] == 0


def test_request_text_is_the_masked_query(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        return {"collection": req.collection, "query": req.query, "pii_masked": 1,
                "concepts": [], "results": []}
    monkeypatch.setattr(ai_vectors, "_search_impl", _impl)
    TestClient(_app()).post("/api/ai/search",
                            json={"collection": "faq", "query": "연락처 010-1234-5678"})
    assert "010-1234-5678" not in calls[0]["request_text"]
