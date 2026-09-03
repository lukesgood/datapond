# Assistant Analysis Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the assistant read and analysis reach across the product's features, behind a capability gate that stops it offering actions for components a deployment does not run.

**Architecture:** `Action` gains a `capability` field enforced twice — filtered out of the model's tool list at proposal time, rechecked server-side at execution — using one shared predicate that the existing route guards also call. The action catalogue moves from two flat files into one module per domain, each exporting its own actions, executors and resolvers, and ten new read actions plus three composite diagnostics are added as new modules.

**Tech Stack:** Python 3.11, FastAPI, pydantic v2, asyncpg, pytest. Frontend: Next.js/React (one copy change only).

**Spec:** `docs/superpowers/specs/2026-09-03-assistant-analysis-actions-design.md` — read it first; this plan argues from it.

## Global Constraints

- Every new action is `ActionKind.READ`. Nothing in this plan creates, mutates or deletes anything.
- Every new action's `pages` is `("*",)`.
- Every params model subclasses `_Strict` (which sets `extra="forbid"`).
- Action ids are `domain.verb`, lowercase, one dot.
- Capability enforcement is fail-closed: any value other than exactly `True` means off, and an absent capability map means every capability-bound action is dropped.
- Executors call service functions directly, never the app's own HTTP routes.
- `audit.activity_summary` and `governance.pii_summary` must not return actor ids, actor usernames, client addresses, free-text `reason`, or raw `route` strings (a route path can embed a resource id).
- No action may spend model tokens unless its permission is `ai:generate`.
- Existing behaviour of the twelve current actions must not change, except that they gain capabilities.
- Run backend tests with `cd backend && python3 -m pytest <paths> -q`.

---

## File structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/chat/analysis/__init__.py` | Assembles every domain module into `ACTIONS`, `EXECUTORS`, `RESOLVERS`, `PREVIEWERS` |
| `backend/app/chat/analysis/catalog.py` | The three existing catalog actions, moved |
| `backend/app/chat/analysis/query.py` | The three existing query actions, moved |
| `backend/app/chat/analysis/dashboards.py` | `dashboard.save`, moved |
| `backend/app/chat/analysis/knowledge.py` | Three existing knowledge actions, moved; two new reads; one diagnostic |
| `backend/app/chat/analysis/governance.py` | `governance.explain_policy`, moved; two new reads; the PII aggregate |
| `backend/app/chat/analysis/spend.py` | `spend.summarize`, moved; one diagnostic |
| `backend/app/chat/analysis/connectors.py` | Three new reads; one diagnostic |
| `backend/app/chat/analysis/platform.py` | Four new reads (services, system events, storage) |
| `backend/app/chat/analysis/pipelines.py` | One new read |
| `backend/app/chat/analysis/audit.py` | The audit aggregate |
| `backend/app/chat/diagnosis.py` | The `Diagnosis` shape and its builder, shared by the three diagnostics |

**Modified:**

| File | Change |
|---|---|
| `backend/app/component_guard.py` | Gains `capability_on()` and `require_capability()` |
| `backend/main.py` | Imports `require_capability` instead of defining it |
| `backend/app/chat/actions.py` | `Action.capability`; third filter; registry assembled from `analysis/` |
| `backend/app/chat/executors.py` | Becomes a thin re-export of `analysis/`, or is deleted if nothing imports it |
| `backend/app/chat/gate.py` | `_authorize` checks capability |
| `backend/app/api/chat_routes.py` | Passes the capability map; `_system_prompt` copy |
| `frontend/components/chat/assistant-panel.tsx` | Greeting copy |

---

## Task 1: One definition of "is this capability on"

**Files:**
- Modify: `backend/app/component_guard.py`
- Modify: `backend/main.py:354-368` (remove the local `require_capability`, import it)
- Test: `backend/tests/test_component_guard.py`

**Interfaces:**
- Produces: `capability_on(cap_key: str) -> bool` and `require_capability(cap_key: str, label: str) -> Callable[[], None]`, both in `app.component_guard`.

`require_capability` is defined inside `main.py` today, which is the file that assembles the app — nothing else can import it without importing the whole application. Task 2 needs the same answer in the action gate, and a second implementation beside the first is a second answer to one question.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_component_guard.py
"""The capability predicate, shared by the route guards and the action gate.

It lived in main.py, where the only way to reach it was to import the application.
"""
import pytest
from fastapi import HTTPException

from app.component_guard import capability_on, require_capability


def test_capability_on_reads_the_computed_map(monkeypatch):
    monkeypatch.delenv("FEATURE_TRINO", raising=False)
    monkeypatch.delenv("FEATURE_POLARIS", raising=False)
    monkeypatch.delenv("FEATURE_GLUE", raising=False)
    assert capability_on("catalog") is False

    monkeypatch.setenv("FEATURE_TRINO", "true")
    assert capability_on("catalog") is True


def test_capability_on_is_false_for_a_name_that_does_not_exist():
    """Fail-closed. A typo must not read as 'on'."""
    assert capability_on("no_such_capability") is False


def test_capability_on_is_false_for_a_non_boolean_value(monkeypatch):
    """compute_capabilities also returns strings (query_engine, profile_id). Only an
    exact True counts, so a truthy string can never open a gate."""
    assert capability_on("query_engine") is False


def test_require_capability_raises_503_when_off(monkeypatch):
    monkeypatch.delenv("FEATURE_TRINO", raising=False)
    monkeypatch.delenv("FEATURE_ATHENA", raising=False)
    guard = require_capability("query", "SQL Lab")
    with pytest.raises(HTTPException) as e:
        guard()
    assert e.value.status_code == 503
    assert "SQL Lab" in e.value.detail


def test_require_capability_passes_when_on(monkeypatch):
    monkeypatch.setenv("FEATURE_TRINO", "true")
    assert require_capability("query", "SQL Lab")() is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_component_guard.py -q`
Expected: FAIL — `ImportError: cannot import name 'capability_on'`.

- [ ] **Step 3: Add both to `component_guard.py`**

Append to `backend/app/component_guard.py`:

```python
def capability_on(cap_key: str) -> bool:
    """Whether `cap_key` is enabled, as /api/capabilities computes it.

    Exactly `True` counts. compute_capabilities also returns strings — query_engine,
    profile_id — and a truthy string must never open a gate. An unknown key is False,
    so a typo hides a feature rather than exposing one (design rule 3).
    """
    return compute_capabilities(os.environ).get(cap_key) is True


def require_capability(cap_key: str, label: str):
    """FastAPI dependency: 503 unless `cap_key` is on.

    Unlike require_component (a single FEATURE_* flag), catalog / query / connectors
    are OR-composed capabilities (e.g. ``trino or polaris or glue``). Gating on the
    computed boolean keeps this server-side guard in exact agreement with the
    /api/capabilities the UI gates on.
    """
    def _guard() -> None:
        if not capability_on(cap_key):
            raise HTTPException(
                status_code=503,
                detail=f"{label} is not enabled on this deployment profile.",
            )
    return _guard
```

Add the import at the top of the file, beside the existing `from app.capabilities import _feat`:

```python
from app.capabilities import _feat, compute_capabilities
```

- [ ] **Step 4: Run the test**

Run: `cd backend && python3 -m pytest tests/test_component_guard.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Delete the copy in `main.py` and import instead**

Remove the `def require_capability(...)` block at `backend/main.py:354-368` entirely. Add `require_capability` to the existing component_guard import in `main.py` (search for `require_component` to find it; if `main.py` does not already import from `app.component_guard`, add `from app.component_guard import require_capability`).

Leave every `dependencies=[Depends(require_capability(...))]` call site untouched — the name resolves to the imported function now.

- [ ] **Step 6: Prove the routers still gate**

