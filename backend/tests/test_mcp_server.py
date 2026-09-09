"""The MCP endpoint: who may call it, what it lists, and what it refuses.

The refusal cases matter most. An unknown tool, a tool this key may not use, and a
write action all return the *same* answer, so that tools/call cannot be used to
enumerate either the deployment's components or the key's scopes.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import auth
from app.mcp import protocol, server
from tests.conftest import _Conn, _Pool, _patch_pool

_REAL_REQUIRE_USER = auth.require_user

SERVICE = {"id": "22222222-2222-2222-2222-222222222222", "username": "svc-bot",
           "role": "ai_engineer", "auth_method": "service",
           "permissions": ["knowledge:read", "ai:generate"]}


def _app(user=SERVICE):
    app = FastAPI()
    app.include_router(server.router, prefix="/api")

    async def _override():
        return user
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def _rpc(client, method, params=None, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/api/mcp", json=body)


@pytest.fixture(autouse=True)
def _no_log_writes(monkeypatch):
    """A fake connection pool, not a stand-in for record() itself — so the real
    record() runs end to end (build_row, the INSERT, the success-only counting()
    accounting) exactly as it does in production. See tests/conftest.py."""
    conn = _Conn()
    _patch_pool(monkeypatch, _Pool(conn))
    return conn.rows


@pytest.fixture
def logged(_no_log_writes):
    return _no_log_writes


def test_initialize_answers_with_the_pinned_version():
    r = _rpc(TestClient(_app()), "initialize",
             {"protocolVersion": "2026-07-28", "capabilities": {}})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {}}


def test_a_notification_gets_no_body():
    r = TestClient(_app()).post(
        "/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert r.content == b""


def test_tools_list_is_scoped_to_the_key():
    r = _rpc(TestClient(_app()), "tools/list")
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert "knowledge_search" in names
    assert "spend_summarize" not in names          # the key lacks spend:read
    assert not any(n.startswith("knowledge_create") for n in names)   # writes never listed


def test_an_unknown_method_is_a_protocol_error():
    r = _rpc(TestClient(_app()), "resources/list")
    assert r.json()["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_malformed_json_is_a_parse_error():
    r = TestClient(_app()).post("/api/mcp", content=b"{not json",
                                headers={"Content-Type": "application/json"})
    assert r.json()["error"]["code"] == protocol.PARSE_ERROR


def test_a_tool_runs_and_returns_its_payload_as_text(monkeypatch):
    async def _exec(params, user):
        return {"results": [{"source": "a.md"}]}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _exec)
    r = _rpc(TestClient(_app()), "tools/call",
             {"name": "knowledge_search",
              "arguments": {"collection": "faq", "query": "hi"}})
    result = r.json()["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"results": [{"source": "a.md"}]}


def test_bad_arguments_are_a_tool_error_not_a_protocol_error():
    r = _rpc(TestClient(_app()), "tools/call",
             {"name": "knowledge_search", "arguments": {"collection": "faq"}})
    assert "error" not in r.json()
    assert r.json()["result"]["isError"] is True


@pytest.mark.parametrize("name", [
    "no_such_tool",            # never existed
    "spend_summarize",         # exists, this key lacks spend:read
    "knowledge_create_collection",   # exists, is a write
])
def test_unknown_unauthorised_and_write_names_are_indistinguishable(name):
    r = _rpc(TestClient(_app()), "tools/call", {"name": name, "arguments": {}})
    result = r.json()["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == f"No such tool: {name}."


def test_an_executor_that_raises_becomes_a_tool_error(monkeypatch):
    async def _boom(params, user):
        raise RuntimeError("upstream is down")
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _boom)
    r = _rpc(TestClient(_app()), "tools/call",
             {"name": "knowledge_search",
              "arguments": {"collection": "faq", "query": "hi"}})
    result = r.json()["result"]
    assert result["isError"] is True and "upstream is down" in result["content"][0]["text"]


def test_a_call_that_logged_nothing_gets_a_fallback_row(logged, monkeypatch):
    async def _exec(params, user):
        return {"collections": []}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.list_collections", _exec)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections", "arguments": {}})
    assert len(logged) == 1
    row = logged[0]
    assert row["tool"] == "knowledge.list_collections"
    assert row["outcome"] == "ok" and row["resource_kind"] == "none"
    assert row["via"] == "mcp"


def test_a_call_whose_route_logged_does_not_get_a_second_row(logged, monkeypatch):
    async def _exec(params, user):
        # stands in for the /ai/search wrapper, which logs its own richer row
        await tool_call_log.record(actor=user, tool="ai.search",
                                   resource_kind="collection", resource=["faq"],
                                   request_text="hi", hit_count=2)
        return {"results": []}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _exec)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_search",
          "arguments": {"collection": "faq", "query": "hi"}})
    assert len(logged) == 1
    assert logged[0]["tool"] == "ai.search" and logged[0]["hit_count"] == 2


def test_a_refused_call_writes_no_row(logged):
    _rpc(TestClient(_app()), "tools/call", {"name": "spend_summarize", "arguments": {}})
    assert logged == []


def test_a_failing_call_is_logged_as_an_error(logged, monkeypatch):
    async def _boom(params, user):
        raise RuntimeError("nope")
    monkeypatch.setitem(server.EXECUTORS, "knowledge.list_collections", _boom)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections", "arguments": {}})
    assert len(logged) == 1 and logged[0]["outcome"] == "error"
