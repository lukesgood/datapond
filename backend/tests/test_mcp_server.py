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
from app.chat.actions import REGISTRY, ActionKind
from app.mcp import protocol, server, tools
from tests.conftest import _Conn, _Pool, _patch_pool

_REAL_REQUIRE_USER = auth.require_user

SERVICE = {"id": "22222222-2222-2222-2222-222222222222", "username": "svc-bot",
           "role": "ai_engineer", "auth_method": "service",
           "permissions": ["knowledge:read", "ai:generate"]}

# Holds every permission any action in the registry needs — including every write's.
# Used to prove the kind guard (read_action_id_for) refuses a write on its own, not
# merely because this caller happens to lack the permission — see
# test_a_write_is_refused_even_to_a_caller_who_holds_its_permission below.
WRITER = {**SERVICE, "permissions": sorted({a.permission for a in REGISTRY.values()})}

# Holds catalog:read only, so tools/list's permission filter admits catalog's three
# actions on its own — isolating capability as the only thing left to spoof. See
# test_tools_list_ignores_client_supplied_capabilities below.
CATALOG_READER = {**SERVICE, "permissions": ["catalog:read"]}


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
    # The envelope now labels executor payloads as data (protocol.UNTRUSTED_NOTICE):
    # the JSON follows the notice rather than standing alone.
    text = result["content"][0]["text"]
    assert text.startswith(protocol.UNTRUSTED_NOTICE)
    body = text[len(protocol.UNTRUSTED_NOTICE):].lstrip("\n")
    assert json.loads(body) == {"results": [{"source": "a.md"}]}


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


@pytest.mark.parametrize("name", [tools.mcp_name(a.id) for a in REGISTRY.values()
                                  if a.kind is not ActionKind.READ])
def test_a_write_is_refused_even_to_a_caller_who_holds_its_permission(name):
    """The write case in test_unknown_unauthorised_and_write_names_are_indistinguishable
    is parametrized on knowledge_create_collection, whose permission (knowledge:write)
    SERVICE does not hold — so that test only ever proves `authorize` refuses it, never
    that the kind guard (read_action_id_for, not action_id_for) is what stands between
    tools/call and dispatching a write. WRITER holds every permission in the registry,
    including this one's, so authorize alone would let it through; only the kind guard
    stops it here.
    """
    r = _rpc(TestClient(_app(WRITER)), "tools/call", {"name": name, "arguments": {}})
    assert r.json()["result"]["content"][0]["text"] == f"No such tool: {name}."


def test_tools_list_ignores_client_supplied_capabilities(monkeypatch):
    """tools/list must source capabilities from this server's own environment
    (compute_capabilities(os.environ)) and never from the request — a client-supplied
    map spoofing every gated capability on must not grow the list. `authorize` would
    still refuse a spoofed tool at call time (it recomputes capability_on itself), but
    tools/list itself would already have told an external agent which components this
    deployment does not run, which is what this guards against.
    """
    for flag in ("FEATURE_TRINO", "FEATURE_POLARIS", "FEATURE_GLUE"):
        monkeypatch.delenv(flag, raising=False)
    client = TestClient(_app(CATALOG_READER))

    baseline = _rpc(client, "tools/list").json()["result"]["tools"]
    assert not any(t["name"].startswith("catalog_") for t in baseline)

    spoofed = _rpc(client, "tools/list", {
        "capabilities": {"catalog": True, "connectors": True, "query": True,
                          "dashboards": True, "pipelines": True, "streaming": True,
                          "experiments": True, "notebooks": True},
    }).json()["result"]["tools"]
    assert len(spoofed) == len(baseline)
    assert not any(t["name"].startswith("catalog_") for t in spoofed)


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
    # A phone number and an email in the arguments the fallback logs — tool_call_log
    # is append-only (a trigger rejects UPDATE and DELETE), so a raw PII value that
    # lands here can never be scrubbed. masked_for_log must run before the INSERT.
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections",
          "arguments": {"q": "010-1234-5678 me@example.com"}})
    assert len(logged) == 1
    row = logged[0]
    assert row["tool"] == "knowledge.list_collections"
    assert row["outcome"] == "ok" and row["resource_kind"] == "none"
    assert row["via"] == "mcp"
    assert "[휴대전화]" in row["request_masked"] and "[이메일]" in row["request_masked"]
    assert "010-1234-5678" not in row["request_masked"]
    assert "me@example.com" not in row["request_masked"]


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


