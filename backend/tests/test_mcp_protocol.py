"""JSON-RPC 2.0 and the three MCP methods, with no application underneath.

The protocol layer is the part a future SDK would replace, so it is tested against
message shapes rather than against DataPond behaviour: everything here would still be
true if the tools were something else entirely.
"""
import pytest

from app.mcp import protocol as p


def test_the_protocol_version_is_pinned():
    assert p.PROTOCOL_VERSION == "2026-07-28"


def test_parse_request_returns_id_method_params():
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "knowledge_search", "arguments": {"collection": "faq"}}}
    assert p.parse_request(body) == (3, "tools/call", body["params"])


def test_a_notification_has_no_id():
    rid, method, params = p.parse_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert rid is None and method == "notifications/initialized" and params == {}


@pytest.mark.parametrize("body,code", [
    ("not an object", p.INVALID_REQUEST),
    ({"id": 1, "method": "tools/list"}, p.INVALID_REQUEST),            # no jsonrpc
    ({"jsonrpc": "1.0", "id": 1, "method": "tools/list"}, p.INVALID_REQUEST),
    ({"jsonrpc": "2.0", "id": 1}, p.INVALID_REQUEST),                  # no method
    ({"jsonrpc": "2.0", "id": 1, "method": ""}, p.INVALID_REQUEST),
    ({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}, p.INVALID_PARAMS),
])
def test_malformed_requests_are_refused_with_the_right_code(body, code):
    with pytest.raises(p.JsonRpcError) as exc:
        p.parse_request(body)
    assert exc.value.code == code


def test_the_error_keeps_the_request_id_when_there_was_one():
    with pytest.raises(p.JsonRpcError) as exc:
        p.parse_request({"jsonrpc": "1.0", "id": 7, "method": "tools/list"})
    assert exc.value.request_id == 7


def test_result_and_error_envelopes():
    assert p.result(1, {"ok": True}) == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    assert p.error(1, p.METHOD_NOT_FOUND, "nope") == {
        "jsonrpc": "2.0", "id": 1,
        "error": {"code": p.METHOD_NOT_FOUND, "message": "nope"}}


def test_initialize_result_announces_tools_and_the_version():
    r = p.initialize_result("datapond", "0.1.0")
    assert r["protocolVersion"] == "2026-07-28"
    assert r["capabilities"] == {"tools": {}}
    assert r["serverInfo"] == {"name": "datapond", "version": "0.1.0"}


def test_tools_list_result_wraps_the_list():
    assert p.tools_list_result([{"name": "a"}]) == {"tools": [{"name": "a"}]}


def test_tool_call_result_is_a_text_content_block():
    ok = p.tool_call_result('{"rows": 1}')
    assert ok == {"content": [{"type": "text", "text": '{"rows": 1}'}], "isError": False}
    assert p.tool_call_result("boom", is_error=True)["isError"] is True
