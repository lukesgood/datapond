"""The action registry as MCP tools: read actions only, this caller's only.

Names are action ids with dots replaced by underscores. The specification does not
forbid a dotted name, but clients and gateways commonly validate one against
^[a-zA-Z0-9_-]{1,64}$, and a name outside a model's tool-spec constraints fails at
invocation rather than at registration — the worst place to find out.

The map is built from every action, not only the exposed ones, so that a write
action's name resolves to a real id and the server refuses it explicitly by kind.
"""
from typing import Dict, Iterable, List, Mapping, Optional

from app.chat.actions import REGISTRY, Action, ActionKind, actions_for


def mcp_name(action_id: str) -> str:
    return action_id.replace(".", "_")


def _build_name_map() -> Dict[str, str]:
    """One entry per action id, keyed by its MCP name.

    A collision here (two ids whose dots/underscores trade places, e.g. `a.b_c`
    and `a_b.c`) would make one tool name silently resolve to the wrong action —
    worse than the duplicate-id case app/chat/analysis/__init__.py already guards
    at import, since a READ name could come to resolve to a write action. So this
    raises at import too, the same way: structurally impossible, not merely
    caught by a test.
    """
    ids_by_name: Dict[str, List[str]] = {}
    for a in REGISTRY.values():
        ids_by_name.setdefault(mcp_name(a.id), []).append(a.id)
    collisions = {name: ids for name, ids in ids_by_name.items() if len(ids) > 1}
    if collisions:
        raise RuntimeError(f"colliding MCP tool names across action ids: {collisions}")
    return {name: ids[0] for name, ids in ids_by_name.items()}


_BY_MCP_NAME: Dict[str, str] = _build_name_map()


def action_id_for(name: str) -> Optional[str]:
    """The id for a tool name, whatever the action's kind — including a write
    action's. This resolves every registered name because `read_action_id_for`
    below is built on it (a READ id is still an id); the server does not use this
    function to distinguish "no such tool" from "that tool is a write action" in
    its own refusal — `server.py`'s `_unknown()` deliberately answers both, and an
    unauthorized tool, identically, so a call cannot be used to enumerate a
    deployment's components or a caller's own missing scopes. `name` comes off the
    wire as JSON, so a client may legally send a list or dict here; match
    resolve()'s guard."""
    if not isinstance(name, str):
        return None
    return _BY_MCP_NAME.get(name)


def read_action_id_for(name: str) -> Optional[str]:
    """The id for a tool name, only if it names a READ action.

    This is the lookup a dispatcher should reach for by reflex: `action_id_for`
    stays permissive so a write action's id can still be reported by name in a
    refusal, but nothing should resolve, authorize and execute through it.
    """
    action_id = action_id_for(name)
    if action_id is None:
        return None
    action = REGISTRY.get(action_id)
    if action is None or action.kind is not ActionKind.READ:
        return None
    return action_id


def exposed_actions(permissions: Iterable[str],
                    capabilities: Optional[Mapping] = None) -> List[Action]:
    """READ actions this caller may use on this deployment.

    `actions_for` already applies the permission, page and capability filters; page is
    "*" because MCP has no page — a tool is not on a screen.
    """
    return [a for a in actions_for(permissions, "*", capabilities)
            if a.kind is ActionKind.READ]


def descriptors(permissions: Iterable[str],
                capabilities: Optional[Mapping] = None) -> List[dict]:
    """What `tools/list` returns: a name, a description, a JSON Schema.

    Nothing else crosses — no permission names, no capability keys, no routes. What the
    caller cannot see, they cannot be talked into using.
    """
    out = []
    for action in exposed_actions(permissions, capabilities):
        schema = action.params.model_json_schema()
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        schema["additionalProperties"] = False
        schema.pop("title", None)
        out.append({
            "name": mcp_name(action.id),
            "description": action.description,
            "inputSchema": schema,
        })
    return out
