"""Reads over sources: what is connected, what ran, and what the checks found."""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class ConnectionRef(_Strict):
    connection_id: str


class ConnectionHistory(_Strict):
    connection_id: str
    # Bounded: the model puts whatever comes back into a prompt, and an unbounded
    # history is an unbounded prompt.
    limit: int = Field(default=20, ge=1, le=100)


async def list_sources(params: dict, user: dict) -> dict:
    from app.api.connectors import list_connections
    return {"sources": await list_connections(user=user)}


async def sync_history(params: dict, user: dict) -> dict:
    from app.api.connectors import get_sync_history
    return {"history": await get_sync_history(
        connection_id=params["connection_id"], limit=params["limit"], user=user)}


async def quality_checks(params: dict, user: dict) -> dict:
    from app.api.connectors import get_quality_checks
    return {"quality": await get_quality_checks(
        connection_id=params["connection_id"], limit=params["limit"], user=user)}


ACTIONS = (
    Action("connectors.list_sources", "List sources",
           "Every connected source and its current sync state.",
           ("*",), "connector:read", ActionKind.READ, _Strict,
           capability="connectors"),
    Action("connectors.sync_history", "Sync history",
           "Recent sync runs for one source: when, how long, and how they ended.",
           ("*",), "connector:read", ActionKind.READ, ConnectionHistory,
           capability="connectors"),
    Action("connectors.quality_checks", "Quality checks",
           "Row-count drift and null-rate findings recorded after a source's syncs.",
           ("*",), "connector:read", ActionKind.READ, ConnectionHistory,
           capability="connectors"),
)

EXECUTORS: Dict[str, Callable] = {
    "connectors.list_sources": list_sources,
    "connectors.sync_history": sync_history,
    "connectors.quality_checks": quality_checks,
}

RESOLVERS: Dict[str, Callable] = {
    "connectors.list_sources": _r("app.api.connectors", "list_connections"),
    "connectors.sync_history": _r("app.api.connectors", "get_sync_history"),
    "connectors.quality_checks": _r("app.api.connectors", "get_quality_checks"),
}

PREVIEWERS: Dict[str, Callable] = {}