def test_a_refused_call_writes_one_refused_row(logged):
    """This used to assert `logged == []`. A refused call is the row an auditor most
    wants — a key asking for what it may not have — so it is now recorded. The answer
    to the caller is unchanged; see the indistinguishability tests above."""
    _rpc(TestClient(_app()), "tools/call", {"name": "spend_summarize", "arguments": {}})
    assert len(logged) == 1
    assert logged[0]["outcome"] == "refused" and logged[0]["tool"] == "spend.summarize"
    assert logged[0]["via"] == "mcp"


def test_a_failing_call_is_logged_as_an_error(logged, monkeypatch):
    async def _boom(params, user):
        raise RuntimeError("nope")
    monkeypatch.setitem(server.EXECUTORS, "knowledge.list_collections", _boom)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections", "arguments": {}})
    assert len(logged) == 1 and logged[0]["outcome"] == "error"


# ── Refusals are audited ─────────────────────────────────────────────────────
# Names here are MCP names (action ids with dots replaced by underscores), and the
# argument shapes are the ones the existing tests above established as valid/invalid —
# otherwise a test could pass because the name was unknown rather than for its own
# reason.

def _refusals(rows):
    return [r for r in rows if r["outcome"] == "refused"]


def test_a_name_that_never_existed_is_recorded_under_the_sentinel(logged):
    r = _rpc(TestClient(_app()), "tools/call", {"name": "no_such_tool", "arguments": {}})
    assert r.json()["result"]["isError"] is True
    [row] = _refusals(logged)
    assert row["tool"] == tool_call_log.UNKNOWN_TOOL
    assert row["via"] == "mcp" and row["actor_username"] == "svc-bot"
    assert "no_such_tool" in row["request_masked"]


def test_a_write_name_is_recorded_under_the_sentinel_with_the_name_kept(logged):
    """A write is not an action this surface can run, so `_readable_action` never
    resolves it and the row cannot claim a tool that was going to run. The requested
    name is kept in request_masked, which is where the auditor reads it. Resolving it
    through the permissive lookup just for the log would put the very resolver the
    dispatch guard exists to avoid back into this path."""
    _rpc(TestClient(_app(WRITER)), "tools/call",
         {"name": "knowledge_create_collection", "arguments": {}})
    [row] = _refusals(logged)
    assert row["tool"] == tool_call_log.UNKNOWN_TOOL
    assert "knowledge_create_collection" in row["request_masked"]


def test_bad_arguments_are_recorded_as_refused(logged):
    # the shape test_bad_arguments_are_a_tool_error_not_a_protocol_error uses: no query
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_search", "arguments": {"collection": "faq"}})
    [row] = _refusals(logged)
    assert row["tool"] == "knowledge.search"


def test_an_action_this_deployment_does_not_run_is_recorded_as_refused(monkeypatch, logged):
    monkeypatch.delitem(server.EXECUTORS, "knowledge.list_collections", raising=False)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections", "arguments": {}})
    [row] = _refusals(logged)
    assert row["tool"] == "knowledge.list_collections"


def test_a_successful_call_records_no_refusal(monkeypatch, logged):
    async def _exec(params, user):
        return {"results": []}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _exec)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_search", "arguments": {"collection": "faq", "query": "hi"}})
    assert _refusals(logged) == [] and len(logged) == 1
