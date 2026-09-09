# MCP Read Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent authenticates with the service-account key it already uses for REST, asks `POST /api/mcp` which tools its scopes allow, calls one, and leaves exactly one `tool_call_log` row — with no write action reachable.

**Architecture:** A new package `backend/app/mcp/` in three layers: `protocol.py` (JSON-RPC 2.0 and the three MCP methods, pure), `tools.py` (the action registry rendered as MCP tool descriptors), `server.py` (the router: principal → dispatch → audit). One function is extracted from the chat gate into `app/chat/authz.py` so both surfaces decide authorization the same way and record it their own way. Migration `0009` rewrites the `tool_call_log.tool` CHECK so fallback rows can carry an action id.

**Tech Stack:** FastAPI 0.109 / pydantic 2.5.3 (both pinned — no new dependency), asyncpg-style `$n` SQL, Alembic wrapper migrations (`.py` + `.sql`), pytest with fake pools.

**Spec:** `docs/superpowers/specs/2026-09-09-mcp-read-server-design.md`

## Global Constraints

- **No new runtime dependency.** The MCP SDK is out (spec §2.1): every version needs `pydantic>=2.7.2`, this repo pins 2.5.3. Do not add anything to `requirements.txt`.
- **Python:** run everything through the project venv — `cd backend && .venv/bin/python -m pytest tests -q -p no:cacheprovider`. The system `python3` is 3.9 and cannot import the app; the bare `python3.12` lacks declared packages (see `docs/DEVELOPMENT.md`). The full suite is **1706 passed, 0 failed** on `main` — any failure is yours.
- **No database in tests.** Fake pool/conn classes; migrations asserted as SQL text. Async tests use `asyncio.new_event_loop().run_until_complete(...)`; no pytest-asyncio.
- **Read-only is structural, not a promise.** Three independent refusals (spec §5): the list filters `kind is READ`, `tools/call` re-checks kind, and nothing in this plan touches `gate.propose`.
- **Unknown, unauthorised and non-READ tool names return the identical response.** A caller learns a tool exists only by being allowed to see it. Never add a distinguishing message.
- **Protocol version is exactly `2026-07-28`.** One constant, one value.
- **Migration:** `0009_tool_call_log_tool_ids`, `down_revision = "0008_tool_call_log"`. `app/migration_rules.py` forbids `DROP TABLE`, `DROP COLUMN`, `RENAME TO|COLUMN`, `SET NOT NULL` — dropping and re-adding a CHECK is none of those.
- **zsh:** never write a bare `echo ====` (a leading `=` is expanded); quote such strings.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PQW9stoiSQnnohhnBCDEvL
  ```

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/chat/authz.py` (new) | `authorize(action, user)` and `held_permissions(user)` — the one fact chat and MCP share. Raises; never records. |
| `backend/app/chat/gate.py` (modify) | `_authorize` becomes a wrapper that adds chat's audit vocabulary around `authz.authorize`. |
| `backend/app/mcp/__init__.py` (new) | Empty package marker. |
| `backend/app/mcp/protocol.py` (new) | JSON-RPC envelope, the three method results, error codes. No DataPond knowledge. |
| `backend/app/mcp/tools.py` (new) | Name mapping, `exposed_actions`, `descriptors`. |
| `backend/app/mcp/server.py` (new) | `resolve_principal`, the `POST /mcp` route, the dispatcher, the fallback audit row. |
| `backend/app/tool_call_log.py` (modify) | `counting()` context manager and the counter increment inside `record`. |
| `backend/migrations/versions/0009_tool_call_log_tool_ids.{py,sql}` (new) | Rewrites the `tool` CHECK. |
| `backend/main.py` (modify) | Import and mount the router at `prefix="/api"`. |
| `backend/app/chat/analysis/*.py` (modify) | 24 field descriptions across 17 parameter models. |
| `docs/MCP.md` (new) | How to point an agent at the server. |

---

### Task 1: `app/chat/authz.py` — one authorization decision, two recorders

**Files:**
- Create: `backend/app/chat/authz.py`
- Modify: `backend/app/chat/gate.py` (`_held_permissions` at ~line 60, `_authorize` at ~line 96, its two call sites in `propose` and `approve`)
- Test: `backend/tests/test_chat_authz.py`

**Interfaces:**
- Produces: `held_permissions(user: dict) -> Set[str]`; `authorize(action: Action, user: dict) -> None`; exceptions `NotPermitted(action)` and `CapabilityOff(action)`, each carrying `.action` and `.required`.
- Consumes: `app.chat.actions.Action`, `app.component_guard.capability_on`, `app.permissions.permissions_for`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_authz.py
"""The authorization decision the assistant panel and the MCP server share.

Both surfaces must answer 'may this caller run this action' identically — that is the
whole reason the decision was extracted from the gate. The parity test below is what
keeps them from drifting: it asserts `authorize` agrees with `actions_for`, which is
the filter the tool list is built from, for every action against several permission
sets. A tool a caller can see but not call, or the reverse, fails here.
"""
import pytest

from app.chat import authz
from app.chat.actions import REGISTRY, actions_for


ALL_PERMISSIONS = sorted({a.permission for a in REGISTRY.values()})
ALL_CAPABILITIES = {a.capability: True for a in REGISTRY.values() if a.capability}


@pytest.fixture
def caps_on(monkeypatch):
    """capability_on reads the environment; actions_for takes a map. Pin both to the
    same answer so the parity test measures the permission rule, not the environment."""
    monkeypatch.setattr(authz, "capability_on", lambda key: ALL_CAPABILITIES.get(key) is True)
    return ALL_CAPABILITIES


@pytest.mark.parametrize("permissions", [
    set(),
    {"knowledge:read"},
    {"knowledge:read", "ai:generate"},
    set(ALL_PERMISSIONS),
])
def test_authorize_agrees_with_actions_for(permissions, caps_on):
    allowed = {a.id for a in actions_for(permissions, "*", caps_on)}
    user = {"permissions": sorted(permissions)}
    for action in REGISTRY.values():
        try:
            authz.authorize(action, user)
            permitted = True
        except (authz.NotPermitted, authz.CapabilityOff):
            permitted = False
        assert permitted is (action.id in allowed), action.id


