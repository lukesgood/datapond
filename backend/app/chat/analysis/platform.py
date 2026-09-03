"""Reads over the deployment: service health and metrics, system events, storage.

Gated on `service:manage` even though three of the four routes accept any signed-in
user. The assistant answers from every page and narrates rather than displays, so where
the two boundaries disagree it takes the stricter one — design §4.1.
"""
from typing import Callable, Dict, Optional

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class ServiceRef(_Strict):
    service: str


class EventWindow(_Strict):
    hours: int = Field(default=168, ge=1, le=2160)
    limit: int = Field(default=50, ge=1, le=200)
    severity: Optional[str] = None


async def service_health(params: dict, user: dict) -> dict:
    from app.api.services import get_service_health
    return {"health": await get_service_health(service=params["service"])}


async def service_metrics(params: dict, user: dict) -> dict:
    from app.api.services import get_service_metrics
    return {"metrics": await get_service_metrics(service=params["service"])}


async def recent_events(params: dict, user: dict) -> dict:
    from app.api.system_events_routes import list_system_events
    return {"events": await list_system_events(
        severity=params.get("severity"), hours=params["hours"], limit=params["limit"])}


async def storage_overview(params: dict, user: dict) -> dict:
    from app.api.storage import get_storage_overview
    return {"storage": await get_storage_overview()}


ACTIONS = (
    Action("platform.service_health", "Service health",
           "Whether one service is healthy, and what its probes report.",
           ("*",), "service:manage", ActionKind.READ, ServiceRef),
    Action("platform.service_metrics", "Service metrics",
           "Current CPU and memory for one service.",
           ("*",), "service:manage", ActionKind.READ, ServiceRef),
    Action("platform.recent_events", "Recent system events",
           "What happened to this deployment recently — restarts, probe failures, "
           "deploys. Repeats are one row with a count.",
           ("*",), "service:manage", ActionKind.READ, EventWindow),
    Action("storage.overview", "Storage overview",
           "Buckets, object counts and sizes.",
           ("*",), "service:manage", ActionKind.READ, _Strict),
)

EXECUTORS: Dict[str, Callable] = {
    "platform.service_health": service_health,
    "platform.service_metrics": service_metrics,
    "platform.recent_events": recent_events,
    "storage.overview": storage_overview,
}

RESOLVERS: Dict[str, Callable] = {
    "platform.service_health": _r("app.api.services", "get_service_health"),
    "platform.service_metrics": _r("app.api.services", "get_service_metrics"),
    "platform.recent_events": _r("app.api.system_events_routes", "list_system_events"),
    "storage.overview": _r("app.api.storage", "get_storage_overview"),
}

PREVIEWERS: Dict[str, Callable] = {}
