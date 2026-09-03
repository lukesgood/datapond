"""What a conversational assistant is allowed to propose.

See docs/superpowers/specs/2026-08-25-conversational-actions-design.md.

The model never composes a request. It selects an `id` from this registry and supplies
parameters validated against that action's model. An id outside the registry is
refused before anything else happens, so catalog content — a column named
`-- ignore prior instructions` is a legal identifier — cannot become an instruction.

The spec calls for `params_schema: dict`. Parameters are declared as pydantic models
instead and the JSON Schema is derived from them: one source of truth, validation and
schema generation that cannot drift apart, and no new dependency.

Pure: no I/O, no database, no model calls. Registration of what each action *does*
lives with the action's own module; this is the vocabulary and the gate.
"""
from dataclasses import dataclass
from enum import Enum
from typing import (Any, Callable, Dict, Iterable, List, Mapping, Optional,
                    Sequence, Tuple, Type)

from pydantic import BaseModel, ValidationError


class UnknownAction(Exception):
    """An id that is not in the registry. Never surfaced to the model as a hint."""


class InvalidParams(Exception):
    """Parameters that do not match the action's declared shape."""


class ActionKind(str, Enum):
    READ = "read"                # nothing changes; no approval
    CREATE = "create"            # preview, then explicit approval
    MUTATE = "mutate"            # edits existing state; approval
    DESTRUCTIVE = "destructive"  # specified in the design, not built in v1


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    description: str             # what the model reads to decide
    pages: Tuple[str, ...]       # ("*",) for every page
    permission: str
    kind: ActionKind
    params: Type[BaseModel]
    # The /api/capabilities key this action needs, or None for the Portable Core.
    # Enforced twice, like `permission`: filtered out of the model's tool list here,
    # rechecked server-side in gate._authorize. Fail-closed — see capability_on.
    capability: Optional[str] = None
    preview: Optional[Callable] = None   # (params, user) -> dict, server-side
    execute: Optional[Callable] = None   # (params, user) -> dict


# ── Parameter shapes ──────────────────────────────────────────────────────────
# `extra="forbid"` on every one: a field the model invented is a sign it
# misunderstood, and dropping it silently hides that.

class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ── The v1 catalogue ──────────────────────────────────────────────────────────
# Deliberately absent: anything that deletes, connector sync, settings and governance
# writes. Those need the destructive gate the design specifies and v1 does not build;
# shipping the actions against the weaker gate is the pairing to avoid.
#
# Registration of what each action *does* lives with the action's own module, under
# app/chat/analysis/ — one module per domain. This module owns the vocabulary only.

def _load_actions():
    """Imported lazily: analysis modules import Action from this module, so a
    top-level import here would be circular."""
    from app.chat.analysis import ACTIONS
    return ACTIONS


_ACTIONS: Sequence[Action] = _load_actions()
REGISTRY: Dict[str, Action] = {a.id: a for a in _ACTIONS}


def resolve(action_id: Any) -> Action:
    """The action for `action_id`, or UnknownAction.

    Rejects anything that is not exactly a registered id — no prefix matching, no
    normalisation. A near-miss is a misunderstanding, not something to guess at.
    """
    if not isinstance(action_id, str) or action_id not in REGISTRY:
        raise UnknownAction(f"No such action: {action_id!r}")
    return REGISTRY[action_id]


def validate_params(action: Action, params: Any) -> dict:
    """Validated, normalised parameters, or InvalidParams."""
    if not isinstance(params, dict):
        raise InvalidParams(
            f"{action.id} expects an object of parameters, got {type(params).__name__}")
    try:
        return action.params.model_validate(params).model_dump()
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in e.errors())
        raise InvalidParams(f"{action.id}: {problems}") from e


def _capability_on(capabilities: Optional[Mapping[str, Any]], key: Optional[str]) -> bool:
    """Fail-closed: no key required is always on; otherwise the map must say exactly
    True. An absent map means this caller could not determine capabilities, which is a
    reason to offer less, never more."""
    if key is None:
        return True
    if not capabilities:
        return False
    return capabilities.get(key) is True


def actions_for(permissions: Iterable[str], page: str = "*",
                capabilities: Optional[Mapping[str, Any]] = None) -> List[Action]:
    """Actions this caller may use, on this page, on this deployment.

    Three filters, one purpose: an action a caller cannot use is not filtered out of a
    list they were shown — they never learn it exists, so the model cannot propose it
    and cannot explain what they are missing.
    """
    held = set(permissions or ())
    return [a for a in _ACTIONS
            if a.permission in held
            and (page == "*" or "*" in a.pages or page in a.pages)
            and _capability_on(capabilities, a.capability)]


def tool_definitions(permissions: Iterable[str], page: str = "*",
                     capabilities: Optional[Mapping[str, Any]] = None) -> List[dict]:
    """The action list as the model sees it: a name, a description, a schema.

    Nothing else crosses — no routes, no callables, no permission or capability names.
    What the model cannot see, it cannot be talked into using.
    """
    out = []
    for action in actions_for(permissions, page, capabilities):
        schema = action.params.model_json_schema()
        schema.setdefault("type", "object")
        schema.setdefault("required", [])
        schema["additionalProperties"] = False
        schema.pop("title", None)
        out.append({
            "name": action.id,
            "description": action.description,
            "input_schema": schema,
        })
    return out