def test_capability_off_is_refused_even_with_the_permission(monkeypatch):
    monkeypatch.setattr(authz, "capability_on", lambda key: False)
    gated = next(a for a in REGISTRY.values() if a.capability)
    with pytest.raises(authz.CapabilityOff) as exc:
        authz.authorize(gated, {"permissions": [gated.permission]})
    assert exc.value.required == gated.capability


def test_held_permissions_prefers_the_key_over_the_role():
    """A service-account key carries its own narrowed set; a person is judged by role."""
    assert authz.held_permissions({"permissions": ["knowledge:read"], "role": "admin"}) \
        == {"knowledge:read"}
    assert "knowledge:read" in authz.held_permissions({"role": "admin"})


def test_an_empty_scope_list_is_not_the_same_as_no_scopes():
    """`permissions: []` is a key that was granted nothing — not a fall-back to role."""
    assert authz.held_permissions({"permissions": [], "role": "admin"}) == set()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_authz.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chat.authz'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/chat/authz.py
"""Who may run which action.

Extracted from gate._authorize, which interleaved this decision with the chat panel's
audit writes. The decision belongs to every surface that offers actions; the recording
does not — the panel writes chat_action_refused, the MCP server writes a tool_call_log
row and returns a protocol error. So this module raises and returns, and knows nothing
about stores, audit events or HTTP.
"""
from typing import Set

from app.chat.actions import Action
from app.component_guard import capability_on
from app.permissions import permissions_for


class NotPermitted(Exception):
    """The caller does not hold the action's permission."""

    def __init__(self, action: Action):
        self.action = action
        self.required = action.permission
        super().__init__(
            f"'{action.permission}' permission required to {action.label.lower()}.")


class CapabilityOff(Exception):
    """The action needs a component this deployment does not run."""

    def __init__(self, action: Action):
        self.action = action
        self.required = action.capability
        super().__init__(
            f"{action.label} needs a component this deployment does not run.")


def held_permissions(user: dict) -> Set[str]:
    """A service-account key carries its own set (role narrowed by scopes); a person is
    judged by role. Same rule as require_permission, so the gate, the API and the MCP
    server agree. An explicit empty list means a key that was granted nothing, which is
    why this tests for None rather than falsiness."""
    granted = user.get("permissions")
    return set(granted) if granted is not None else set(permissions_for(user.get("role")))


def authorize(action: Action, user: dict) -> None:
    """Raise unless this caller may run this action on this deployment.

    The capability half is recomputed from the server's own environment by the same
    predicate the route guards use — a map a client sent is never the one that decides.
    """
    if action.permission not in held_permissions(user):
        raise NotPermitted(action)
    if action.capability and not capability_on(action.capability):
        raise CapabilityOff(action)
```

- [ ] **Step 4: Rewire the gate**

In `backend/app/chat/gate.py`:

1. Add to the imports: `from app.chat.authz import CapabilityOff, NotPermitted, authorize, held_permissions`.
2. Delete the local `_held_permissions` definition and replace its body with a re-export so any existing importer keeps working:
   ```python
   _held_permissions = held_permissions  # moved to app.chat.authz; both surfaces share it
   ```
   First run `grep -rn '_held_permissions' backend/` — if nothing outside `gate.py` imports it, delete the name entirely and update the internal call sites instead. Say which you did in the report.
3. Replace `_authorize` with:
   ```python
   async def _authorize(action: Action, user: dict, store: InvocationStore,
                        stage: str) -> None:
       """The shared decision, recorded in the panel's own vocabulary."""
       try:
           authorize(action, user)
       except NotPermitted as e:
           await _audit(store, "chat_action_refused", user, action=action.id,
                        stage=stage, reason="permission", required=e.required)
           raise ActionRefused(str(e)) from e
       except CapabilityOff as e:
           await _audit(store, "chat_action_refused", user, action=action.id,
                        stage=stage, reason="capability", required=e.required)
           raise ActionRefused(str(e)) from e
   ```
   Note the dropped `page` parameter: the old signature took it and never used it. Update both call sites (`propose` and `approve`) to match.

- [ ] **Step 5: Run the new test and every chat test**

Run: `cd backend && .venv/bin/python -m pytest tests/test_chat_authz.py -q -p no:cacheprovider && .venv/bin/python -m pytest tests -q -p no:cacheprovider -k chat`
Expected: the new file passes; every existing chat test passes unchanged. The refusal messages and audit `reason` values are byte-identical to before — that is the point of the wrapper. If a chat test fails, the extraction changed behaviour: fix the extraction, never the test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/authz.py backend/app/chat/gate.py backend/tests/test_chat_authz.py
git commit -m "refactor(chat): the authorization decision leaves the gate, the recording stays"
```

---

### Task 2: `app/mcp/protocol.py` — the wire

**Files:**
- Create: `backend/app/mcp/__init__.py` (empty), `backend/app/mcp/protocol.py`
- Test: `backend/tests/test_mcp_protocol.py`

