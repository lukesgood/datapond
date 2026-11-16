"""Every route an application serves, flattened — the one place that walks `app.routes`.

From FastAPI 0.137 an included router stays one `_IncludedRouter` entry in `app.routes`
instead of being copied in route by route, so a plain walk saw a few dozen entries and
none of the API. `fastapi.routing.iter_route_contexts` yields one `RouteContext` per
served route, with the full path and the router-level dependencies combined into its
`dependant`. Older FastAPI flattens on include, and `app.routes` already is the list.

Each route comes back as a `ServedRoute`: attributes forward to the effective route,
`methods` is always a set (a mount has none), and `is_api` says whether it is an HTTP
endpoint declared with FastAPI (`APIRoute`) — `isinstance` cannot see through the
context. The API surface, the gateway OpenAPI and every route inventory test read routes
through here, so a FastAPI change to this shape breaks one module, not twenty walkers.
"""
from typing import Any, List

from fastapi.routing import APIRoute

try:
    from fastapi.routing import iter_route_contexts as _iter_route_contexts
except ImportError:          # FastAPI < 0.137: include_router copies routes into app.routes
    _iter_route_contexts = None


class ServedRoute:
    __slots__ = ("_route", "is_api")

    def __init__(self, route: Any, is_api: bool):
        self._route = route
        self.is_api = is_api

    def __getattr__(self, name: str) -> Any:
        return getattr(self._route, name)

    @property
    def methods(self) -> set:
        return set(getattr(self._route, "methods", None) or ())

    def __repr__(self) -> str:
        return f"ServedRoute({getattr(self._route, 'path', '?')!r}, api={self.is_api})"


def app_routes(app: Any) -> List[ServedRoute]:
    routes = list(app.routes)
    if _iter_route_contexts is None:
        return [ServedRoute(r, isinstance(r, APIRoute)) for r in routes]
    return [ServedRoute(c, isinstance(c.original_route, APIRoute)) for c in _iter_route_contexts(routes)]


def api_routes(app: Any) -> List[ServedRoute]:
    """Only the HTTP endpoints this application declares (no mounts, docs, websockets)."""
    return [r for r in app_routes(app) if r.is_api]