Run: `cd backend && python3 -m pytest tests/test_app_imports.py tests/test_capabilities.py -q`
Expected: PASS. (`test_app_imports.py` imports the whole app; a broken import here fails it.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/component_guard.py backend/main.py backend/tests/test_component_guard.py
git commit -m "refactor(capabilities): one predicate for 'is this capability on'

require_capability was defined in main.py, so the only way to ask the question
was to import the application. The action gate needs the same answer, and a
second implementation beside the first is a second answer.

capability_on() is the predicate; require_capability() is the dependency over
it. Both fail closed: exactly True counts, an unknown key is False, and a
truthy string (query_engine, profile_id) never opens a gate."
```

---

## Task 2: Capability, gated twice

**Files:**
- Modify: `backend/app/chat/actions.py` (the `Action` dataclass, `actions_for`, `tool_definitions`)
- Modify: `backend/app/chat/gate.py` (`_authorize`)
- Modify: `backend/app/api/chat_routes.py` (`available_actions`, `chat`)
- Test: `backend/tests/test_chat_capability_gate.py`

**Interfaces:**
- Consumes: `capability_on(cap_key) -> bool` from Task 1.
- Produces: `Action.capability: Optional[str]`; `actions_for(permissions, page="*", capabilities=None)`; `tool_definitions(permissions, page="*", capabilities=None)`. `capabilities` is `Optional[Mapping[str, Any]]`.

This task does the field, both filters and the call sites together on purpose. Adding the field and the proposal filter without wiring the map would drop every capability-bound action from a working deployment — a broken intermediate state is not a smaller change.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_capability_gate.py
"""The third gate: an action for a component this deployment does not run.

Permission answers "may this person", capability answers "does this deployment have
it". Before this, `actions_for` asked only the first, so a Portable Core install with
no query engine still offered the model catalog.describe_table — which it proposed,
and which then failed at the route. The model cannot explain that, and the user reads
it as the assistant being broken.
"""
import pytest

from app.chat.actions import (REGISTRY, Action, ActionKind, actions_for,
                              tool_definitions)
from app.chat import gate
from app.chat.gate import ActionRefused


ALL = {a.permission for a in REGISTRY.values()}


def test_an_action_whose_capability_is_off_is_not_offered():
    off = {"catalog": False, "query": False}
    ids = {a.id for a in actions_for(ALL, "*", off)}
    assert "catalog.describe_table" not in ids
    assert "query.run" not in ids
    # Core actions carry no capability and are unaffected.
    assert "knowledge.search" in ids


def test_an_action_whose_capability_is_on_is_offered():
    ids = {a.id for a in actions_for(ALL, "*", {"catalog": True, "query": True})}
    assert "catalog.describe_table" in ids
    assert "query.run" in ids


def test_no_capability_map_drops_every_capability_bound_action():
    """Fail-closed. A caller that could not determine capabilities loses the gated
    actions rather than gaining them."""
    ids = {a.id for a in actions_for(ALL, "*", None)}
    assert not [i for i in ids if REGISTRY[i].capability]
    assert "knowledge.search" in ids


@pytest.mark.parametrize("value", [False, None, "true", 1, {}])
def test_only_an_exact_true_counts(value):
    ids = {a.id for a in actions_for(ALL, "*", {"catalog": value})}
    assert "catalog.describe_table" not in ids


def test_tool_definitions_hides_them_from_the_model():
    names = {t["name"] for t in tool_definitions(ALL, "*", {"catalog": False})}
    assert "catalog.describe_table" not in names


@pytest.mark.asyncio
async def test_execution_refuses_a_forged_id_for_a_disabled_capability(monkeypatch):
    """The second gate. Not seeing an action is UX; being refused is the control."""
    monkeypatch.setattr(gate, "capability_on", lambda key: False)

    class _Store:
        async def record_audit(self, *a, **k):
            return None

    user = {"id": "u1", "permissions": sorted(ALL)}
    with pytest.raises(ActionRefused):
        await gate._authorize(REGISTRY["catalog.describe_table"], user, "*",
                              _Store(), stage="propose")


def test_every_capability_named_in_the_registry_exists():
    """A capability name that does not exist fails closed, which means a typo hides an
    action forever and nothing ever says so. This is the only thing that would."""
    from app.capabilities import compute_capabilities
    known = set(compute_capabilities({}))
    unknown = sorted({a.capability for a in REGISTRY.values()
                      if a.capability and a.capability not in known})
    assert not unknown, f"capabilities not in compute_capabilities(): {unknown}"


def test_every_permission_named_in_the_registry_exists():
    from app.permissions import ALL_PERMISSIONS
    unknown = sorted({a.permission for a in REGISTRY.values()
                      if a.permission not in ALL_PERMISSIONS})
    assert not unknown, f"permissions not in ALL_PERMISSIONS: {unknown}"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_capability_gate.py -q`
Expected: FAIL — `actions_for() takes from 1 to 2 positional arguments but 3 were given`.

- [ ] **Step 3: Add the field**

In `backend/app/chat/actions.py`, add to the `Action` dataclass after `permission`:

```python
    # The /api/capabilities key this action needs, or None for the Portable Core.
    # Enforced twice, like `permission`: filtered out of the model's tool list here,
    # rechecked server-side in gate._authorize. Fail-closed — see capability_on.
    capability: Optional[str] = None
```

`capability` must come after every other field that has no default, and before `preview`/`execute`. Because `Action` is constructed positionally throughout `_ACTIONS`, add it as a keyword argument at each call site instead of a positional one.

- [ ] **Step 4: Filter on it**

Replace `actions_for` and `tool_definitions` in `backend/app/chat/actions.py`:

```python
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
```

Add `Mapping` to the `typing` import at the top of the file.

- [ ] **Step 5: Give the existing seven their capabilities**

In `_ACTIONS`, add `capability=` to exactly these, leaving every other action untouched:

```python
    Action("catalog.describe_table", ..., capability="catalog"),
    Action("catalog.find_tables", ..., capability="catalog"),
    Action("catalog.explain_relationships", ..., capability="catalog"),
    Action("query.generate_sql", ..., capability="query"),
    Action("query.explain_plan", ..., capability="query"),
    Action("query.run", ..., capability="query"),
    Action("dashboard.save", ..., capability="dashboards"),
```

- [ ] **Step 6: Add the execution-time check**

In `backend/app/chat/gate.py`, import the predicate at the top:

```python
from app.component_guard import capability_on
```

and extend `_authorize` (it currently only checks permission):

```python
async def _authorize(action: Action, user: dict, page: str, store: InvocationStore,
                     stage: str) -> None:
    if action.permission not in _held_permissions(user):
        await _audit(store, "chat_action_refused", user,
                     action=action.id, stage=stage, reason="permission",
                     required=action.permission)
        raise ActionRefused(
            f"'{action.permission}' permission required to {action.label.lower()}.")

    # The map a client sent is never the one that decides. Recomputed here from the
    # server's own environment, by the same predicate the route guards use.
    if action.capability and not capability_on(action.capability):
        await _audit(store, "chat_action_refused", user,
                     action=action.id, stage=stage, reason="capability",
                     required=action.capability)
        raise ActionRefused(
            f"{action.label} needs a component this deployment does not run.")
```

- [ ] **Step 7: Pass the map at the call sites**

In `backend/app/api/chat_routes.py`, add the import:

```python
from app.capabilities import compute_capabilities
```

and a helper beside `_held`:

```python
def _caps() -> dict:
    """This deployment's capabilities, computed here rather than taken from the
    client — the panel's copy is for rendering, not for deciding."""
    return compute_capabilities(os.environ)
```

(`os` is already imported; if it is not, add `import os`.)

Then pass it in both places:

```python
    return {"page": page, "actions": tool_definitions(_held(user), page, _caps())}
```

```python
    tools = tool_definitions(_held(user), request.page, _caps())
```

- [ ] **Step 8: Run the whole chat suite**

Run: `cd backend && python3 -m pytest tests/test_chat_capability_gate.py tests/test_chat_actions.py tests/test_chat_gate.py tests/test_chat_executors.py tests/test_chat_executor_wiring.py tests/test_chat_human_only.py tests/test_chat_read_chaining.py tests/test_chat_user_proposal.py -q`
Expected: PASS. Existing tests that call `actions_for(perms, page)` still pass — the new parameter defaults, and the actions they assert on are the capability-free ones or they pass a map.

If an existing test asserts a catalog or query action is offered without passing a map, it now fails — that is the fail-closed rule working. Fix it by passing `{"catalog": True, "query": True, "dashboards": True}`, and say so in the commit.

- [ ] **Step 9: Commit**

```bash
git add backend/app/chat/actions.py backend/app/chat/gate.py backend/app/api/chat_routes.py backend/tests/test_chat_capability_gate.py
git commit -m "feat(assistant): gate actions on capability, the way permission is gated

actions_for filtered on permission and page but not on whether the deployment
runs the component. On the Portable Core default — no Trino, no Athena — the
model was still offered catalog.describe_table, proposed it, and it failed at
the route. Nothing in that sequence is explainable to the person watching.

Two gates for two reasons: filtered from the tool list so the model cannot
propose it, rechecked in _authorize so a forged id is refused. Fail-closed
throughout — exactly True counts, and no map at all means no gated actions."
```

---
## Task 3: One module per domain

**Files:**
- Create: `backend/app/chat/analysis/__init__.py`, `catalog.py`, `query.py`, `dashboards.py`, `knowledge.py`, `governance.py`, `spend.py`
- Modify: `backend/app/chat/actions.py` (assemble the registry from `analysis/`)
- Modify: `backend/app/chat/executors.py` (re-export, or delete)
- Test: `backend/tests/test_chat_analysis_assembly.py`

**Interfaces:**
- Produces: every module in `app.chat.analysis` exports four names —
  `ACTIONS: tuple[Action, ...]`, `EXECUTORS: dict[str, Callable]`,
  `RESOLVERS: dict[str, Callable]`, `PREVIEWERS: dict[str, Callable]`.
  `app.chat.analysis` re-exports the merged four.
- Consumes: `Action`, `ActionKind`, `_Strict` from `app.chat.actions`.

No behaviour changes. `actions.py` already says registration of what an action does
"lives with the action's own module" while `executors.py` holds all twelve in one file;
every later task adds a module, and doing the move first makes each of them a small diff
instead of another append to a file that is already the wrong shape.

Move, do not rewrite. Cut each function and `Action(...)` line into its domain module
unchanged, including its comments.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_analysis_assembly.py
"""The registry is assembled from domain modules, and stays whole while it moves.

The move is mechanical, so the test that matters is the one asserting nothing was
dropped on the way: the same ids, each with an executor, each executor with a resolver.
"""
from app.chat import analysis
from app.chat.actions import REGISTRY


def test_every_action_comes_from_a_domain_module():
    assert {a.id for a in analysis.ACTIONS} == set(REGISTRY)


def test_every_action_has_an_executor():
    missing = sorted(set(REGISTRY) - set(analysis.EXECUTORS))
    assert not missing, f"actions with no executor: {missing}"


def test_every_executor_has_a_resolver():
    """RESOLVERS is what test_chat_executor_wiring proves against the real modules —
    an executor with no resolver is one nothing checks the target function of."""
    missing = sorted(set(analysis.EXECUTORS) - set(analysis.RESOLVERS))
    assert not missing, f"executors with no resolver: {missing}"


def test_no_module_declares_an_id_another_module_also_declares():
    ids = [a.id for a in analysis.ACTIONS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate action ids across modules: {dupes}"


def test_every_params_model_forbids_fields_the_model_invented():
    """extra="forbid" everywhere. A field the model made up is a sign it misunderstood,
    and accepting it silently hides that."""
    loose = sorted(a.id for a in analysis.ACTIONS
                   if a.params.model_config.get("extra") != "forbid")
    assert not loose, f"params models accepting extra fields: {loose}"


def test_every_id_is_domain_dot_verb():
    bad = sorted(a.id for a in analysis.ACTIONS
                 if a.id.count(".") != 1 or a.id != a.id.lower())
    assert not bad, f"ids that are not lowercase domain.verb: {bad}"


def test_the_twelve_that_existed_before_are_all_still_here():
    """Named literally. A move that silently drops one would otherwise pass every
    other test in this file."""
    assert {
        "catalog.describe_table", "catalog.find_tables", "catalog.explain_relationships",
        "query.generate_sql", "query.explain_plan", "query.run",
        "dashboard.save",
        "knowledge.search", "knowledge.answer_with_citations",
        "knowledge.create_collection",
        "governance.explain_policy", "spend.summarize",
    } <= set(REGISTRY)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_analysis_assembly.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis'`.

- [ ] **Step 3: Create one domain module, as the pattern for the rest**

`backend/app/chat/analysis/catalog.py`:

```python
"""Catalog actions: what tables exist and how they relate.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
from typing import Callable, Dict, Optional

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


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


# Move these three verbatim from executors.py — bodies and comments unchanged:
#   describe_table          executors.py:24-37
#   find_tables             executors.py:39-69
#   explain_relationships   executors.py:71-81
# Verify the line numbers against the file before cutting; a move that also edits is
# a move nothing can review.


ACTIONS = (
    Action("catalog.describe_table", "Describe table",
           "Columns, types, and relationships for one table.",
           ("/catalog", "/query"), "catalog:read", ActionKind.READ, TableRef,
           capability="catalog"),
    Action("catalog.find_tables", "Find tables",
           "Find tables by name or namespace. Pass plain words only — there is no "
           "query syntax, no operators, no field: prefixes.",
           ("*",), "catalog:read", ActionKind.READ, TableSearch,
           capability="catalog"),
    Action("catalog.explain_relationships", "Explain relationships",
           "How tables are joined, from observed query history and column naming.",
           ("/catalog",), "catalog:read", ActionKind.READ, RelationshipQuery,
           capability="catalog"),
)

EXECUTORS: Dict[str, Callable] = {
    "catalog.describe_table": describe_table,
    "catalog.find_tables": find_tables,
    "catalog.explain_relationships": explain_relationships,
}

RESOLVERS: Dict[str, Callable] = {
    "catalog.describe_table": _r("app.api.catalog_backend", "get_catalog_reader"),
    "catalog.find_tables": _r("app.api.catalog_backend", "get_catalog_reader"),
    "catalog.explain_relationships": _r("app.api.catalog_graph", "build_graph"),
}

PREVIEWERS: Dict[str, Callable] = {}
```

`_r` comes from a module of its own rather than being copied into ten files:

```python
# backend/app/chat/analysis/_resolve.py
"""Late resolution of the function an executor reaches for.

Imported at call time, not at module import: the chat package must not pull the whole
API surface in just to declare what it can do. `test_chat_executor_wiring` calls every
resolver, so a renamed or moved target fails a test rather than a user's request.
"""


def _r(module: str, name: str):
    def _resolve():
        import importlib
        return getattr(importlib.import_module(module), name)
    return _resolve
```

- [ ] **Step 4: Move the other five domains the same way**

`query.py` (`SqlText`, `NaturalQuestion`; `generate_sql`, `explain_plan`, `run_query`,
`preview_query_run`, `qualify_for_preview`; `PREVIEWERS = {"query.run": preview_query_run}`),
`dashboards.py` (`DashboardSave`; `save_dashboard`, `preview_dashboard_save`,
`build_dashboard_create`), `knowledge.py` (`CollectionCreate`, `KnowledgeQuery`;
`search_knowledge`, `answer_with_citations`, `create_collection`,
`preview_create_collection`, `build_search_request`, `build_rag_request`,
`_existing_collections`), `governance.py` (`PolicyQuery`; `explain_policy`),
`spend.py` (`SpendQuery`; `summarize_spend`).

Carry `capability="query"` on the three query actions and `capability="dashboards"` on
`dashboard.save`, from Task 2.

- [ ] **Step 5: Assemble**

`backend/app/chat/analysis/__init__.py`:

```python
"""Every domain module, merged.

Order is declaration order and nothing depends on it. A duplicate id is a programming
error, not a precedence question, so it raises here rather than letting one module
quietly win — tests/test_chat_analysis_assembly.py pins that.
"""
from typing import Callable, Dict, Tuple

from app.chat.actions import Action
from app.chat.analysis import (catalog, dashboards, governance, knowledge, query,
                               spend)

_MODULES = (catalog, query, dashboards, knowledge, governance, spend)

ACTIONS: Tuple[Action, ...] = tuple(a for m in _MODULES for a in m.ACTIONS)

_ids = [a.id for a in ACTIONS]
_dupes = sorted({i for i in _ids if _ids.count(i) > 1})
if _dupes:
    raise RuntimeError(f"duplicate action ids across analysis modules: {_dupes}")

EXECUTORS: Dict[str, Callable] = {k: v for m in _MODULES for k, v in m.EXECUTORS.items()}
RESOLVERS: Dict[str, Callable] = {k: v for m in _MODULES for k, v in m.RESOLVERS.items()}
PREVIEWERS: Dict[str, Callable] = {k: v for m in _MODULES for k, v in m.PREVIEWERS.items()}
```

In `backend/app/chat/actions.py`, replace the `_ACTIONS = (...)` literal with:

```python
def _load_actions():
    """Imported lazily: analysis modules import Action from this module, so a
    top-level import here would be circular."""
    from app.chat.analysis import ACTIONS
    return ACTIONS


_ACTIONS: Sequence[Action] = _load_actions()
REGISTRY: Dict[str, Action] = {a.id: a for a in _ACTIONS}
```

Keep `_Strict` in `actions.py` — the domain modules import it.

Replace the body of `backend/app/chat/executors.py` with a re-export so existing
importers keep working:

```python
"""Kept as the import path the routes already use. The implementations moved to
app/chat/analysis/, one module per domain — see that package's __init__."""
from app.chat.analysis import EXECUTORS, PREVIEWERS, RESOLVERS  # noqa: F401
```

- [ ] **Step 6: Run every chat test**

Run: `cd backend && python3 -m pytest tests/test_chat_analysis_assembly.py tests/test_chat_actions.py tests/test_chat_gate.py tests/test_chat_executors.py tests/test_chat_executor_wiring.py tests/test_chat_capability_gate.py tests/test_chat_human_only.py tests/test_chat_read_chaining.py tests/test_chat_user_proposal.py -q`
Expected: PASS, with no test changed. A move that changes behaviour shows up here.

- [ ] **Step 7: Commit**

```bash
git add backend/app/chat backend/tests/test_chat_analysis_assembly.py
git commit -m "refactor(assistant): one module per domain, declaration beside implementation

actions.py has always said that registration of what an action does lives with
the action's own module, while executors.py held all twelve in one 318-line
file. Ten more actions are coming; adding them to that file would leave two
conventions in one registry.

Nothing changes but where the code sits — the same ids, executors and
resolvers, asserted whole by the assembly test."
```

---

## Task 4: Connector reads

**Files:**
- Create: `backend/app/chat/analysis/connectors.py`
- Modify: `backend/app/chat/analysis/__init__.py` (add to `_MODULES`)
- Test: `backend/tests/test_chat_connector_actions.py`

**Interfaces:**
- Produces: actions `connectors.list_sources`, `connectors.sync_history`, `connectors.quality_checks`.
- Consumes: `_r` from `app.chat.analysis._resolve`; `Action`, `ActionKind`, `_Strict` from `app.chat.actions`.

**The trap to avoid.** These handlers declare FastAPI dependencies as defaults —
`user: dict = Depends(require_user)`. Calling `list_connections()` with no argument
passes a `Depends` object as `user`, and the failure is an `AttributeError` deep inside,
not a `TypeError` at the call. This has already happened once in this codebase. Pass
every such parameter explicitly.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_connector_actions.py
"""Reads over sources: what exists, what ran, what the quality checks found."""
import pytest

from app.chat.analysis import connectors as mod


@pytest.mark.asyncio
async def test_list_sources_passes_the_caller_through(monkeypatch):
    """The handler takes `user` as a Depends default. Called without it, the Depends
    object arrives as the user and the failure surfaces far from here."""
    seen = {}

    async def _fake(user):
        seen["user"] = user
        return [{"id": "c1", "name": "crm"}]

    monkeypatch.setattr("app.api.connectors.list_connections", _fake)
    user = {"id": "u1"}
    out = await mod.list_sources({}, user)
    assert seen["user"] is user
    assert out["sources"] == [{"id": "c1", "name": "crm"}]


@pytest.mark.asyncio
async def test_sync_history_passes_id_limit_and_user(monkeypatch):
    seen = {}

    async def _fake(connection_id, limit=20, user=None):
        seen.update(connection_id=connection_id, limit=limit, user=user)
        return {"sessions": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _fake)
    user = {"id": "u1"}
    await mod.sync_history({"connection_id": "c1", "limit": 5}, user)
    assert seen == {"connection_id": "c1", "limit": 5, "user": user}


@pytest.mark.asyncio
async def test_quality_checks_passes_id_limit_and_user(monkeypatch):
    seen = {}

    async def _fake(connection_id, limit=20, user=None):
        seen.update(connection_id=connection_id, limit=limit, user=user)
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_quality_checks", _fake)
    user = {"id": "u1"}
    await mod.quality_checks({"connection_id": "c1", "limit": 20}, user)
    assert seen == {"connection_id": "c1", "limit": 20, "user": user}


def test_all_three_are_reads_gated_on_the_connectors_capability():
    for action in mod.ACTIONS:
        assert action.kind.value == "read"
        assert action.capability == "connectors"
        assert action.permission == "connector:read"
        assert action.pages == ("*",)


def test_limit_is_bounded():
    """An unbounded limit is a way to pull the whole history into a model prompt."""
    from app.chat.actions import InvalidParams, validate_params
    action = next(a for a in mod.ACTIONS if a.id == "connectors.sync_history")
    with pytest.raises(InvalidParams):
        validate_params(action, {"connection_id": "c1", "limit": 5000})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_connector_actions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis.connectors'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/chat/analysis/connectors.py
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
```

Add `connectors` to `_MODULES` in `backend/app/chat/analysis/__init__.py`.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_connector_actions.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py tests/test_chat_capability_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/connectors.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_connector_actions.py
git commit -m "feat(assistant): read sources, their sync history and their quality checks"
```

---
## Task 5: Platform reads — services, events, storage

**Files:**
- Create: `backend/app/chat/analysis/platform.py`
- Modify: `backend/app/chat/analysis/__init__.py`
- Test: `backend/tests/test_chat_platform_actions.py`

**Interfaces:**
- Produces: `platform.service_health`, `platform.service_metrics`, `platform.recent_events`, `storage.overview`. All `service:manage`, no capability — Services, System and Storage are core.

These four are gated harder than the routes they read: `/services/{s}/health`,
`/services/{s}/metrics` and `/storage/overview` accept any signed-in user today. Spec
§4.1 records the reason and the cost. Do not "fix" the routes here.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_platform_actions.py
"""Reads over the deployment itself: service health, metrics, events, storage."""
import pytest

from app.chat.analysis import platform as mod


@pytest.mark.asyncio
async def test_service_health_passes_the_service_name(monkeypatch):
    seen = {}

    async def _fake(service):
        seen["service"] = service
        return {"status": "healthy"}

    monkeypatch.setattr("app.api.services.get_service_health", _fake)
    out = await mod.service_health({"service": "backend"}, {"id": "u1"})
    assert seen["service"] == "backend"
    assert out["health"] == {"status": "healthy"}


@pytest.mark.asyncio
async def test_recent_events_bounds_the_window_and_the_page(monkeypatch):
    seen = {}

    async def _fake(severity=None, kind=None, source=None, hours=168, limit=200):
        seen.update(hours=hours, limit=limit, severity=severity)
        return {"events": []}

    monkeypatch.setattr("app.api.system_events_routes.list_system_events", _fake)
    await mod.recent_events({"hours": 24, "limit": 50, "severity": None}, {"id": "u1"})
    assert seen == {"hours": 24, "limit": 50, "severity": None}


@pytest.mark.asyncio
async def test_storage_overview_takes_no_parameters(monkeypatch):
    async def _fake():
        return {"buckets": []}

    monkeypatch.setattr("app.api.storage.get_storage_overview", _fake)
    out = await mod.storage_overview({}, {"id": "u1"})
    assert out["storage"] == {"buckets": []}


def test_all_four_are_reads_on_service_manage_with_no_capability():
    for action in mod.ACTIONS:
        assert action.kind.value == "read"
        assert action.permission == "service:manage"
        assert action.capability is None
        assert action.pages == ("*",)


def test_the_event_window_is_bounded():
    from app.chat.actions import InvalidParams, validate_params
    action = next(a for a in mod.ACTIONS if a.id == "platform.recent_events")
    with pytest.raises(InvalidParams):
        validate_params(action, {"hours": 100000})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_platform_actions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis.platform'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/chat/analysis/platform.py
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
```

Add `platform` to `_MODULES`.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_platform_actions.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/platform.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_platform_actions.py
git commit -m "feat(assistant): read service health, metrics, system events and storage"
```

---

## Task 6: Knowledge reads

**Files:**
- Modify: `backend/app/chat/analysis/knowledge.py` (add two actions to the module Task 3 created)
- Test: `backend/tests/test_chat_knowledge_reads.py`

**Interfaces:**
- Produces: `knowledge.list_collections`, `knowledge.collection_composition`. Both `knowledge:read`, no capability.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_knowledge_reads.py
"""What collections exist, and what one of them is made of."""
import pytest

from app.chat.analysis import knowledge as mod


@pytest.mark.asyncio
async def test_list_collections_passes_the_caller_and_bounds_the_page(monkeypatch):
    """Collections are access-filtered by caller. Passing the Depends default instead
    of the user would filter by nothing."""
    seen = {}

    async def _fake(user=None, q=None, limit=None, offset=None):
        seen.update(user=user, q=q, limit=limit)
        return {"collections": []}

    monkeypatch.setattr("app.api.ai_vectors.list_collections", _fake)
    user = {"id": "u1"}
    await mod.list_collections_action({"q": "handbook", "limit": 25}, user)
    assert seen == {"user": user, "q": "handbook", "limit": 25}


@pytest.mark.asyncio
async def test_composition_passes_name_and_user(monkeypatch):
    seen = {}

    async def _fake(name, user=None):
        seen.update(name=name, user=user)
        return {"sources": []}

    monkeypatch.setattr("app.api.ai_vectors.collection_composition", _fake)
    user = {"id": "u1"}
    await mod.collection_composition_action({"collection": "handbook"}, user)
    assert seen == {"name": "handbook", "user": user}


def test_both_are_reads_on_knowledge_read():
    for action_id in ("knowledge.list_collections", "knowledge.collection_composition"):
        action = next(a for a in mod.ACTIONS if a.id == action_id)
        assert action.kind.value == "read"
        assert action.permission == "knowledge:read"
        assert action.capability is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_knowledge_reads.py -q`
Expected: FAIL — `AttributeError: module 'app.chat.analysis.knowledge' has no attribute 'list_collections_action'`.

- [ ] **Step 3: Add to `knowledge.py`**

The executors are named `*_action` because the module already imports functions with
the bare names from `app.api.ai_vectors`, and two things called `list_collections` in
one file is how the wrong one gets called.

```python
class CollectionSearch(_Strict):
    q: Optional[str] = None
    limit: int = Field(default=25, ge=1, le=100)


class CollectionRef(_Strict):
    collection: str


async def list_collections_action(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import list_collections
    return {"collections": await list_collections(
        user=user, q=params.get("q"), limit=params["limit"])}


async def collection_composition_action(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import collection_composition
    return {"composition": await collection_composition(
        name=params["collection"], user=user)}
```

Add to that module's `ACTIONS`:

```python
    Action("knowledge.list_collections", "List collections",
           "Knowledge collections this caller can see, with their sizes and freshness.",
           ("*",), "knowledge:read", ActionKind.READ, CollectionSearch),
    Action("knowledge.collection_composition", "Collection composition",
           "What one collection is built from: sources, chunk counts, last refresh.",
           ("*",), "knowledge:read", ActionKind.READ, CollectionRef),
```

and to its `EXECUTORS` / `RESOLVERS`:

```python
    "knowledge.list_collections": list_collections_action,
    "knowledge.collection_composition": collection_composition_action,
```

```python
    "knowledge.list_collections": _r("app.api.ai_vectors", "list_collections"),
    "knowledge.collection_composition": _r("app.api.ai_vectors", "collection_composition"),
```

Add `Field` and `Optional` to that module's imports if they are not there.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_knowledge_reads.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/knowledge.py backend/tests/test_chat_knowledge_reads.py
git commit -m "feat(assistant): list knowledge collections and read one's composition"
```

---

## Task 7: Governance reads

**Files:**
- Modify: `backend/app/chat/analysis/governance.py`
- Test: `backend/tests/test_chat_governance_reads.py`

**Interfaces:**
- Produces: `governance.policy_coverage`, `governance.summary_stats`. Both `governance:read`, no capability.

`get_governance_stats(db: Session = Depends(get_db))` is synchronous and needs a
session. Use `app.database.connection.get_db_context()`, the context manager that exists
for exactly this — callers outside a request.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_governance_reads.py
"""Policy coverage and the governance summary, for the assistant."""
from contextlib import contextmanager

import pytest

from app.chat.analysis import governance as mod


@pytest.mark.asyncio
async def test_policy_coverage_passes_the_caller(monkeypatch):
    seen = {}

    async def _fake(user=None):
        seen["user"] = user
        return {"covered": 3, "uncovered": 1}

    monkeypatch.setattr("app.api.governance.rls_coverage", _fake)
    user = {"id": "u1"}
    out = await mod.policy_coverage({}, user)
    assert seen["user"] is user
    assert out["coverage"]["covered"] == 3


@pytest.mark.asyncio
async def test_summary_stats_opens_and_closes_a_session(monkeypatch):
    """The handler is sync and takes a Session as a Depends default. Called with no
    session it would receive a Depends object and fail inside SQLAlchemy."""
    closed = {"value": False}

    class _Session:
        pass

    session = _Session()

    @contextmanager
    def _ctx():
        try:
            yield session
        finally:
            closed["value"] = True

    monkeypatch.setattr("app.database.connection.get_db_context", _ctx)
    monkeypatch.setattr("app.api.governance.get_governance_stats",
                        lambda db: {"policies": 4, "seen_db": db})

    out = await mod.summary_stats({}, {"id": "u1"})
    assert out["stats"]["seen_db"] is session
    assert closed["value"] is True


def test_both_are_reads_on_governance_read():
    for action_id in ("governance.policy_coverage", "governance.summary_stats"):
        action = next(a for a in mod.ACTIONS if a.id == action_id)
        assert action.kind.value == "read"
        assert action.permission == "governance:read"
        assert action.capability is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_governance_reads.py -q`
Expected: FAIL — `AttributeError: module 'app.chat.analysis.governance' has no attribute 'policy_coverage'`.

- [ ] **Step 3: Add to `governance.py`**

```python
async def policy_coverage(params: dict, user: dict) -> dict:
    from app.api.governance import rls_coverage
    return {"coverage": await rls_coverage(user=user)}


async def summary_stats(params: dict, user: dict) -> dict:
    """`get_governance_stats` is synchronous and takes a Session. get_db_context is the
    context manager that exists for callers outside a request; without it the Depends
    default arrives as `db` and fails inside SQLAlchemy."""
    from app.api.governance import get_governance_stats
    from app.database.connection import get_db_context
    with get_db_context() as db:
        return {"stats": get_governance_stats(db=db)}
```

Add to `ACTIONS`:

```python
    Action("governance.policy_coverage", "Policy coverage",
           "Which tables have a row-level policy and which have none.",
           ("*",), "governance:read", ActionKind.READ, _Strict),
    Action("governance.summary_stats", "Governance summary",
           "Counts of policies, masked columns and covered tables.",
           ("*",), "governance:read", ActionKind.READ, _Strict),
```

and to `EXECUTORS` / `RESOLVERS`:

```python
    "governance.policy_coverage": policy_coverage,
    "governance.summary_stats": summary_stats,
```

```python
    "governance.policy_coverage": _r("app.api.governance", "rls_coverage"),
    "governance.summary_stats": _r("app.api.governance", "get_governance_stats"),
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_governance_reads.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/governance.py backend/tests/test_chat_governance_reads.py
git commit -m "feat(assistant): read RLS coverage and the governance summary"
```

---

## Task 8: Pipeline runs

**Files:**
- Create: `backend/app/chat/analysis/pipelines.py`
- Modify: `backend/app/chat/analysis/__init__.py`
- Test: `backend/tests/test_chat_pipeline_actions.py`

**Interfaces:**
- Produces: `pipelines.recent_runs` — `pipeline:write`, capability `pipelines`.

`pipeline:write` is the only pipeline permission the vocabulary has; there is no
`pipeline:read`. Gating a read behind it is the closest true statement available, and
inventing a permission is a change to the role matrix that belongs to its own decision.

Transforms is the only add-on that gets an action. Streaming, Notebooks and Experiments
get none — "is it running" is already answered by `platform.service_health`, and this
release labels those preview or experimental.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_pipeline_actions.py
"""Recent runs of one transform pipeline."""
import pytest

from app.chat.analysis import pipelines as mod


@pytest.mark.asyncio
async def test_recent_runs_passes_name_and_limit(monkeypatch):
    seen = {}

    async def _fake(pipeline_name, limit=10):
        seen.update(pipeline_name=pipeline_name, limit=limit)
        return {"runs": []}

    monkeypatch.setattr("app.api.pipelines.get_pipeline_runs", _fake)
    await mod.recent_runs({"pipeline": "daily_rollup", "limit": 5}, {"id": "u1"})
    assert seen == {"pipeline_name": "daily_rollup", "limit": 5}


def test_it_is_a_read_gated_on_the_pipelines_capability():
    action = mod.ACTIONS[0]
    assert action.id == "pipelines.recent_runs"
    assert action.kind.value == "read"
    assert action.capability == "pipelines"
    assert action.permission == "pipeline:write"


def test_only_transforms_among_the_add_ons_has_an_action():
    """Streaming, Notebooks and Experiments deliberately have none — design §4."""
    from app.chat.actions import REGISTRY
    gated = {a.capability for a in REGISTRY.values() if a.capability}
    assert "streaming" not in gated
    assert "notebooks" not in gated
    assert "experiments" not in gated
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_pipeline_actions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis.pipelines'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/chat/analysis/pipelines.py
"""Reads over Transforms. The only add-on with an assistant action — design §4."""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class PipelineRuns(_Strict):
    pipeline: str
    limit: int = Field(default=10, ge=1, le=50)


async def recent_runs(params: dict, user: dict) -> dict:
    from app.api.pipelines import get_pipeline_runs
    return {"runs": await get_pipeline_runs(
        pipeline_name=params["pipeline"], limit=params["limit"])}


ACTIONS = (
    Action("pipelines.recent_runs", "Recent pipeline runs",
           "Execution history for one transform pipeline: when it ran and how it ended.",
           ("*",), "pipeline:write", ActionKind.READ, PipelineRuns,
           capability="pipelines"),
)

EXECUTORS: Dict[str, Callable] = {"pipelines.recent_runs": recent_runs}
RESOLVERS: Dict[str, Callable] = {
    "pipelines.recent_runs": _r("app.api.pipelines", "get_pipeline_runs"),
}
PREVIEWERS: Dict[str, Callable] = {}
```

Add `pipelines` to `_MODULES`.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_pipeline_actions.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/pipelines.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_pipeline_actions.py
git commit -m "feat(assistant): read recent runs of a transform pipeline"
```

---
## Task 9: The diagnosis shape, and the first diagnostic

**Files:**
- Create: `backend/app/chat/diagnosis.py`
- Modify: `backend/app/chat/analysis/knowledge.py`
- Test: `backend/tests/test_chat_diagnosis.py`, `backend/tests/test_chat_knowledge_diagnosis.py`

**Interfaces:**
- Produces: `Diagnosis` builder in `app.chat.diagnosis` —
  `Diagnosis(subject: str)` with `.fact(key, value)`, `.signal(severity, statement, **evidence)`,
  `.skipped(reason)`, and `.done() -> dict` returning
  `{"subject", "facts", "signals", "not_checked"}`. `severity` is `"ok" | "warn" | "bad"`.
- Produces: action `knowledge.diagnose_collection` — `knowledge:read`, no capability.

Thresholds live here, not in the prompt. A threshold in a prompt is a threshold nobody
can test. `not_checked` is not optional: a diagnosis that quietly skips what it could not
reach reads to the model as a clean bill of health, and the model will say so.

- [ ] **Step 1: Write the failing test for the shape**

```python
# backend/tests/test_chat_diagnosis.py
"""The shape every diagnostic returns.

Facts are measured, signals are judged, and not_checked is what was out of reach. The
model narrates all three; it decides none of them.
"""
import pytest

from app.chat.diagnosis import Diagnosis


def test_it_carries_subject_facts_signals_and_gaps():
    d = Diagnosis("collection 'handbook'")
    d.fact("chunks", 412)
    d.signal("warn", "Last refreshed 9 days ago", last_refreshed_at="2026-08-25")
    d.skipped("Quality checks need the connectors add-on, which is off")
    out = d.done()

    assert out["subject"] == "collection 'handbook'"
    assert out["facts"] == {"chunks": 412}
    assert out["signals"] == [{"severity": "warn",
                               "statement": "Last refreshed 9 days ago",
                               "evidence": {"last_refreshed_at": "2026-08-25"}}]
    assert out["not_checked"] == ["Quality checks need the connectors add-on, which is off"]


def test_an_untouched_diagnosis_still_has_every_key():
    """The model reads the keys, not the presence of keys. A missing 'not_checked'
    would be indistinguishable from 'nothing was skipped'."""
    assert Diagnosis("x").done() == {
        "subject": "x", "facts": {}, "signals": [], "not_checked": []}


def test_severity_is_one_of_three_words():
    d = Diagnosis("x")
    with pytest.raises(ValueError):
        d.signal("critical", "…")


def test_signals_keep_the_order_they_were_added():
    d = Diagnosis("x")
    d.signal("ok", "first")
    d.signal("bad", "second")
    assert [s["statement"] for s in d.done()["signals"]] == ["first", "second"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_diagnosis.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.diagnosis'`.

- [ ] **Step 3: Write it**

```python
# backend/app/chat/diagnosis.py
"""One shape for every composite diagnostic.

Three parts, and the split is the point. `facts` are measured. `signals` are judged —
by this server, against thresholds that live in code where a test can reach them, not
in a prompt where nothing can. `not_checked` is what was out of reach.

That last one is not decoration. A diagnosis that silently skips what it could not read
— an add-on that is off, a history table with no rows yet — is indistinguishable to the
model from one that found nothing wrong, and the model will report it as health.
"""
from typing import Any, Dict, List

SEVERITIES = ("ok", "warn", "bad")


class Diagnosis:
    def __init__(self, subject: str) -> None:
        self.subject = subject
        self._facts: Dict[str, Any] = {}
        self._signals: List[dict] = []
        self._not_checked: List[str] = []

    def fact(self, key: str, value: Any) -> "Diagnosis":
        self._facts[key] = value
        return self

    def signal(self, severity: str, statement: str, **evidence: Any) -> "Diagnosis":
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {severity!r}")
        self._signals.append({"severity": severity, "statement": statement,
                              "evidence": evidence})
        return self

    def skipped(self, reason: str) -> "Diagnosis":
        self._not_checked.append(reason)
        return self

    def done(self) -> dict:
        return {"subject": self.subject, "facts": dict(self._facts),
                "signals": list(self._signals), "not_checked": list(self._not_checked)}
```

- [ ] **Step 4: Run it**

Run: `cd backend && python3 -m pytest tests/test_chat_diagnosis.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Write the failing test for the collection diagnostic**

```python
# backend/tests/test_chat_knowledge_diagnosis.py
"""Is this collection still worth querying?

The embedding-model check is why this action exists. A collection embedded with one
model and queried through another degrades retrieval silently: nothing errors, nothing
is logged, and the only symptom is worse answers.
"""
import pytest

from app.chat.analysis import knowledge as mod


class _Conn:
    def __init__(self, row, chunks):
        self._row, self._chunks = row, chunks

    async def fetchrow(self, *a):
        return self._row

    async def fetchval(self, *a):
        return self._chunks


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _install(monkeypatch, row, chunks=100, model="embed"):
    pool = _Pool(_Conn(row, chunks))

    async def _get_pool():
        return pool

    monkeypatch.setattr("app.api.auth._get_pool", _get_pool)
    monkeypatch.setattr("app.api.ai_vectors._embed_model", lambda: model)


@pytest.mark.asyncio
async def test_a_model_mismatch_is_a_bad_signal(monkeypatch):
    _install(monkeypatch, {"embed_model": "titan-v1", "refresh_enabled": True,
                           "refresh_interval_minutes": 60, "last_refreshed_at": None,
                           "last_refresh_status": "ok", "owner_id": "u1"},
             model="titan-v2")
    out = await mod.diagnose_collection({"collection": "handbook"}, {"id": "u1"})
    bad = [s for s in out["signals"] if s["severity"] == "bad"]
    assert any("embed" in s["statement"].lower() for s in bad)
    assert out["facts"]["embed_model"] == "titan-v1"


@pytest.mark.asyncio
async def test_an_empty_collection_is_flagged(monkeypatch):
    _install(monkeypatch, {"embed_model": "embed", "refresh_enabled": False,
                           "refresh_interval_minutes": None, "last_refreshed_at": None,
                           "last_refresh_status": None, "owner_id": "u1"}, chunks=0)
    out = await mod.diagnose_collection({"collection": "handbook"}, {"id": "u1"})
    assert any(s["severity"] == "bad" for s in out["signals"])
    assert out["facts"]["chunks"] == 0


@pytest.mark.asyncio
async def test_a_collection_with_no_schedule_says_so_rather_than_calling_it_stale(monkeypatch):
    """Not scheduled is a choice, not a fault. Reporting it as staleness would train
    people to ignore the staleness signal."""
    _install(monkeypatch, {"embed_model": "embed", "refresh_enabled": False,
                           "refresh_interval_minutes": None, "last_refreshed_at": None,
                           "last_refresh_status": None, "owner_id": "u1"})
    out = await mod.diagnose_collection({"collection": "handbook"}, {"id": "u1"})
    assert any("not scheduled" in r.lower() for r in out["not_checked"])
    assert not any("stale" in s["statement"].lower() for s in out["signals"])


@pytest.mark.asyncio
async def test_an_unknown_collection_is_refused_not_diagnosed(monkeypatch):
    _install(monkeypatch, None)
    with pytest.raises(ValueError):
        await mod.diagnose_collection({"collection": "nope"}, {"id": "u1"})
```

- [ ] **Step 6: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_knowledge_diagnosis.py -q`
Expected: FAIL — `AttributeError: … has no attribute 'diagnose_collection'`.

- [ ] **Step 7: Implement it in `knowledge.py`**

```python
# Stale once it is this many times past its own refresh interval. Two, not one: a tick
# that lands a minute late is not a fault, and a signal that fires on every healthy
# collection is a signal people learn to ignore.
_STALE_INTERVALS = 2


async def diagnose_collection(params: dict, user: dict) -> dict:
    """Is this collection still worth querying?

    Access is the caller's own: the row is read through the same pool the rest of the
    app uses, and a caller who cannot see the collection gets nothing back from
    list_collections either. The diagnosis adds no reach.
    """
    from datetime import datetime, timezone

    from app.api.ai_vectors import _embed_model
    from app.api.auth import _get_pool
    from app.chat.diagnosis import Diagnosis

    name = params["collection"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, embed_model, refresh_enabled, refresh_interval_minutes,
                      last_refreshed_at, last_refresh_status, owner_id
               FROM ai_collections WHERE name = $1""", name)
        if row is None:
            raise ValueError(f"No collection named {name!r}.")
        chunks = await conn.fetchval(
            "SELECT count(*) FROM ai_chunks WHERE collection_id = $1", row["id"])

    d = Diagnosis(f"collection {name!r}")
    d.fact("chunks", chunks)
    d.fact("embed_model", row["embed_model"])
    d.fact("refresh_enabled", bool(row["refresh_enabled"]))
    d.fact("last_refreshed_at", str(row["last_refreshed_at"] or ""))
    d.fact("last_refresh_status", row["last_refresh_status"] or "")

    configured = _embed_model()
    if row["embed_model"] != configured:
        d.signal("bad",
                 "Embedded with a different model than the one queries use now — "
                 "retrieval degrades silently, with nothing logged.",
                 collection_model=row["embed_model"], configured_model=configured)
    else:
        d.signal("ok", "Embedding model matches the configured one.",
                 model=configured)

    if chunks == 0:
        d.signal("bad", "The collection is empty — nothing to retrieve.")

    if not row["refresh_enabled"] or not row["refresh_interval_minutes"]:
        d.skipped("Freshness not checked: the collection is not scheduled to refresh.")
    elif row["last_refreshed_at"] is None:
        d.signal("warn", "Scheduled to refresh but has never refreshed.")
    else:
        age_min = (datetime.now(timezone.utc)
                   - row["last_refreshed_at"]).total_seconds() / 60
        overdue = age_min > row["refresh_interval_minutes"] * _STALE_INTERVALS
        d.signal("warn" if overdue else "ok",
                 "Stale against its own schedule." if overdue
                 else "Refreshed within its schedule.",
                 minutes_since_refresh=int(age_min),
                 interval_minutes=row["refresh_interval_minutes"])

    if row["last_refresh_status"] and row["last_refresh_status"] != "ok":
        d.signal("bad", "The last refresh did not succeed.",
                 status=row["last_refresh_status"])

    return d.done()
```

Register it in that module:

```python
    Action("knowledge.diagnose_collection", "Diagnose collection",
           "Whether one collection is still worth querying: size, freshness against "
           "its own schedule, last refresh outcome, and whether it was embedded with "
           "the model queries use now.",
           ("*",), "knowledge:read", ActionKind.READ, CollectionRef),
```

```python
    "knowledge.diagnose_collection": diagnose_collection,
```

```python
    "knowledge.diagnose_collection": _r("app.api.ai_vectors", "_embed_model"),
```

- [ ] **Step 8: Run every knowledge test**

Run: `cd backend && python3 -m pytest tests/test_chat_knowledge_diagnosis.py tests/test_chat_knowledge_reads.py tests/test_chat_diagnosis.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/chat/diagnosis.py backend/app/chat/analysis/knowledge.py backend/tests/test_chat_diagnosis.py backend/tests/test_chat_knowledge_diagnosis.py
git commit -m "feat(assistant): diagnose a knowledge collection

Facts measured, signals judged server-side against thresholds a test can reach,
and not_checked for what was out of reach — a diagnosis that silently skips
what it could not read is one the model reports as health.

The embedding-model check is the reason this exists: a collection embedded with
one model and queried through another loses retrieval quality with nothing
logged and nothing shown anywhere in the console."
```

---

## Task 10: Diagnose a sync

**Files:**
- Modify: `backend/app/chat/analysis/connectors.py`
- Test: `backend/tests/test_chat_sync_diagnosis.py`

**Interfaces:**
- Produces: `connectors.diagnose_sync` — `connector:read`, capability `connectors`.
- Consumes: `Diagnosis` from `app.chat.diagnosis`; `get_sync_history` and `get_quality_checks` from `app.api.connectors`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_sync_diagnosis.py
"""Why did last night's sync fail? — history and quality checks, read together."""
import pytest

from app.chat.analysis import connectors as mod


def _history(*sessions):
    return {"sessions": list(sessions)}


@pytest.mark.asyncio
async def test_a_failed_last_run_is_a_bad_signal_carrying_its_error(monkeypatch):
    async def _hist(connection_id, limit=20, user=None):
        return _history({"status": "failed", "error": "connection refused",
                         "started_at": "2026-09-02T22:00:00Z", "duration_seconds": 3})

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = await mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"})
    bad = [s for s in out["signals"] if s["severity"] == "bad"]
    assert bad and "connection refused" in str(bad[0]["evidence"])


@pytest.mark.asyncio
async def test_a_tripped_quality_check_is_reported_even_when_the_sync_succeeded(monkeypatch):
    """A green sync that loaded a tenth of the usual rows is the failure that does not
    announce itself."""
    async def _hist(connection_id, limit=20, user=None):
        return _history({"status": "success", "duration_seconds": 40})

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": [{"check": "row_count", "severity": "alert",
                            "detail": "-64% against previous run"}]}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = await mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"})
    assert any(s["severity"] == "bad" for s in out["signals"])


@pytest.mark.asyncio
async def test_no_history_is_recorded_as_not_checked_not_as_health(monkeypatch):
    async def _hist(connection_id, limit=20, user=None):
        return _history()

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = await mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"})
    assert any("never" in r.lower() or "no sync" in r.lower()
               for r in out["not_checked"])
    assert not any(s["severity"] == "ok" for s in out["signals"])
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_sync_diagnosis.py -q`
Expected: FAIL — `AttributeError: … has no attribute 'diagnose_sync'`.

- [ ] **Step 3: Implement it**

Append to `backend/app/chat/analysis/connectors.py`:

```python
_RECENT_RUNS = 10


async def diagnose_sync(params: dict, user: dict) -> dict:
    """Why did this source's last sync go the way it did?

    History and quality checks read together, because the answer is often in the one
    the person was not looking at: a run that ends 'success' having loaded a tenth of
    the usual rows is a failure that does not announce itself.
    """
    from app.api.connectors import get_quality_checks, get_sync_history
    from app.chat.diagnosis import Diagnosis

    cid = params["connection_id"]
    history = await get_sync_history(connection_id=cid, limit=_RECENT_RUNS, user=user)
    quality = await get_quality_checks(connection_id=cid, limit=_RECENT_RUNS, user=user)

    sessions = (history or {}).get("sessions") or []
    checks = (quality or {}).get("checks") or []

    d = Diagnosis(f"source {cid!r}")
    d.fact("runs_examined", len(sessions))
    d.fact("quality_checks_examined", len(checks))

    if not sessions:
        d.skipped("Outcome not checked: this source has no sync runs on record yet.")
    else:
        last = sessions[0]
        d.fact("last_status", last.get("status", ""))
        d.fact("last_started_at", str(last.get("started_at", "")))
        if str(last.get("status", "")).lower() not in ("success", "ok", "completed"):
            d.signal("bad", "The most recent sync did not succeed.",
                     status=last.get("status"), error=last.get("error"))
        else:
            d.signal("ok", "The most recent sync succeeded.",
                     status=last.get("status"))

        durations = [s.get("duration_seconds") for s in sessions
                     if isinstance(s.get("duration_seconds"), (int, float))]
        if len(durations) >= 3:
            recent, earlier = durations[0], sum(durations[1:]) / len(durations[1:])
            # Twice the recent average, and not a rounding artefact on a fast sync.
            if earlier > 0 and recent > earlier * 2 and recent > 30:
                d.signal("warn", "The last run took markedly longer than the ones "
                                 "before it.",
                         last_seconds=recent, previous_average_seconds=round(earlier, 1))
        else:
            d.skipped("Duration trend not checked: fewer than three timed runs on "
                      "record.")

    tripped = [c for c in checks
               if str(c.get("severity", "")).lower() in ("alert", "warn", "warning")]
    if not checks:
        d.skipped("Data quality not checked: no check results recorded for this "
                  "source.")
    elif tripped:
        worst = "bad" if any(str(c.get("severity", "")).lower() == "alert"
                             for c in tripped) else "warn"
        d.signal(worst, "Data quality checks flagged this source's recent loads.",
                 findings=tripped[:5])
    else:
        d.signal("ok", "Data quality checks passed on the recent loads.")

    return d.done()
```

Register:

```python
    Action("connectors.diagnose_sync", "Diagnose sync",
           "Why a source's syncs are going the way they are: last outcome and error, "
           "duration trend, and the quality checks recorded after each load.",
           ("*",), "connector:read", ActionKind.READ, ConnectionRef,
           capability="connectors"),
```

```python
    "connectors.diagnose_sync": diagnose_sync,
```

```python
    "connectors.diagnose_sync": _r("app.api.connectors", "get_sync_history"),
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_sync_diagnosis.py tests/test_chat_connector_actions.py tests/test_chat_analysis_assembly.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/connectors.py backend/tests/test_chat_sync_diagnosis.py
git commit -m "feat(assistant): diagnose a source's syncs, history and quality together"
```

---
## Task 11: Diagnose a change in spend

**Files:**
- Modify: `backend/app/chat/analysis/spend.py`
- Test: `backend/tests/test_chat_spend_diagnosis.py`

**Interfaces:**
- Produces: `spend.diagnose_change` — `spend:read`, no capability.
- Consumes: `spend_report(start_date, end_date)` from `app.api.ai_backends` (the
  date-ranged breakdown by model and key); `Diagnosis` from `app.chat.diagnosis`.

`spend.summarize` answers "what did we spend". This answers "why did it change", and the
distinction that matters is one a single-window summary cannot make: whether the total
moved because of **volume** or because of **unit price**. Someone switching to a costlier
model moves the bill without moving the call count, and the two have completely
different responses.

Actor attribution stays at exactly the level `spend.summarize` already returns — this
action widens no privacy boundary.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_spend_diagnosis.py
"""Why did spend change? Volume or unit price — a single window cannot tell you."""
import pytest

from app.chat.analysis import spend as mod


def _report(rows):
    return {"rows": rows}


def _install(monkeypatch, current, previous):
    calls = []

    async def _fake(start_date=None, end_date=None):
        calls.append((start_date, end_date))
        return current if len(calls) == 1 else previous

    monkeypatch.setattr("app.api.ai_backends.spend_report", _fake)
    return calls


@pytest.mark.asyncio
async def test_a_rise_driven_by_call_count_is_named_as_volume(monkeypatch):
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 20.0, "requests": 200}]),
             previous=_report([{"model": "claude", "spend": 10.0, "requests": 100}]))
    out = await mod.diagnose_change({"days": 7}, {"id": "u1"})
    assert any("volume" in s["statement"].lower() for s in out["signals"])
    assert out["facts"]["current_total"] == 20.0


@pytest.mark.asyncio
async def test_a_rise_at_flat_volume_is_named_as_unit_price(monkeypatch):
    """Same number of calls, twice the bill — someone changed model."""
    _install(monkeypatch,
             current=_report([{"model": "opus", "spend": 20.0, "requests": 100}]),
             previous=_report([{"model": "haiku", "spend": 10.0, "requests": 100}]))
    out = await mod.diagnose_change({"days": 7}, {"id": "u1"})
    assert any("per call" in s["statement"].lower()
               or "unit" in s["statement"].lower() for s in out["signals"])


@pytest.mark.asyncio
async def test_no_change_is_an_ok_signal(monkeypatch):
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 10.0, "requests": 100}]),
             previous=_report([{"model": "claude", "spend": 10.0, "requests": 100}]))
    out = await mod.diagnose_change({"days": 7}, {"id": "u1"})
    assert all(s["severity"] == "ok" for s in out["signals"])


@pytest.mark.asyncio
async def test_an_empty_previous_window_is_not_reported_as_infinite_growth(monkeypatch):
    """A first week of use is not a hundred-percent increase; it is no comparison."""
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 10.0, "requests": 100}]),
             previous=_report([]))
    out = await mod.diagnose_change({"days": 7}, {"id": "u1"})
    assert any("no spend" in r.lower() or "nothing to compare" in r.lower()
               for r in out["not_checked"])
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_spend_diagnosis.py -q`
Expected: FAIL — `AttributeError: … has no attribute 'diagnose_change'`.

- [ ] **Step 3: Implement it**

Append to `backend/app/chat/analysis/spend.py`:

```python
class SpendWindow(_Strict):
    days: int = Field(default=7, ge=1, le=90)


# Below this the movement is noise: a few pennies on a small account is a large
# percentage and no story at all.
_MATERIAL_USD = 1.0
_MATERIAL_FRACTION = 0.15


# `spend_report` returns {"start_date", "end_date", "report": [...]}, and the list under
# "report" is LiteLLM's own payload passed through untouched — its item shape is not
# defined anywhere in this repo and cannot be verified from it. So read it defensively
# and say so when the fields are not there: a total computed from rows whose spend field
# was named something else is zero, and zero reported as fact is worse than "not checked".
def _totals(report: dict) -> tuple:
    rows = (report or {}).get("report") or []
    spend = sum(float(r.get("spend") or 0) for r in rows if isinstance(r, dict))
    requests = sum(int(r.get("requests") or 0) for r in rows if isinstance(r, dict))
    recognised = any(isinstance(r, dict) and "spend" in r for r in rows)
    return spend, requests, rows, recognised


async def diagnose_change(params: dict, user: dict) -> dict:
    """Did spend change, and was it volume or unit price?"""
    from datetime import date, timedelta

    from app.api.ai_backends import spend_report
    from app.chat.diagnosis import Diagnosis

    days = params["days"]
    today = date.today()
    cur_start, cur_end = today - timedelta(days=days), today
    prev_start, prev_end = cur_start - timedelta(days=days), cur_start

    current = await spend_report(start_date=cur_start.isoformat(),
                                 end_date=cur_end.isoformat())
    previous = await spend_report(start_date=prev_start.isoformat(),
                                  end_date=prev_end.isoformat())

    cur_spend, cur_calls, cur_rows, cur_ok = _totals(current)
    prev_spend, prev_calls, _, prev_ok = _totals(previous)

    if cur_rows and not cur_ok:
        d = Diagnosis(f"model spend over the last {days} days against the {days} before")
        d.skipped("Spend not checked: the gateway returned rows this build does not "
                  "recognise — no field named 'spend' on any of them.")
        return d.done()

    d = Diagnosis(f"model spend over the last {days} days against the {days} before")
    d.fact("current_total", round(cur_spend, 4))
    d.fact("previous_total", round(prev_spend, 4))
    d.fact("current_requests", cur_calls)
    d.fact("previous_requests", prev_calls)
    d.fact("by_model", sorted(
        ({"model": r.get("model"), "spend": round(float(r.get("spend") or 0), 4),
          "requests": int(r.get("requests") or 0)} for r in cur_rows),
        key=lambda r: r["spend"], reverse=True)[:10])

    if prev_spend <= 0:
        d.skipped("Change not checked: the earlier window has no spend, so there is "
                  "nothing to compare against.")
        return d.done()

    delta = cur_spend - prev_spend
    fraction = delta / prev_spend
    if abs(delta) < _MATERIAL_USD or abs(fraction) < _MATERIAL_FRACTION:
        d.signal("ok", "Spend is broadly flat against the previous window.",
                 delta_usd=round(delta, 4), delta_fraction=round(fraction, 3))
        return d.done()

    cur_unit = cur_spend / cur_calls if cur_calls else 0.0
    prev_unit = prev_spend / prev_calls if prev_calls else 0.0
    call_growth = (cur_calls - prev_calls) / prev_calls if prev_calls else None
    unit_growth = (cur_unit - prev_unit) / prev_unit if prev_unit else None

    direction = "rose" if delta > 0 else "fell"
    if call_growth is not None and abs(call_growth) >= abs(fraction) * 0.6:
        d.signal("warn" if delta > 0 else "ok",
                 f"Spend {direction} mostly on volume — the number of calls moved with it.",
                 delta_usd=round(delta, 4), call_growth=round(call_growth, 3))
    elif unit_growth is not None and abs(unit_growth) >= abs(fraction) * 0.6:
        d.signal("warn" if delta > 0 else "ok",
                 f"Spend {direction} mostly on cost per call, not volume — the model "
                 f"mix changed.",
                 delta_usd=round(delta, 4), unit_growth=round(unit_growth, 3),
                 current_cost_per_call=round(cur_unit, 6),
                 previous_cost_per_call=round(prev_unit, 6))
    else:
        d.signal("warn" if delta > 0 else "ok",
                 f"Spend {direction}, with volume and cost per call both moving.",
                 delta_usd=round(delta, 4))
    return d.done()
```

Register:

```python
    Action("spend.diagnose_change", "Diagnose spend change",
           "Whether model spend changed against the previous period of the same "
           "length, and whether the cause was call volume or cost per call.",
           ("*",), "spend:read", ActionKind.READ, SpendWindow),
```

```python
    "spend.diagnose_change": diagnose_change,
```

```python
    "spend.diagnose_change": _r("app.api.ai_backends", "spend_report"),
```

Add `Field` to that module's pydantic import.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_spend_diagnosis.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis/spend.py backend/tests/test_chat_spend_diagnosis.py
git commit -m "feat(assistant): diagnose why model spend changed

Volume or unit price. A single-window summary cannot separate them, and the two
have different answers: more calls is a usage question, more per call means
someone changed model."
```

---

## Task 12: Audit and PII, as aggregates

**Files:**
- Create: `backend/app/chat/analysis/audit.py`
- Modify: `backend/app/chat/analysis/governance.py`, `backend/app/chat/analysis/__init__.py`
- Test: `backend/tests/test_chat_audit_aggregate.py`

**Interfaces:**
- Produces: `audit.activity_summary` — `audit:read`, no capability.
- Produces: `governance.pii_summary` — `governance:read`, no capability.

**The rule, and it is the whole task.** Neither action may be built by calling a list
endpoint and trimming the result. Trimming puts raw records in process memory, and the
boundary becomes a line of mapping code that a later change widens without anyone
noticing. `audit.activity_summary` is a dedicated `GROUP BY` against
`public.security_audit_log`, so no raw row is ever loaded.

The columns that must never leave: `actor_id`, `actor_username`, `client_address`,
`reason` (free text), and `route` — a route path can embed a resource id, which is a
target identifier however it is spelled.

The PII report is a schema-level scan: `PiiColumn` is `{column, type}`, so no detected
*value* exists to leak. What is aggregated away is the per-column detail; what is kept is
counts by table. `_scan_pii_tables()` returns `None` when no scan could run — on a
deployment with no Trino, which is the Portable Core default — and `None` means "not
scanned", never "clean". That distinction goes into `not_checked`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_audit_aggregate.py
"""Audit and PII reach the model as counts, never as records.

The forbidden strings are asserted by name. A future field added to the aggregate that
happens to carry one fails here rather than in someone's conversation.
"""
import pytest

from app.chat.analysis import audit as audit_mod
from app.chat.analysis import governance as gov_mod

FORBIDDEN = ("alice@example.com", "10.1.2.3", "b7c1f2e0-0000-0000-0000-000000000001",
             "/api/connectors/42/quality", "denied because the token had expired")


class _Conn:
    def __init__(self, rows):
        self._rows = rows
        self.sql = None

    async def fetch(self, sql, *args):
        self.sql = sql
        return self._rows


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _install_pool(monkeypatch, rows):
    conn = _Conn(rows)

    async def _pool():
        return _Pool(conn)

    monkeypatch.setattr("app.api.auth._get_pool", _pool)
    return conn


@pytest.mark.asyncio
async def test_the_summary_is_counts_and_nothing_else(monkeypatch):
    _install_pool(monkeypatch, [
        {"permission": "query:run", "outcome": "denied", "day": "2026-09-01", "n": 4},
        {"permission": "query:run", "outcome": "allowed", "day": "2026-09-01", "n": 91},
    ])
    out = await audit_mod.activity_summary({"days": 7}, {"id": "u1"})
    assert out["totals"] == {"allowed": 91, "denied": 4}
    assert out["by_permission"][0]["permission"] == "query:run"


@pytest.mark.asyncio
async def test_the_query_never_selects_an_identifying_column(monkeypatch):
    """Read the SQL, not just the output. A column selected and then dropped in Python
    is one line away from being returned."""
    conn = _install_pool(monkeypatch, [])
    await audit_mod.activity_summary({"days": 7}, {"id": "u1"})
    lowered = conn.sql.lower()
    for column in ("actor_id", "actor_username", "client_address", "reason", "route"):
        assert column not in lowered, f"{column} must not appear in the aggregate query"


@pytest.mark.asyncio
async def test_no_forbidden_string_survives_into_the_result(monkeypatch):
    _install_pool(monkeypatch, [
        {"permission": "query:run", "outcome": "denied", "day": "2026-09-01", "n": 1,
         # Fields a careless future change might add to the SELECT.
         "actor_username": "alice@example.com", "client_address": "10.1.2.3",
         "actor_id": "b7c1f2e0-0000-0000-0000-000000000001",
         "route": "/api/connectors/42/quality",
         "reason": "denied because the token had expired"},
    ])
    out = await audit_mod.activity_summary({"days": 7}, {"id": "u1"})
    rendered = repr(out)
    for secret in FORBIDDEN:
        assert secret not in rendered


@pytest.mark.asyncio
async def test_pii_summary_reports_not_scanned_rather_than_clean(monkeypatch):
    """None from the scanner means the scan could not run. Reporting that as zero
    findings is the one answer that would be actively misleading."""
    monkeypatch.setattr("app.api.governance._scan_pii_tables", lambda: None)
    out = await gov_mod.pii_summary({}, {"id": "u1"})
    assert out["scanned"] is False
    assert out["not_checked"]
    assert out["tables_with_pii"] == 0


@pytest.mark.asyncio
async def test_pii_summary_counts_tables_and_columns_without_naming_columns(monkeypatch):
    monkeypatch.setattr(
        "app.api.governance._scan_pii_tables",
        lambda: [type("E", (), {"table": "crm.customers",
                                "pii_columns": [type("C", (), {"column": "ssn",
                                                               "type": "national_id"})()]})()])
    out = await gov_mod.pii_summary({}, {"id": "u1"})
    assert out["scanned"] is True
    assert out["tables_with_pii"] == 1
    assert out["by_type"] == {"national_id": 1}
    assert "ssn" not in repr(out)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_audit_aggregate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chat.analysis.audit'`.

- [ ] **Step 3: Write the audit module**

```python
# backend/app/chat/analysis/audit.py
"""Audit activity as counts.

Deliberately not built on /governance/audit-log. That endpoint returns records, and an
action that fetched records and trimmed them would put actor names, client addresses and
route paths — which embed resource ids — into memory one careless edit away from the
model. This is a GROUP BY: the identifying columns are never selected, so there is no
path along which they reach anything.

"Who read what" stays a question for the Governance screen, which answers it to the same
people under the same permission, with no model in the middle.
"""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class AuditWindow(_Strict):
    days: int = Field(default=7, ge=1, le=90)


# Every column here is a category or a count. Adding one that is not fails
# tests/test_chat_audit_aggregate.py, which reads this statement.
_SUMMARY_SQL = """
    SELECT permission,
           outcome,
           date_trunc('day', occurred_at)::date AS day,
           count(*) AS n
      FROM public.security_audit_log
     WHERE occurred_at >= now() - ($1::int * interval '1 day')
     GROUP BY permission, outcome, day
     ORDER BY day
"""


async def activity_summary(params: dict, user: dict) -> dict:
    from app.api.auth import _get_pool

    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SUMMARY_SQL, params["days"])

    totals = {"allowed": 0, "denied": 0}
    by_permission: Dict[str, dict] = {}
    by_day: Dict[str, dict] = {}
    for row in rows:
        outcome = str(row["outcome"])
        n = int(row["n"])
        totals[outcome] = totals.get(outcome, 0) + n

        perm = by_permission.setdefault(
            str(row["permission"]), {"permission": str(row["permission"]),
                                     "allowed": 0, "denied": 0})
        perm[outcome] = perm.get(outcome, 0) + n

        day = by_day.setdefault(str(row["day"]), {"day": str(row["day"]),
                                                  "allowed": 0, "denied": 0})
        day[outcome] = day.get(outcome, 0) + n

    return {
        "days": params["days"],
        "totals": totals,
        "by_permission": sorted(by_permission.values(),
                                key=lambda r: r["denied"] + r["allowed"], reverse=True),
        "by_day": [by_day[k] for k in sorted(by_day)],
    }


ACTIONS = (
    Action("audit.activity_summary", "Audit activity summary",
           "Authorisation activity over a period as counts: allowed and denied per "
           "permission and per day. Returns no actor, address or target — those stay "
           "on the Governance screen.",
           ("*",), "audit:read", ActionKind.READ, AuditWindow),
)

EXECUTORS: Dict[str, Callable] = {"audit.activity_summary": activity_summary}
RESOLVERS: Dict[str, Callable] = {"audit.activity_summary": _r("app.api.auth", "_get_pool")}
PREVIEWERS: Dict[str, Callable] = {}
```

Add `audit` to `_MODULES`.

- [ ] **Step 4: Add the PII aggregate to `governance.py`**

```python
async def pii_summary(params: dict, user: dict) -> dict:
    """PII findings as counts by table and by category.

    `_scan_pii_tables()` returns None when no scan could run — no Trino, which is the
    Portable Core default — and None is not an empty result. Reporting "no PII found"
    for a scan that never happened is the one answer here that would be actively
    misleading, so it is reported as not scanned.

    The scan is schema-level: an entry carries a column name and a detected type, never
    a value. This drops the column names too, which are not needed to answer "where is
    our exposure" at the level a summary answers it.
    """
    from app.api.governance import _scan_pii_tables

    scanned = _scan_pii_tables()
    if scanned is None:
        return {
            "scanned": False,
            "tables_with_pii": 0,
            "columns_with_pii": 0,
            "by_type": {},
            "by_table": [],
            "not_checked": ["No PII scan could run on this deployment — the scan needs "
                            "the Trino query engine. This is not a clean result."],
        }

    by_type: dict = {}
    by_table = []
    columns = 0
    for entry in scanned:
        cols = list(getattr(entry, "pii_columns", []) or [])
        columns += len(cols)
        by_table.append({"table": getattr(entry, "table", ""), "columns": len(cols)})
        for col in cols:
            kind = str(getattr(col, "type", "") or "unknown")
            by_type[kind] = by_type.get(kind, 0) + 1

    return {
        "scanned": True,
        "tables_with_pii": len(by_table),
        "columns_with_pii": columns,
        "by_type": by_type,
        "by_table": sorted(by_table, key=lambda r: r["columns"], reverse=True),
        "not_checked": [],
    }
```

Register in `governance.py`:

```python
    Action("governance.pii_summary", "PII summary",
           "Where PII was detected, as counts by table and category. Reports "
           "'not scanned' rather than 'clean' when no scan could run.",
           ("*",), "governance:read", ActionKind.READ, _Strict),
```

```python
    "governance.pii_summary": pii_summary,
```

```python
    "governance.pii_summary": _r("app.api.governance", "_scan_pii_tables"),
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && python3 -m pytest tests/test_chat_audit_aggregate.py tests/test_chat_governance_reads.py tests/test_chat_analysis_assembly.py tests/test_chat_executor_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/analysis/audit.py backend/app/chat/analysis/governance.py backend/app/chat/analysis/__init__.py backend/tests/test_chat_audit_aggregate.py
git commit -m "feat(assistant): audit and PII as aggregates, with no record in the path

Built as a GROUP BY rather than a filtered list, so actor names, client
addresses and route paths — which embed resource ids — are never selected. The
test reads the SQL as well as the output: a column selected and dropped in
Python is one line from being returned.

The PII summary reports 'not scanned' when no scan could run. On the Portable
Core there is no Trino to scan with, and calling that clean would be the one
actively misleading answer available."
```

---

## Task 13: Say what it can do now

**Files:**
- Modify: `backend/app/api/chat_routes.py` (`_system_prompt`)
- Modify: `frontend/components/chat/assistant-panel.tsx` (the greeting)
- Test: `backend/tests/test_chat_prompt_copy.py`

Both texts describe the narrower reach the assistant had before this work. Left alone
they are false the moment it ships — and the sentence that must survive verbatim is the
one that is still true: it cannot change settings and cannot delete anything.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_prompt_copy.py
"""What the assistant says it can do has to match what the registry lets it do."""
from app.api.chat_routes import _system_prompt


def test_the_prompt_still_refuses_writes_it_cannot_do():
    """The registry has no action that changes settings, runs a sync or deletes
    anything. If that ever stops being true, this sentence has to change with it —
    and the second assertion below is what forces the pairing."""
    prompt = _system_prompt("/knowledge", {})
    assert "cannot delete" in prompt
    assert "change settings" in prompt


def test_the_registry_agrees_with_that_claim():
    from app.chat.actions import REGISTRY
    for action in REGISTRY.values():
        assert action.permission not in ("settings:write", "user:manage"), action.id
        assert "delete" not in action.id, action.id
        assert action.id != "connectors.sync", action.id


def test_the_prompt_mentions_the_reach_it_now_has():
    prompt = _system_prompt("/knowledge", {})
    for word in ("sources", "services", "storage", "collections"):
        assert word in prompt.lower(), f"prompt no longer mentions {word}"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && python3 -m pytest tests/test_chat_prompt_copy.py -q`
Expected: FAIL on the third test — the prompt names none of those.

- [ ] **Step 3: Update the prompt**

In `backend/app/api/chat_routes.py`, replace the last sentence of `_system_prompt`:

```python
        "You can read and analyse this deployment — the catalog, queries, knowledge "
        "collections, sources and their syncs, services, storage, governance policies, "
        "audit activity and model spend — using only the tools you were given.\n"
        "You cannot delete anything, run a sync, or change settings. If asked, say so "
        "plainly and suggest where in the UI to do it."
```

- [ ] **Step 4: Update the panel greeting**

In `frontend/components/chat/assistant-panel.tsx`, replace the greeting text
("Ask about the data here. I can look things up and, with your approval, run a query,
save a dashboard, or create a collection. I cannot delete anything or change settings.")
with:

```
Ask about this deployment — the data, your sources and syncs, collections, services,
storage, policies and spend. With your approval I can run a query, save a dashboard, or
create a collection. I cannot delete anything, run a sync, or change settings.
```

- [ ] **Step 5: Run both suites**

Run: `cd backend && python3 -m pytest tests/test_chat_prompt_copy.py -q`
Expected: PASS.

Run: `cd frontend && npm test && npx tsc --noEmit -p tsconfig.json && npm run build`
Expected: PASS, clean, compiled.

- [ ] **Step 6: Full backend chat suite, one last time**

Run: `cd backend && python3 -m pytest tests/ -q -k "chat or capabilit or component_guard"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/chat_routes.py frontend/components/chat/assistant-panel.tsx backend/tests/test_chat_prompt_copy.py
git commit -m "feat(assistant): say what it can reach now, and what it still cannot

Both texts described the reach it had before this work. The test pairs the
claim with the registry: the sentence about settings, syncs and deletion stays
only while no action in the registry can do any of them."
```

---

## Done

Every task above ships behind the same two gates the assistant already had, plus the
third this plan adds. Nothing here can change or delete anything; the configuration half
is spec §11, and the decision about it should be made against the invocation records
these actions produce.