**Interfaces:**
- Produces: `PROTOCOL_VERSION`; codes `PARSE_ERROR`, `INVALID_REQUEST`, `METHOD_NOT_FOUND`, `INVALID_PARAMS`; `JsonRpcError(code, message, request_id=None)`; `parse_request(body) -> (id, method, params)`; `result(id, payload)`; `error(id, code, message)`; `initialize_result(name, version)`; `tools_list_result(tools)`; `tool_call_result(text, is_error=False)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mcp_protocol.py
"""JSON-RPC 2.0 and the three MCP methods, with no application underneath.

The protocol layer is the part a future SDK would replace, so it is tested against
message shapes rather than against DataPond behaviour: everything here would still be
true if the tools were something else entirely.
"""
import pytest

from app.mcp import protocol as p


def test_the_protocol_version_is_pinned():
    assert p.PROTOCOL_VERSION == "2026-07-28"


def test_parse_request_returns_id_method_params():
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "knowledge_search", "arguments": {"collection": "faq"}}}
    assert p.parse_request(body) == (3, "tools/call", body["params"])


def test_a_notification_has_no_id():
    rid, method, params = p.parse_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert rid is None and method == "notifications/initialized" and params == {}


@pytest.mark.parametrize("body,code", [
    ("not an object", p.INVALID_REQUEST),
    ({"id": 1, "method": "tools/list"}, p.INVALID_REQUEST),            # no jsonrpc
    ({"jsonrpc": "1.0", "id": 1, "method": "tools/list"}, p.INVALID_REQUEST),
    ({"jsonrpc": "2.0", "id": 1}, p.INVALID_REQUEST),                  # no method
    ({"jsonrpc": "2.0", "id": 1, "method": ""}, p.INVALID_REQUEST),
    ({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}, p.INVALID_PARAMS),
])
def test_malformed_requests_are_refused_with_the_right_code(body, code):
    with pytest.raises(p.JsonRpcError) as exc:
        p.parse_request(body)
    assert exc.value.code == code


def test_the_error_keeps_the_request_id_when_there_was_one():
    with pytest.raises(p.JsonRpcError) as exc:
        p.parse_request({"jsonrpc": "1.0", "id": 7, "method": "tools/list"})
    assert exc.value.request_id == 7


def test_result_and_error_envelopes():
    assert p.result(1, {"ok": True}) == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    assert p.error(1, p.METHOD_NOT_FOUND, "nope") == {
        "jsonrpc": "2.0", "id": 1,
        "error": {"code": p.METHOD_NOT_FOUND, "message": "nope"}}


def test_initialize_result_announces_tools_and_the_version():
    r = p.initialize_result("datapond", "0.1.0")
    assert r["protocolVersion"] == "2026-07-28"
    assert r["capabilities"] == {"tools": {}}
    assert r["serverInfo"] == {"name": "datapond", "version": "0.1.0"}


def test_tools_list_result_wraps_the_list():
    assert p.tools_list_result([{"name": "a"}]) == {"tools": [{"name": "a"}]}


def test_tool_call_result_is_a_text_content_block():
    ok = p.tool_call_result('{"rows": 1}')
    assert ok == {"content": [{"type": "text", "text": '{"rows": 1}'}], "isError": False}
    assert p.tool_call_result("boom", is_error=True)["isError"] is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_protocol.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/mcp/__init__.py
```
(empty file)

```python
# backend/app/mcp/protocol.py
"""JSON-RPC 2.0 and the three MCP methods this server answers.

Pure: dicts in, dicts out. It knows nothing about actions, users, permissions or the
database, which is what lets the protocol be tested against message shapes alone — and
what makes it the single place a future SDK adoption would land.

Protocol errors (a malformed envelope, an unknown method) are JSON-RPC errors. A tool
that runs and fails is not one: per the specification that is a *result* carrying
isError, because the call reached the tool. See the design's §7.
"""
from typing import Any, Dict, List, Tuple

PROTOCOL_VERSION = "2026-07-28"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, request_id: Any = None):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(message)


def parse_request(body: Any) -> Tuple[Any, str, Dict]:
    """`(id, method, params)`, or JsonRpcError.

    `id` is None for a notification, which the stateless HTTP transport answers with no
    body at all — so the caller must check for it before dispatching.
    """
    if not isinstance(body, dict):
        raise JsonRpcError(INVALID_REQUEST, "Request must be a JSON object")
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        raise JsonRpcError(INVALID_REQUEST, "Only JSON-RPC 2.0 is supported", request_id)
    method = body.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcError(INVALID_REQUEST, "Missing method", request_id)
    params = body.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise JsonRpcError(INVALID_PARAMS, "params must be an object", request_id)
    return request_id, method, params


def result(request_id: Any, payload: Dict) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error(request_id: Any, code: int, message: str) -> Dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def initialize_result(server_name: str, server_version: str) -> Dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": server_name, "version": server_version},
    }


def tools_list_result(tools: List[dict]) -> Dict:
    return {"tools": list(tools)}


def tool_call_result(text: str, is_error: bool = False) -> Dict:
    """A tool's answer as MCP carries it: content blocks, plus the isError flag.

    Action executors return dicts; the server serialises one into a single text block,
    which every client understands.
    """
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
```

- [ ] **Step 4: Run it green**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_protocol.py -q -p no:cacheprovider`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/__init__.py backend/app/mcp/protocol.py backend/tests/test_mcp_protocol.py
git commit -m "feat(mcp): the JSON-RPC layer, with nothing of DataPond in it"
```

---

### Task 3: `app/mcp/tools.py` — the registry as tools

**Files:**
- Create: `backend/app/mcp/tools.py`
- Test: `backend/tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `app.chat.actions.{Action, ActionKind, REGISTRY, actions_for}`.
- Produces: `mcp_name(action_id) -> str`; `action_id_for(name) -> Optional[str]`; `exposed_actions(permissions, capabilities=None) -> List[Action]`; `descriptors(permissions, capabilities=None) -> List[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mcp_tools.py
"""The action registry rendered as MCP tools.

Two properties matter more than the rendering: the name map cannot collide (a new
action must not silently shadow an existing tool), and nothing but a READ action can
reach the list.
"""
from app.chat.actions import REGISTRY, ActionKind
from app.mcp import tools


ALL_CAPS = {a.capability: True for a in REGISTRY.values() if a.capability}
ALL_PERMS = sorted({a.permission for a in REGISTRY.values()})


def test_names_are_the_ids_with_dots_replaced():
    assert tools.mcp_name("knowledge.search") == "knowledge_search"


def test_the_name_map_is_collision_free_and_round_trips():
    seen = {}
    for action in REGISTRY.values():
        name = tools.mcp_name(action.id)
        assert name not in seen, f"{action.id} and {seen.get(name)} both map to {name}"
        seen[name] = action.id
        assert tools.action_id_for(name) == action.id


def test_every_name_is_what_a_client_will_accept():
    """Common clients and gateways validate against ^[a-zA-Z0-9_-]{1,64}$ and reject a
    dotted name at invocation time rather than at registration."""
    import re
    for action in REGISTRY.values():
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tools.mcp_name(action.id)), action.id


