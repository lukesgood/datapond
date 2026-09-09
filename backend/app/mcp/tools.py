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


_BY_MCP_NAME: Dict[str, str] = {mcp_name(a.id): a.id for a in REGISTRY.values()}


def action_id_for(name: str) -> Optional[str]:
    return _BY_MCP_NAME.get(name)


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
