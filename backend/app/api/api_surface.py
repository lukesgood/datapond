"""What an application can call, read out of the running application.

The API page listed three endpoints because three were typed into it. The AI surface
is fourteen paths. A hand-written list is exactly the drift this codebase has been
removing everywhere else: it is correct on the day it is written and wrong after the
next route lands, and nothing fails when it goes wrong.

So nothing here is restated. The paths come from the router, the permission from the
marker `require_permission` already sets on its guard, the summary from the route's
own docstring, and the request skeleton from the pydantic model the route validates
against.

Scoped to `/api/ai/*` deliberately. The deployment serves 218 paths; the ones an
application integrates against are the knowledge and generation surface, and putting
the operational and administrative routes in front of a developer would bury it.
"""
from typing import Any, Dict, List, Optional

PREFIX = "/api/ai/"

_PLACEHOLDER = {
    "string": "string", "integer": 0, "number": 0, "boolean": False,
    "array": [], "object": {},
}


def example_from_schema(schema: Optional[dict]) -> Optional[dict]:
    """A skeleton request body: required fields, plus optional ones that have a
    default so their real value is visible rather than guessed at.

    Optional fields without a default are omitted — listing every one turns a
    two-field call into a wall, and the point is something a person can edit and send.
    """
    if not schema or not schema.get("properties"):
        return None
    required = set(schema.get("required") or [])
    out: Dict[str, Any] = {}
    for name, prop in schema["properties"].items():
        if name in required:
            out[name] = _PLACEHOLDER.get(prop.get("type"), None)
        elif "default" in prop and prop["default"] is not None:
            out[name] = prop["default"]
    return out


def _permission(route) -> Optional[str]:
    """The permission this route's guard enforces, walking the dependency tree.

    Same marker the route-authorization inventory reads. A route whose gate changes
    reports the change here without anyone editing anything.
    """
    seen = set()

    def walk(dep):
        if id(dep) in seen:
            return None
        seen.add(id(dep))
        marker = getattr(dep.call, "__datapond_authorization__", None)
        if marker:
            return marker
        for sub in dep.dependencies:
            found = walk(sub)
            if found:
                return found
        return None

    return walk(route.dependant)


def _body_schema(route) -> Optional[dict]:
    for field in getattr(route, "body_field", None) and [route.body_field] or []:
        model = getattr(field, "type_", None)
        if model is not None and hasattr(model, "model_json_schema"):
            try:
                return model.model_json_schema()
            except Exception:
                return None
    return None


def build_api_surface(app) -> List[dict]:
    """One entry per (path, method) an application can call."""
    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith(PREFIX) or not hasattr(route, "dependant"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            doc = (getattr(route, "endpoint", None).__doc__ or "").strip()
            out.append({
                "path": path,
                "method": method,
                # First line only: the rest of a docstring is written for whoever
                # maintains the route, not for whoever calls it.
                "summary": doc.split("\n")[0] if doc else "",
                "permission": _permission(route),
                "example": example_from_schema(_body_schema(route)),
            })
    out.sort(key=lambda e: (e["path"], e["method"]))
    return out