def test_an_unknown_name_resolves_to_nothing():
    assert tools.action_id_for("no_such_tool") is None


def test_only_read_actions_are_exposed():
    exposed = tools.exposed_actions(ALL_PERMS, ALL_CAPS)
    assert exposed, "expected some tools"
    assert all(a.kind is ActionKind.READ for a in exposed)
    expected = {a.id for a in REGISTRY.values() if a.kind is ActionKind.READ}
    assert {a.id for a in exposed} == expected


def test_a_narrow_key_sees_a_short_list():
    narrow = {a.id for a in tools.exposed_actions(["knowledge:read"], ALL_CAPS)}
    assert "knowledge.search" in narrow
    assert "spend.summarize" not in narrow
    assert narrow < {a.id for a in tools.exposed_actions(ALL_PERMS, ALL_CAPS)}


def test_a_capability_that_is_off_hides_its_tools_from_everyone():
    assert not [a for a in tools.exposed_actions(ALL_PERMS, {}) if a.capability]


def test_descriptors_carry_name_description_and_schema():
    d = {t["name"]: t for t in tools.descriptors(ALL_PERMS, ALL_CAPS)}
    search = d["knowledge_search"]
    assert search["description"]
    schema = search["inputSchema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "title" not in schema
    assert set(schema["properties"]) == {"collection", "query"}


def test_an_action_with_no_parameters_still_gets_an_object_schema():
    d = {t["name"]: t for t in tools.descriptors(ALL_PERMS, ALL_CAPS)}
    schema = d["storage_overview"]["inputSchema"]
    assert schema["type"] == "object" and schema["properties"] == {}
    assert schema["required"] == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_tools.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'tools' from 'app.mcp'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/mcp/tools.py
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
```

- [ ] **Step 4: Run it green**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_tools.py -q -p no:cacheprovider`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/tools.py backend/tests/test_mcp_tools.py
git commit -m "feat(mcp): read actions as tool descriptors, named for the clients that consume them"
```

---

### Task 4: counting rows, and a `tool` column that can hold an action id

**Files:**
- Modify: `backend/app/tool_call_log.py` (the ContextVar block near line 25, and `record` at ~line 128)
- Create: `backend/migrations/versions/0009_tool_call_log_tool_ids.py`, `backend/migrations/versions/0009_tool_call_log_tool_ids.sql`
- Test: `backend/tests/test_tool_call_counting.py`, `backend/tests/test_mcp_migration.py`

**Interfaces:**
- Produces: `tool_call_log.counting()` — a context manager yielding a zero-argument callable that returns how many rows `record` wrote inside the block.
- Produces: migration `0009_tool_call_log_tool_ids`, `down_revision = "0008_tool_call_log"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_tool_call_counting.py
"""Counting rows so the MCP dispatcher can tell whether the inner path already logged.

Suppressing the inner write would have been simpler and worse: the /ai/* routes build a
row carrying the collection, the hit count, the cited sources and the masked count, and
a flat row written at the MCP boundary would have thrown all of that away for the sake
of uniformity. Counting keeps the rich row where one exists and fills the gap where one
does not.
"""
import asyncio

from app import tool_call_log


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


ACTOR = {"id": "11111111-1111-1111-1111-111111111111", "username": "svc-bot",
         "auth_method": "service"}


class _Conn:
    def __init__(self):
        self.rows = 0

    async def execute(self, sql, *args):
        self.rows += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self, timeout=None):
        return self._conn


class _BrokenPool:
    def acquire(self, timeout=None):
        raise RuntimeError("pool is gone")


def _patch_pool(monkeypatch, pool):
    async def _get_db_pool():
        return pool
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _get_db_pool)


def _record(**over):
    kwargs = dict(actor=ACTOR, tool="ai.search", resource_kind="collection",
                  resource=["faq"], request_text="q")
    kwargs.update(over)
    return tool_call_log.record(**kwargs)


def test_counting_reports_rows_written_inside_the_block(monkeypatch):
    _patch_pool(monkeypatch, _Pool(_Conn()))

    async def _go():
        with tool_call_log.counting() as count:
            assert count() == 0
            await _record()
            await _record()
            return count()
    assert _run(_go()) == 2


def test_a_failed_write_does_not_count(monkeypatch):
    """Otherwise a lost row would suppress the dispatcher's fallback and the call would
    vanish from the log entirely."""
    _patch_pool(monkeypatch, _BrokenPool())

    async def _go():
        with tool_call_log.counting() as count:
            await _record()
            return count()
    assert _run(_go()) == 0


def test_the_counter_does_not_leak_out_of_the_block(monkeypatch):
    _patch_pool(monkeypatch, _Pool(_Conn()))

    async def _go():
        with tool_call_log.counting():
            pass
        await _record()          # outside: no counter, must not raise
    _run(_go())


def test_counting_nests_without_disturbing_the_outer_count(monkeypatch):
    _patch_pool(monkeypatch, _Pool(_Conn()))

    async def _go():
        with tool_call_log.counting() as outer:
            await _record()
            with tool_call_log.counting() as inner:
                await _record()
                assert inner() == 1
            return outer()
    assert _run(_go()) == 1
```

```python
# backend/tests/test_mcp_migration.py
"""Migration 0009, checked as text — there is no database in this test environment."""
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0009_tool_call_log_tool_ids.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0009_tool_call_log_tool_ids.py").read_text(encoding="utf-8")


