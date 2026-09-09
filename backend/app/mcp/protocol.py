"""JSON-RPC 2.0 and the three MCP methods this server answers.

Pure: dicts in, dicts out. It knows nothing about actions, users, permissions or the
database, which is what lets the protocol be tested against message shapes alone — and
what makes it the single place a future SDK adoption would land.

Protocol errors (a malformed envelope, an unknown method) are JSON-RPC errors. A tool
that runs and fails is not one: per the specification that is a *result* carrying
isError, because the call reached the tool. See the design's §7.
"""
from typing import Any, Dict, List, Tuple

PROTOCOL_VERSION = "2026-07-28"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, request_id: Any = None):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(message)


def parse_request(body: Any) -> Tuple[Any, str, Dict]:
    """`(id, method, params)`, or JsonRpcError.

    `id` is None for a notification, which the stateless HTTP transport answers with no
    body at all — so the caller must check for it before dispatching.
    """
    if not isinstance(body, dict):
        raise JsonRpcError(INVALID_REQUEST, "Request must be a JSON object")
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        raise JsonRpcError(INVALID_REQUEST, "Only JSON-RPC 2.0 is supported", request_id)
    method = body.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcError(INVALID_REQUEST, "Missing method", request_id)
    params = body.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise JsonRpcError(INVALID_PARAMS, "params must be an object", request_id)
    return request_id, method, params


def result(request_id: Any, payload: Dict) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error(request_id: Any, code: int, message: str) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def initialize_result(server_name: str, server_version: str) -> Dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": server_name, "version": server_version},
    }


def tools_list_result(tools: List[dict]) -> Dict:
    return {"tools": list(tools)}


def tool_call_result(text: str, is_error: bool = False) -> Dict:
    """A tool's answer as MCP carries it: content blocks, plus the isError flag.

    Action executors return dicts; the server serialises one into a single text block,
    which every client understands.
    """
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
