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
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Type

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
    preview: Optional[Callable] = None   # (params, user) -> dict, server-side
    execute: Optional[Callable] = None   # (params, user) -> dict


# ── Parameter shapes ──────────────────────────────────────────────────────────
# `extra="forbid"` on every one: a field the model invented is a sign it
# misunderstood, and dropping it silently hides that.

class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class TableRef(_Strict):
    # `namespace`, not `schema`: the latter shadows a BaseModel attribute, which
    # quietly drops it from the generated JSON Schema's `required` list — and the
    # product's own API already calls these namespaces.
    namespace: str
    table: str


class TableSearch(_Strict):
    query: str


class RelationshipQuery(_Strict):
    table: Optional[str] = None
    days: int = 30


class SqlText(_Strict):
    sql: str


class NaturalQuestion(_Strict):
    question: str


class DashboardSave(_Strict):
    name: str
    sql: str
    chart_type: str = "table"


class CollectionCreate(_Strict):
    name: str
    description: Optional[str] = None


class KnowledgeQuery(_Strict):
    # Required, because SearchRequest.collection and RagRequest.collection are. An
    # optional field here would let the model omit what the API demands, and the call
    # would fail after the user had already been told it was happening.
    collection: str
    query: str


class PolicyQuery(_Strict):
    table: Optional[str] = None


class SpendQuery(_Strict):
    days: int = 30


# ── The v1 catalogue ──────────────────────────────────────────────────────────
# Deliberately absent: anything that deletes, connector sync, settings and governance
# writes. Those need the destructive gate the design specifies and v1 does not build;
# shipping the actions against the weaker gate is the pairing to avoid.

_ACTIONS: Sequence[Action] = (
    Action("catalog.describe_table", "Describe table",
           "Columns, types, and relationships for one table.",
           ("/catalog", "/query"), "catalog:read", ActionKind.READ, TableRef),
    Action("catalog.find_tables", "Find tables",
           "Find tables by name or namespace. Pass plain words only — there is no query syntax, no operators, no field: prefixes.",
           ("*",), "catalog:read", ActionKind.READ, TableSearch),
    Action("catalog.explain_relationships", "Explain relationships",
           "How tables are joined, from observed query history and column naming.",
           ("/catalog",), "catalog:read", ActionKind.READ, RelationshipQuery),

    # Offered everywhere, like catalog.find_tables. These were scoped to /query, so
    # the assistant had no SQL tool on any other page — and the panel is on every
    # page. "What does the data say" does not depend on which screen you are looking
    # at, and the permission gate is what decides who may ask.
    Action("query.generate_sql", "Generate SQL",
           "Turn a question into SQL, checked against the catalog. Does not run it.",
           ("*",), "ai:generate", ActionKind.READ, NaturalQuestion),
    Action("query.explain_plan", "Explain the plan",
           "What a statement will read, and anything worth knowing before running it.",
           ("*",), "query:run", ActionKind.READ, SqlText),
    # Classed CREATE, not READ: Athena bills by bytes scanned, and a query the user
    # did not write can read the wrong table. It gets an approval step.
    Action("query.run", "Run query",
           "Execute a statement and return rows.",
           ("*",), "query:run", ActionKind.CREATE, SqlText),

    Action("dashboard.save", "Save dashboard",
           "Save a statement and its chart as a dashboard.",
           ("/query",), "dashboard:write", ActionKind.CREATE, DashboardSave),

    Action("knowledge.search", "Search knowledge",
           "Retrieve passages from a knowledge collection.",
           ("/knowledge",), "knowledge:read", ActionKind.READ, KnowledgeQuery),
    Action("knowledge.answer_with_citations", "Answer with citations",
           "Answer a question from a collection, with sources.",
           ("/knowledge",), "ai:generate", ActionKind.READ, KnowledgeQuery),
    Action("knowledge.create_collection", "Create collection",
           "Create an empty knowledge collection.",
           ("/knowledge",), "knowledge:write", ActionKind.CREATE, CollectionCreate),

    Action("governance.explain_policy", "Explain policy",
           "Which row filters and column masks apply, and to whom.",
           ("/governance",), "governance:read", ActionKind.READ, PolicyQuery),

    Action("spend.summarize", "Summarise spend",
           "Model usage and cost over a period.",
           ("/ai", "/settings"), "spend:read", ActionKind.READ, SpendQuery),
)

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


def actions_for(permissions: Iterable[str], page: str = "*") -> List[Action]:
    """Actions this caller may use on this page.

    The first of the two permission gates. An action the caller cannot use is not
    filtered out of a list they were shown — they never learn it exists, so the model
    cannot propose it and cannot explain what they are missing.

    `page="*"` lists everything permitted, for callers that are not page-bound.
    """
    held = set(permissions or ())
    return [a for a in _ACTIONS
            if a.permission in held
            and (page == "*" or "*" in a.pages or page in a.pages)]


def tool_definitions(permissions: Iterable[str], page: str = "*") -> List[dict]:
    """The action list as the model sees it: a name, a description, a schema.

    Nothing else crosses — no routes, no callables, no permission names. What the
    model cannot see, it cannot be talked into using.
    """
    out = []
    for action in actions_for(permissions, page):
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