def test_revision_chain_points_at_0008():
    assert 'revision: str = "0009_tool_call_log_tool_ids"' in PY
    assert 'down_revision: Union[str, None] = "0008_tool_call_log"' in PY


def test_the_old_constraint_is_found_by_definition_not_by_name():
    """An inline column CHECK is auto-named by PostgreSQL. Dropping a guessed name would
    silently do nothing and leave the old constraint rejecting every new row."""
    assert "pg_constraint" in SQL and "conrelid" in SQL
    assert "DROP CONSTRAINT" in SQL


def test_a_new_constraint_replaces_it_rather_than_nothing():
    assert "ADD CONSTRAINT tool_call_log_tool_check" in SQL
    for tool in ("ai.search", "ai.rag", "ai.sql", "query.execute"):
        assert tool in SQL, tool


def test_every_registered_action_id_satisfies_the_new_pattern():
    """The constraint must not reject a tool the server can legitimately log."""
    import re
    from app.chat.actions import REGISTRY
    pattern = re.search(r"tool ~ '\^(.+?)\$'", SQL)
    assert pattern, "expected a regex branch in the CHECK"
    rx = re.compile("^" + pattern.group(1).replace("\\\\", "\\") + "$")
    for action_id in REGISTRY:
        assert rx.match(action_id), action_id


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0009_tool_call_log_tool_ids", SQL) == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tool_call_counting.py tests/test_mcp_migration.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'app.tool_call_log' has no attribute 'counting'` and `FileNotFoundError` on the `.sql`.

- [ ] **Step 3: Add `counting()` to `tool_call_log.py`**

Beside the existing `_via` / `_client_address` ContextVars:

```python
_calls: contextvars.ContextVar[Optional[List[int]]] = \
    contextvars.ContextVar("tool_call_count", default=None)


@contextmanager
def counting() -> Iterator[Callable[[], int]]:
    """Count the rows `record` writes inside this block.

    The MCP dispatcher writes its own row only when the inner path wrote none, so a
    data tool keeps the rich row its route builds — collection, hit count, cited
    sources, masked count — and a diagnostic tool still leaves a trace. Only a
    successful insert counts: a lost row must not suppress the fallback, or the call
    would disappear from the log altogether.
    """
    counter = [0]
    token = _calls.set(counter)
    try:
        yield lambda: counter[0]
    finally:
        _calls.reset(token)
```

Inside `record`, immediately after the `await conn.execute(...)` succeeds and still inside the `try`:

```python
        counter = _calls.get()
        if counter is not None:
            counter[0] += 1
```

Add `Callable`, `Iterator` and `List` to the module's `typing` import if they are not there already.

- [ ] **Step 4: Write the migration**

```sql
-- backend/migrations/versions/0009_tool_call_log_tool_ids.sql
-- 0008 constrained `tool` to the four data tools it knew about. The MCP server
-- (docs/superpowers/specs/2026-09-09-mcp-read-server-design.md) logs one row per tool
-- call, and for the twenty-three actions whose executors do not reach an /ai/* route it
-- writes a fallback row carrying the action id: catalog.find_tables, spend.summarize.
--
-- The constraint is rewritten, not removed. An unconstrained column would let a typo
-- become a permanent row in a table with an append-only trigger and no UPDATE — there
-- is no correcting it afterwards. The pattern admits any registered action id shape
-- (lowercase words either side of one dot) and still rejects free text, an empty
-- string, and anything with whitespace.
--
-- The old constraint is located by definition rather than by name: 0008 declared it
-- inline on the column, so PostgreSQL auto-named it, and dropping a guessed name would
-- silently succeed while leaving the real constraint in place.
DO $$
DECLARE
    old_name text;
BEGIN
    SELECT conname INTO old_name
      FROM pg_constraint
     WHERE conrelid = 'public.tool_call_log'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%tool%ai.search%';
    IF old_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.tool_call_log DROP CONSTRAINT %I', old_name);
    END IF;
END $$;

ALTER TABLE public.tool_call_log
    ADD CONSTRAINT tool_call_log_tool_check
    CHECK (tool IN ('ai.search', 'ai.rag', 'ai.sql', 'query.execute')
           OR tool ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$');
```

```python
# backend/migrations/versions/0009_tool_call_log_tool_ids.py
"""tool_call_log.tool admits action ids, for the MCP server's fallback rows.

Revision ID: 0009_tool_call_log_tool_ids
Revises: 0008_tool_call_log
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0009_tool_call_log_tool_ids"
down_revision: Union[str, None] = "0008_tool_call_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    run_sql(
        op.get_bind(),
        "ALTER TABLE public.tool_call_log "
        "DROP CONSTRAINT IF EXISTS tool_call_log_tool_check;",
    )
```

- [ ] **Step 5: Run the tests and the migration suites**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tool_call_counting.py tests/test_mcp_migration.py tests/test_migrations.py tests/test_tool_call_log.py tests/test_tool_call_log_export.py tests/test_audit_append_only.py -q -p no:cacheprovider`
Expected: PASS. If `test_migrations.py` pins the head revision, update it to `0009_tool_call_log_tool_ids` and say so in the report.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tool_call_log.py backend/migrations/versions/0009_tool_call_log_tool_ids.py backend/migrations/versions/0009_tool_call_log_tool_ids.sql backend/tests/test_tool_call_counting.py backend/tests/test_mcp_migration.py
git commit -m "feat(audit): count rows inside a block, and let tool hold an action id"
```

---

### Task 5: `app/mcp/server.py` — the endpoint, and one row per call

