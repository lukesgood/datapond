"""The Model Context Protocol endpoint: read-only tools over the action registry.

One route, because stateless MCP is one route. It resolves the caller, parses the
envelope, and answers initialize / tools/list / tools/call. Nothing here reaches
gate.propose: an approval flow needs a person, and this surface has none — which is
also why nothing but a READ action can be dispatched.
"""
import json
import logging
import os
import time
from typing import Any, Awaitable, Optional

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app import tool_call_log
from app.api.auth import require_user
from app.capabilities import compute_capabilities
from app.chat.actions import Action, InvalidParams, UnknownAction
from app.chat.actions import resolve as resolve_action
from app.chat.actions import validate_params
from app.chat.authz import CapabilityOff, NotPermitted, authorize, held_permissions
from app.chat.executors import EXECUTORS
from app.mcp import protocol, tools

logger = logging.getLogger(__name__)

router = APIRouter()

SERVER_NAME = "datapond"
_UNKNOWN_TOOL = "No such tool: {name}."


async def resolve_principal(user: dict = Depends(require_user)) -> dict:
    """The caller, however they authenticated.

    Today this is exactly the REST path: a `dp_sk_` service-account key or a person's
    JWT, both resolved by require_user into the same dict. The OAuth follow-up replaces
    this function's body — validating an external issuer's access token and mapping its
    subject onto a DataPond principal — and nothing above it changes.
    """
    return user


async def _maybe_await(value: Any) -> Any:
    return await value if isinstance(value, Awaitable) else value


def _unknown(name: str) -> dict:
    """The one answer for a name that does not exist, a tool this caller may not use,
    and a write action.

    Distinguishing them would turn tools/call into an enumeration oracle: a caller could
    learn which components this deployment runs and which scopes their key lacks by
    reading the differences. A caller learns a tool exists by being allowed to see it.
    """
    return protocol.tool_call_result(_UNKNOWN_TOOL.format(name=name), is_error=True)


def _readable_action(name: str) -> Optional[Action]:
    """The action for a tool name, only if it is a READ action.

    Uses `read_action_id_for`, never `action_id_for`: the latter resolves every
    registered action, including the 14 non-READ ones, and `authorize` below checks
    permission and capability only — it does not check kind. Dispatching through the
    permissive lookup would let a write action run the moment a caller happened to
    hold its permission, which is exactly the defect this surface exists to prevent.
    """
    action_id = tools.read_action_id_for(name)
    if action_id is None:
        return None
    try:
        return resolve_action(action_id)
    except UnknownAction:
        return None


async def _log_fallback(rows_written: int, action: Action, params: dict,
                        user: dict, outcome: str, started: float) -> None:
    """A row for a call the inner path did not log — the actions whose executors
    never reach an /ai/* route. Where one did, its row is richer and stands."""
    if rows_written:
        return
    await tool_call_log.record(
        actor=user, tool=action.id, resource_kind="none", resource=[],
        request_text=tool_call_log.masked_for_log(
            json.dumps(params, ensure_ascii=False, default=str)),
        outcome=outcome, via="mcp",
        duration_ms=int((time.perf_counter() - started) * 1000))


async def _call_tool(params: dict, user: dict) -> dict:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return protocol.tool_call_result("A tool name is required.", is_error=True)
    arguments = params.get("arguments") or {}

    action = _readable_action(name)
    if action is None:
        return _unknown(name)
    try:
        authorize(action, user)
    except (NotPermitted, CapabilityOff):
        return _unknown(name)
    try:
        clean = validate_params(action, arguments)
    except InvalidParams as e:
        return protocol.tool_call_result(str(e), is_error=True)

    executor = EXECUTORS.get(action.id)
    if executor is None:
        return protocol.tool_call_result(
            f"{action.label} is not available in this deployment.", is_error=True)

    started = time.perf_counter()
    with tool_call_log.via("mcp"), tool_call_log.counting() as count:
        try:
            payload = await _maybe_await(executor(clean, user))
        except Exception as e:
            await _log_fallback(count(), action, clean, user, "error", started)
            logger.warning("[mcp] %s failed: %s", action.id, e)
            return protocol.tool_call_result(
                f"{action.label} failed: {e}", is_error=True)
        await _log_fallback(count(), action, clean, user, "ok", started)
    return protocol.tool_call_result(
        json.dumps(payload, ensure_ascii=False, default=str))


@router.post("/mcp")
async def mcp_endpoint(request: Request,
                       user: dict = Depends(resolve_principal)) -> Response:
    """Model Context Protocol, 2026-07-28 stateless HTTP: read-only tools."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(protocol.error(None, protocol.PARSE_ERROR, "Invalid JSON"))

    try:
        request_id, method, params = protocol.parse_request(body)
    except protocol.JsonRpcError as e:
        return JSONResponse(protocol.error(e.request_id, e.code, e.message))

    if request_id is None:
        # A notification. The stateless transport answers with no body at all.
        return Response(status_code=status.HTTP_202_ACCEPTED)

    if method == "initialize":
        version = getattr(request.app, "version", "0") or "0"
        return JSONResponse(protocol.result(
            request_id, protocol.initialize_result(SERVER_NAME, version)))

    if method == "tools/list":
        # Capabilities come from this server's own environment, never from the
        # request — a client-supplied map could make tools/list advertise tools this
        # deployment does not actually run.
        return JSONResponse(protocol.result(request_id, protocol.tools_list_result(
            tools.descriptors(held_permissions(user),
                              compute_capabilities(os.environ)))))

    if method == "tools/call":
        return JSONResponse(protocol.result(
            request_id, await _call_tool(params, user)))

    return JSONResponse(protocol.error(
        request_id, protocol.METHOD_NOT_FOUND, f"Unknown method: {method}"))