**Files:**
- Create: `backend/app/mcp/server.py`
- Modify: `backend/main.py` (import beside `tool_call_router` at ~line 49; `include_router` at ~line 409)
- Test: `backend/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: Tasks 1–4 (`authz.authorize`, `protocol.*`, `tools.*`, `tool_call_log.counting`), `app.chat.executors.EXECUTORS`, `app.capabilities.compute_capabilities`, `app.api.auth.require_user`.
- Produces: `resolve_principal` (the auth seam), `router` with `POST /mcp`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mcp_server.py
"""The MCP endpoint: who may call it, what it lists, and what it refuses.

The refusal cases matter most. An unknown tool, a tool this key may not use, and a
write action all return the *same* answer, so that tools/call cannot be used to
enumerate either the deployment's components or the key's scopes.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import auth
from app.mcp import protocol, server

_REAL_REQUIRE_USER = auth.require_user

SERVICE = {"id": "22222222-2222-2222-2222-222222222222", "username": "svc-bot",
           "role": "ai_engineer", "auth_method": "service",
           "permissions": ["knowledge:read", "ai:generate"]}


def _app(user=SERVICE):
    app = FastAPI()
    app.include_router(server.router, prefix="/api")

    async def _override():
        return user
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def _rpc(client, method, params=None, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/api/mcp", json=body)


@pytest.fixture(autouse=True)
def _no_log_writes(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)
    return calls


@pytest.fixture
def logged(_no_log_writes):
    return _no_log_writes


def test_initialize_answers_with_the_pinned_version():
    r = _rpc(TestClient(_app()), "initialize",
             {"protocolVersion": "2026-07-28", "capabilities": {}})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {}}


def test_a_notification_gets_no_body():
    r = TestClient(_app()).post(
        "/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert r.content == b""


def test_tools_list_is_scoped_to_the_key():
    r = _rpc(TestClient(_app()), "tools/list")
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert "knowledge_search" in names
    assert "spend_summarize" not in names          # the key lacks spend:read
    assert not any(n.startswith("knowledge_create") for n in names)   # writes never listed


def test_an_unknown_method_is_a_protocol_error():
    r = _rpc(TestClient(_app()), "resources/list")
    assert r.json()["error"]["code"] == protocol.METHOD_NOT_FOUND


def test_malformed_json_is_a_parse_error():
    r = TestClient(_app()).post("/api/mcp", content=b"{not json",
                                headers={"Content-Type": "application/json"})
    assert r.json()["error"]["code"] == protocol.PARSE_ERROR


def test_a_tool_runs_and_returns_its_payload_as_text(monkeypatch):
    async def _exec(params, user):
        return {"results": [{"source": "a.md"}]}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _exec)
    r = _rpc(TestClient(_app()), "tools/call",
             {"name": "knowledge_search",
              "arguments": {"collection": "faq", "query": "hi"}})
    result = r.json()["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"results": [{"source": "a.md"}]}


def test_bad_arguments_are_a_tool_error_not_a_protocol_error():
    r = _rpc(TestClient(_app()), "tools/call",
             {"name": "knowledge_search", "arguments": {"collection": "faq"}})
    assert "error" not in r.json()
    assert r.json()["result"]["isError"] is True


@pytest.mark.parametrize("name", [
    "no_such_tool",            # never existed
    "spend_summarize",         # exists, this key lacks spend:read
    "knowledge_create_collection",   # exists, is a write
])
def test_unknown_unauthorised_and_write_names_are_indistinguishable(name):
    r = _rpc(TestClient(_app()), "tools/call", {"name": name, "arguments": {}})
    result = r.json()["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == f"No such tool: {name}."


def test_an_executor_that_raises_becomes_a_tool_error(monkeypatch):
    async def _boom(params, user):
        raise RuntimeError("upstream is down")
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _boom)
    r = _rpc(TestClient(_app()), "tools/call",
             {"name": "knowledge_search",
              "arguments": {"collection": "faq", "query": "hi"}})
    result = r.json()["result"]
    assert result["isError"] is True and "upstream is down" in result["content"][0]["text"]


def test_a_call_that_logged_nothing_gets_a_fallback_row(logged, monkeypatch):
    async def _exec(params, user):
        return {"collections": []}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.list_collections", _exec)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections", "arguments": {}})
    assert len(logged) == 1
    row = logged[0]
    assert row["tool"] == "knowledge.list_collections"
    assert row["outcome"] == "ok" and row["resource_kind"] == "none"
    assert row["via"] == "mcp"


def test_a_call_whose_route_logged_does_not_get_a_second_row(logged, monkeypatch):
    async def _exec(params, user):
        # stands in for the /ai/search wrapper, which logs its own richer row
        await tool_call_log.record(actor=user, tool="ai.search",
                                   resource_kind="collection", resource=["faq"],
                                   request_text="hi", hit_count=2)
        return {"results": []}
    monkeypatch.setitem(server.EXECUTORS, "knowledge.search", _exec)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_search",
          "arguments": {"collection": "faq", "query": "hi"}})
    assert len(logged) == 1
    assert logged[0]["tool"] == "ai.search" and logged[0]["hit_count"] == 2


def test_a_refused_call_writes_no_row(logged):
    _rpc(TestClient(_app()), "tools/call", {"name": "spend_summarize", "arguments": {}})
    assert logged == []


def test_a_failing_call_is_logged_as_an_error(logged, monkeypatch):
    async def _boom(params, user):
        raise RuntimeError("nope")
    monkeypatch.setitem(server.EXECUTORS, "knowledge.list_collections", _boom)
    _rpc(TestClient(_app()), "tools/call",
         {"name": "knowledge_list_collections", "arguments": {}})
    assert len(logged) == 1 and logged[0]["outcome"] == "error"
```

Note the `logged` fixture asserts on `via` — `tool_call_log.record` is monkeypatched, so `via` must be passed explicitly by the dispatcher rather than left to the ContextVar default. Write the dispatcher accordingly.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_server.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'server' from 'app.mcp'`.

- [ ] **Step 3: Write the module**

```python
# backend/app/mcp/server.py
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
from app.chat.actions import Action, ActionKind, InvalidParams, UnknownAction
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
    action_id = tools.action_id_for(name)
    if action_id is None:
        return None
    try:
        action = resolve_action(action_id)
    except UnknownAction:
        return None
    return action if action.kind is ActionKind.READ else None


async def _log_fallback(rows_written: int, action: Action, params: dict,
                        user: dict, outcome: str, started: float) -> None:
    """A row for a call the inner path did not log — the twenty-three actions whose
    executors never reach an /ai/* route. Where one did, its row is richer and stands."""
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
        return JSONResponse(protocol.result(request_id, protocol.tools_list_result(
            tools.descriptors(held_permissions(user),
                              compute_capabilities(os.environ)))))

    if method == "tools/call":
        return JSONResponse(protocol.result(
            request_id, await _call_tool(params, user)))

    return JSONResponse(protocol.error(
        request_id, protocol.METHOD_NOT_FOUND, f"Unknown method: {method}"))
```

Before running: confirm `UnknownAction` and `InvalidParams` are importable from `app.chat.actions` (grep for their `class` definitions) and that `from app.chat.executors import EXECUTORS` resolves. Fix the import paths to what the code actually exports; do not invent names.

- [ ] **Step 4: Mount it in `main.py`**

Beside the other router imports (~line 49):
```python
from app.mcp.server import router as mcp_router
```
Beside the other `include_router` calls (~line 409):
```python
app.include_router(mcp_router, prefix="/api")
```

- [ ] **Step 5: Run the tests, the route inventory, and the app import**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_server.py tests/test_route_authorization_inventory.py tests/test_api_surface.py -q -p no:cacheprovider && .venv/bin/python -c "import main"`
Expected: PASS, and the import prints only the usual insecure-dev-key warnings with no traceback.

`test_route_authorization_inventory.py` scans **mutating** routes for a permission dependency. `POST /api/mcp` is a POST, so it will be scanned. It carries authentication (`resolve_principal` → `require_user`) but no `require_permission` — the permission is per-tool, checked inside. Add it to that test's exception list with exactly that reason, in the file's existing format. Do not weaken the test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/mcp/server.py backend/main.py backend/tests/test_mcp_server.py backend/tests/test_route_authorization_inventory.py
git commit -m "feat(mcp): the endpoint — scoped tool list, read-only dispatch, one row per call"
```

---

### Task 6: 24 parameter descriptions, and the test that keeps them

**Files:**
- Modify: `backend/app/chat/analysis/{audit,catalog,connectors,governance,knowledge,pipelines,platform,query,spend}.py`
- Modify: `backend/tests/test_mcp_tools.py` (add one test)

**Interfaces:** no signature changes — only `Field(description=...)` on existing fields.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_mcp_tools.py`:

```python
def test_every_exposed_field_is_described():
    """A client's model sees the JSON Schema and nothing else. A field it has to guess
    at is a field it fills in wrong, so an undescribed parameter is an unshipped tool."""
    missing = []
    for action in tools.exposed_actions(ALL_PERMS, ALL_CAPS):
        for field_name, field in action.params.model_fields.items():
            if not (field.description or "").strip():
                missing.append(f"{action.id}.{field_name}")
    assert not missing, "undescribed parameters: " + ", ".join(sorted(missing))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_tools.py::test_every_exposed_field_is_described -q -p no:cacheprovider`
Expected: FAIL listing 31 entries (24 distinct fields; several actions share a model).

- [ ] **Step 3: Describe every field**

Each field below keeps its current type, default and constraints — add only `description=`. Where a field is currently a bare annotation (`table: Optional[str] = None`), convert it to `Field(default=None, description=...)`; where it is already a `Field(...)`, add the keyword. Import `Field` from pydantic in any module that lacks it.

| Module | Model.field | Description |
|---|---|---|
| `audit.py` | `AuditWindow.days` | `"How many days back to summarise, 1-90. Defaults to 7."` |
| `catalog.py` | `TableRef.namespace` | `"The table's namespace (schema), as listed by catalog_find_tables."` |
| `catalog.py` | `TableRef.table` | `"The table's name within the namespace, without the namespace prefix."` |
| `catalog.py` | `RelationshipQuery.table` | `"Limit to relationships involving this table, written namespace.table. Omit for every relationship the catalog knows."` |
| `catalog.py` | `RelationshipQuery.days` | `"How many days of query history to infer relationships from. Defaults to 30."` |
| `catalog.py` | `TableSearch.query` | `"Words to match against table and column names, for example 'orders customer'."` |
| `connectors.py` | `ConnectionRef.connection_id` | `"The source's id, as listed by connectors_list_sources."` |
| `connectors.py` | `ConnectionHistory.connection_id` | `"The source's id, as listed by connectors_list_sources."` |
| `connectors.py` | `ConnectionHistory.limit` | `"How many records to return, 1-100. Defaults to 20, newest first."` |
| `governance.py` | `PolicyQuery.table` | `"Limit to policies on this table, written namespace.table. Omit for every policy."` |
| `knowledge.py` | `KnowledgeQuery.collection` | `"The collection's name, as listed by knowledge_list_collections."` |
| `knowledge.py` | `KnowledgeQuery.query` | `"The question or phrase to search for, in the words a person would use."` |
| `knowledge.py` | `CollectionRef.collection` | `"The collection's name, as listed by knowledge_list_collections."` |
| `knowledge.py` | `CollectionSearch.q` | `"Match collection names containing this text. Omit to list them all."` |
| `knowledge.py` | `CollectionSearch.limit` | `"How many collections to return, 1-100. Defaults to 25."` |
| `pipelines.py` | `PipelineRuns.pipeline` | `"The pipeline or transform's name, as shown on the Transforms page."` |
| `pipelines.py` | `PipelineRuns.limit` | `"How many runs to return, 1-50. Defaults to 10, newest first."` |
| `platform.py` | `EventWindow.hours` | `"How many hours back to look, 1-2160 (90 days). Defaults to 168 (7 days)."` |
| `platform.py` | `EventWindow.limit` | `"How many events to return, 1-200. Defaults to 50, newest first."` |
| `platform.py` | `EventWindow.severity` | `"Return only events of this severity, for example 'critical'. Omit for every severity."` |
| `platform.py` | `ServiceRef.service` | `"Which service to inspect, by the name Infrastructure lists — for example 'minio', 'airflow', 'mlflow'."` |
| `query.py` | `SqlText.sql` | `"The SQL statement to explain. It is analysed, not executed."` |
| `query.py` | `NaturalQuestion.question` | `"What you want to know, in plain language. The answer is SQL, which is not run."` |
| `spend.py` | `SpendWindow.days` | `"How many days back to compare, 1-90. Defaults to 7."` |
| `spend.py` | `SpendQuery.days` | `"How many days of spend to summarise. Defaults to 30."` |

Two descriptions state a bound the field does not enforce (`RelationshipQuery.days` and `SpendQuery.days` have no `ge`/`le`); they say "Defaults to N" only, as written above. Do not add constraints — that would change the API.

- [ ] **Step 4: Run the tools test and every chat test**

Run: `cd backend && .venv/bin/python -m pytest tests/test_mcp_tools.py tests -q -p no:cacheprovider -k "mcp or chat"`
Expected: PASS. Descriptions appear in `model_json_schema()`, which `tool_definitions` also renders — if a chat test pins an exact schema, update it to include the new `description` keys and say so in the report.

- [ ] **Step 5: Commit**

```bash
git add backend/app/chat/analysis backend/tests/test_mcp_tools.py
git commit -m "feat(mcp): every exposed parameter says what it is and where the value comes from"
```

---

### Task 7: Documents

**Files:**
- Create: `docs/MCP.md`
- Modify: `README.md` (roadmap → Shipped), `docs/README.md` (doc index), `docs/POSITIONING_FIT_AUDIT.md` (§7.1 축 A row, §6.8 rank 4), `docs/UPGRADING.md` (new entry), `frontend/app/connect/page.tsx` (one card)

- [ ] **Step 1: Write `docs/MCP.md`**

```markdown
# MCP server

DataPond speaks the Model Context Protocol at `POST /api/mcp`, so an agent can discover
its tools instead of being wired to them by hand.

**Read-only.** The 26 read actions are exposed; nothing that writes is reachable, by
three separate refusals. Changing configuration or data still goes through the console
or the typed REST endpoints.

**Protocol.** 2026-07-28, stateless HTTP. One endpoint, no session.

**Authentication.** The service-account key you already use for REST:
`Authorization: Bearer dp_sk_…`. Issue one under Settings → Service accounts with the
scopes the agent needs — `knowledge:read` and `ai:generate` cover search and cited
answers. OAuth is not supported yet, so hosted clients that require it cannot connect.

## Point an agent at it

    curl -sX POST https://<your-deployment>/api/mcp \
      -H "Authorization: Bearer $DATAPOND_KEY" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

The list is the caller's own: a key holding only `knowledge:read` sees the knowledge
tools and nothing else, and a tool whose component this deployment does not run is
absent for everyone. A tool you may not use is indistinguishable from one that does not
exist — that is deliberate, so a call cannot be used to enumerate your scopes.

## What it costs

`knowledge_answer_with_citations` and `query_generate_sql` call a model, and that spend
is attributed to the calling service account exactly as it is over REST. The other
tools read from PostgreSQL and the configured adapters.

## What it records

Every call writes one row to `tool_call_log` with `via='mcp'`, visible under
`GET /api/audit/tool-calls` and in Governance → Reports → Agent tool calls. Calls that
read a collection carry the collection, the hit count, the cited sources and the number
of PII matches masked; the rest carry the tool, the caller and the outcome.

## Limits

- Read-only, and no write action will be added without the approval gate the console has.
- No per-key rate limit yet; an agent loop can call as fast as it likes.
- `prompts` and `resources` are not implemented. Tools only.
```

- [ ] **Step 2: Update the other documents**

- `README.md`: under **Roadmap or hardening**, delete the bullet beginning `- Read-only MCP server (2026-07-28 spec)` and add under **Shipped**: `- Read-only MCP server at POST /api/mcp (2026-07-28 stateless HTTP): the 26 read actions as tools, scoped by the calling key, one audit row per call`.
- `docs/README.md`: add `| [MCP.md](MCP.md) | MCP 서버 — 도구 목록, 인증, 감사, 한계 |` to the 먼저 읽을 문서 table.
- `docs/POSITIONING_FIT_AUDIT.md`: §7.1 축 A, the `MCP 엔드포인트` row → ○, 근거 `backend/app/mcp/`, 갭 `—`. In §6.8, strike rank 4's line and note it landed. Leave §7.2's totals alone — reconcile them in one pass when the next plan finishes, as the sovereign-core ledger's ruling set out.
- `docs/UPGRADING.md`: a new dated entry at the top:
  ```markdown
  ## 2026-09 — An MCP endpoint, read-only, on the key you already have

  `POST /api/mcp` speaks MCP 2026-07-28 and exposes the 26 read actions as tools,
  authenticated with a service-account key. Nothing that writes is reachable. Each call
  writes one `tool_call_log` row with `via='mcp'`; migration 0009 widens that table's
  `tool` constraint so a row can name the action it logged. No configuration is
  required and nothing changes for a deployment that does not use it.
  ```
- `frontend/app/connect/page.tsx`: one card above the generated endpoint list — heading "MCP", the endpoint, the same `Authorization: Bearer $DATAPOND_KEY` header, and a link to the guide. Follow the file's existing card markup; do not restructure the page.

- [ ] **Step 3: Full verification**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider` (expect **1706 + the new tests, 0 failed**), then `cd ../frontend && npm test && npm run lint && npm run build` (lint: only the known baseline — one error in `components/chat/assistant-panel.tsx`, one warning in `app/query/page.tsx`).

- [ ] **Step 4: Commit**

```bash
git add docs/MCP.md README.md docs/README.md docs/POSITIONING_FIT_AUDIT.md docs/UPGRADING.md frontend/app/connect/page.tsx
git commit -m "docs(mcp): the endpoint, what it exposes, and what it refuses"
```
