# MCP read server — design

**Status:** approved in conversation 2026-09-09, not yet implemented.
**Closes:** `docs/POSITIONING_FIT_AUDIT.md` §6.8 rank 4 ("read 전용 MCP 서버") and §7.1 축 A row
"MCP 엔드포인트".
**Positioning it serves:** `docs/PRODUCT_CONCEPT.md` v6.0 — a governed data tool server that agents
call directly. Today they call REST with a service-account key; this adds the protocol that lets an
agent *discover* those tools instead of being hand-wired to them.

## 1. What this is

A read-only Model Context Protocol server at `POST /api/mcp`, speaking the 2026-07-28 stateless HTTP
protocol, exposing the 26 `READ` actions already in `app/chat/actions.py` as MCP tools. An agent
authenticates with the service-account key it already uses for REST, lists the tools its key's scopes
allow, and calls them. Every call leaves exactly one `tool_call_log` row.

It adds no new capability to the product. Everything reachable through MCP is reachable today through
the typed REST endpoints; what changes is that the agent learns the tool list and its schemas from the
server rather than from code someone wrote by hand.

### 1.1 Answering the objection already in the codebase

`app/api/auth.py:require_human` refuses service accounts on the assistant panel and gives reasons:

> An agent already calls the typed endpoints; routing it through a model to pick an action adds
> nondeterminism and a second round of token spend, and leaves the audit trail unable to name an
> approver.

Each clause is about the chat panel, and each stops applying here:

- **A second round of token spend.** In the chat panel, DataPond calls a model to choose an action. In
  MCP the *client's* model chooses; DataPond runs no model to dispatch. There is no second round.
  (`knowledge.answer_with_citations` and `query.generate_sql` do spend model tokens, but that is the
  tool's own work, attributed to the caller, exactly as over REST.)
- **Nondeterminism.** Same tool, same parameters, same executor as the REST path. The nondeterminism
  is in the agent, and it is the agent's own.
- **No approver in the audit trail.** Only write actions need an approver. This server exposes reads
  only, and §5 makes that structural rather than a promise.

`require_human` stays exactly as it is. The chat panel remains people-only; MCP is a different surface
with a different gate.

## 2. Decisions

| Question | Decision | Why |
|---|---|---|
| Authentication | Service-account key (`Authorization: Bearer dp_sk_…`) now; OAuth resource-server is a follow-up spec | Zero new auth code; the seam in §4.3 makes the swap local |
| Tool set | All 26 `READ` actions; the key's scopes decide what a caller sees | The permission and capability gates already exist and are enforced twice |
| Audit | Exactly one `tool_call_log` row per call, `via='mcp'` | §6 |
| Implementation | Hand-rolled JSON-RPC, no SDK | §2.1 |
| Protocol version | `2026-07-28` only, stateless HTTP | AgentCore Gateway supports it; older versions need session/SSE machinery for clients that would need OAuth anyway |
| Mount | `POST /api/mcp` inside the existing FastAPI app | `/api/` is what `AuthMiddleware` protects and what the NetworkPolicy admits |

### 2.1 Why not the official SDK

Measured on 2026-09-09 against this repo's pinned stack (`fastapi==0.109.0`, `pydantic==2.5.3`,
starlette 0.35.1):

- Installing `mcp` 2.2.0 resolved starlette to 1.6.0 and broke FastAPI's `starlette<0.36` pin.
- The real blocker is deeper: **every** published SDK version requires `pydantic>=2.7.2`, and 2.2.0 —
  the only line speaking 2026-07-28 — requires `pydantic>=2.12.0`, plus `sse-starlette>=3.0.0` and
  `httpx2>=2.5.0` as new transitive dependencies.
- pydantic 2.5 → 2.12 changes `model_json_schema()` output, which `chat/actions.py:tool_definitions`
  and `tests/test_api_surface.py` both depend on, and puts all 1706 backend tests in scope.

Adopting the SDK is therefore a web-stack modernisation project, not part of a read-only MCP server.
It may still be worth doing; it is not this. The transport boundary in §4.1 keeps the swap cheap if
that project happens later.

## 3. What an agent sees

```
POST /api/mcp   Authorization: Bearer dp_sk_…   Content-Type: application/json

→ {"jsonrpc":"2.0","id":1,"method":"initialize",
   "params":{"protocolVersion":"2026-07-28","capabilities":{},"clientInfo":{...}}}
← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2026-07-28",
   "capabilities":{"tools":{}},"serverInfo":{"name":"datapond","version":"…"}}}

→ {"jsonrpc":"2.0","id":2,"method":"tools/list"}
← {"jsonrpc":"2.0","id":2,"result":{"tools":[
     {"name":"knowledge_search","description":"…","inputSchema":{…}}, …]}}

→ {"jsonrpc":"2.0","id":3,"method":"tools/call",
   "params":{"name":"knowledge_search","arguments":{"collection":"faq","query":"…"}}}
← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{…}"}],"isError":false}}
```

The tool list is per-caller: a key holding only `knowledge:read` and `ai:generate` sees the knowledge
tools and nothing else. Tools whose capability is off in this deployment are absent for everyone.

## 4. Components

New package `backend/app/mcp/`, three modules with one job each, plus one shared function extracted
from the chat gate.

### 4.1 `protocol.py` — the wire, and nothing else

Pure functions over dicts. Knows JSON-RPC 2.0 and the three MCP methods; knows nothing about actions,
users, or the database.

```python
PROTOCOL_VERSION = "2026-07-28"

class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None): ...

# Standard codes used: -32700 parse, -32600 invalid request, -32601 method not found,
# -32602 invalid params. Tool *execution* failures are not JSON-RPC errors — see §7.

def parse_request(body: Any) -> tuple[Any, str, dict]:      # (id, method, params)
def result(request_id: Any, payload: dict) -> dict
def error(request_id: Any, code: int, message: str) -> dict
def initialize_result(server_name: str, server_version: str) -> dict
def tools_list_result(tools: list[dict]) -> dict
def tool_call_result(payload: Any, is_error: bool = False) -> dict
```

Notifications (a request with no `id`) get no response body; the route answers `202` with an empty
body, per the spec's stateless HTTP transport.

This module is where a future SDK swap lands: everything above it deals in Python dicts that the SDK
would produce instead.

### 4.2 `tools.py` — registry → tool descriptors

```python
def mcp_name(action_id: str) -> str          # "knowledge.search" -> "knowledge_search"
def action_id_for(mcp_name: str) -> str | None
def exposed_actions(permissions, capabilities) -> list[Action]   # READ only
def descriptors(permissions, capabilities) -> list[dict]         # name/description/inputSchema
```

**Naming.** Action ids contain dots. The MCP spec does not forbid them, but common clients and
gateways validate tool names against `^[a-zA-Z0-9_-]{1,64}$`, and AWS documents that a name outside a
model's ToolSpec constraints fails at invocation time rather than registration. Dots become
underscores. The map is built once from the registry and asserted collision-free and round-trip-exact
by a test, so a future action id cannot silently shadow another.

**Schema.** `action.params.model_json_schema()`, the same call `tool_definitions` already makes, with
`additionalProperties: false` and the `title` key dropped. The MCP field is `inputSchema` (camelCase),
not `input_schema`; `tool_definitions` keeps its Anthropic-shaped output for the chat panel and is not
changed.

**READ only.** `exposed_actions` filters `kind is ActionKind.READ` on top of `actions_for`'s permission,
page (`"*"`) and capability filters. A non-read action is not merely unlisted: §5 refuses it again at
call time.

### 4.3 `server.py` — the router

```python
router = APIRouter()

@router.post("/mcp")
async def mcp_endpoint(request: Request) -> Response
```

One route, because stateless MCP is one route. It:

1. resolves the principal (§4.4),
2. parses the envelope (`protocol.parse_request`),
3. dispatches `initialize` / `tools/list` / `tools/call`,
4. returns the JSON-RPC response.

Registered in `backend/main.py` beside the other routers with `prefix="/api"`, so `AuthMiddleware`
covers it exactly as it covers every other `/api/` path.

### 4.4 The authentication seam

```python
async def resolve_principal(request: Request) -> dict   # the user dict, or raises 401
```

The only function that knows what a credential looks like. Today it delegates to the same bearer
resolution the REST routes use, so a `dp_sk_` key and a person's JWT both work and both arrive as the
same user dict (`id`, `username`, `role`, optional `permissions`, `auth_method`). The OAuth follow-up
replaces this function's body and nothing else.

A missing or invalid credential is HTTP 401 with no JSON-RPC body — the request never became a
protocol message.

### 4.5 `app/chat/authz.py` — the one shared fact

Extracted from `gate._authorize`, which today interleaves the decision with chat-shaped audit writes:

```python
class NotPermitted(Exception): ...     # carries action, required permission
class CapabilityOff(Exception): ...    # carries action, required capability

def held_permissions(user: dict) -> set        # moved verbatim from gate._held_permissions
def authorize(action: Action, user: dict) -> None
```

`authorize` raises or returns; it takes no store, writes no audit, and calls
`component_guard.capability_on` for the capability half — the same predicate the route guards use, read
from the server's own environment rather than from anything a client sent.

`gate._authorize` becomes a wrapper: call `authorize`, catch, write its `chat_action_refused` audit
event, re-raise as `ActionRefused`. Chat behaviour is unchanged — a test asserts the same refusals as
before. The MCP dispatcher calls `authorize` directly and records its own way.

This is the whole of the sharing. The chat gate keeps its invocation store, its approval flow, its
`named_by_user` evidence and its audit vocabulary; MCP borrows none of it.

## 5. The read-only boundary

Three independent reasons a write action cannot be called through this server:

1. `exposed_actions` filters to `kind is READ`, so it is never listed.
2. `tools/call` re-resolves the name and refuses anything whose kind is not READ, with the same
   response an unknown name gets (§7).
3. The dispatcher never touches `gate.propose`, so no invocation record, no approval endpoint and no
   `approve()` path exists for an MCP caller to reach.

Write actions arrive only with the destructive gate they were designed for — a person, a typed target,
and an approver in the audit trail — which is a separate spec if it is ever wanted.

## 6. Audit — one row per call, and the rich one wins

Every MCP call writes exactly one `tool_call_log` row. Getting there needs one observation: three of the
26 exposed actions reach route functions that *already* write a rich row (collection, hit count, cited
sources, PII masked) — `knowledge.search`, `knowledge.answer_with_citations` and `query.generate_sql`,
whose executors call the public `/ai/*` wrappers. `query.explain_plan` resolves to
`app.api.plan_review.review` and writes nothing; `query.run`, which does reach the logging
`execute_query`, is `CREATE` and therefore not exposed. Suppressing the rich rows and writing a flat one
at the MCP boundary would trade information for uniformity.

So the dispatcher counts instead of suppressing:

```python
# app/tool_call_log.py — additions beside the existing `via` ContextVar
_calls: ContextVar[Optional[list]] = ContextVar("tool_call_count", default=None)

@contextmanager
def counting() -> Iterator[Callable[[], int]]:
    """Count rows written inside this block. The MCP dispatcher writes a fallback row
    only when the inner path wrote none — so a data tool keeps its rich row and a
    diagnostic tool still leaves a trace."""
```

`record()` increments the counter when one is set. The dispatcher runs the executor inside
`via("mcp")` and `counting()`, then writes its own row **iff** the count is zero:

| Action | Row written by | `tool` value | Fields |
|---|---|---|---|
| `knowledge.search`, `knowledge.answer_with_citations` | the `/ai/*` route function | `ai.search`, `ai.rag` | collection, hits, cited sources, pii_masked |
| `query.generate_sql` | the `/ai/sql` route function | `ai.sql` | pii_masked |
| the other 23 | the MCP dispatcher | the action id, e.g. `catalog.find_tables` | `resource_kind='none'`, outcome, duration |

Both carry `via='mcp'` and the caller's identity, so `GET /api/audit/tool-calls/summary` and the
governance compliance report count MCP work without changing.

**Migration `0009_tool_call_log_tool_ids`** drops the `tool` CHECK constraint from `0008` and replaces
it with one that also admits registered action ids. Dropping a CHECK is not among the forms
`app/migration_rules.py` forbids (DROP TABLE/COLUMN, RENAME, SET NOT NULL). The constraint is rewritten
rather than removed: an unconstrained `tool` column would let a typo become a permanent audit row.
`via` needs no migration — `0008` left it unconstrained.

Failures are logged too, with `outcome='error'`, before the error result is returned. A call that was
refused at authorization writes **no** row: nothing was read, and the refusal belongs to
`security_audit_log`, which `require_permission` already writes for denials.

## 7. Errors

| Situation | Response |
|---|---|
| Body is not JSON | JSON-RPC `-32700` |
| Missing `jsonrpc`/`method` | `-32600` |
| Method other than the three | `-32601` |
| `tools/call` params fail `validate_params` | tool result with `isError: true`, message from `InvalidParams` |
| Unknown tool name | tool result with `isError: true`: *"No such tool: `<name>`."* |
| Known tool, caller lacks the permission or the capability is off | **the same response as unknown** |
| Known tool, not READ | **the same response as unknown** |
| Executor raises | tool result with `isError: true`, the exception message, and an `error` row in the log |
| No credential / bad credential | HTTP 401, no JSON-RPC body |

The three "same response" rows are the point: a caller learns a tool exists only by being allowed to
see it. This matches `actions_for`'s stated rule — *an action a caller cannot use is not filtered out
of a list they were shown; they never learn it exists.* Making refusal distinguishable from absence
would turn `tools/call` into an enumeration oracle for the deployment's capabilities and the key's
scopes.

Protocol-level errors are JSON-RPC errors; tool-level failures are results with `isError: true`. That
split is the spec's, and the tests pin it.

## 8. Parameter descriptions

The registry has field-level `description=` on roughly seven fields across 40 actions. For the chat
panel that was survivable — the action-level description carried the meaning and a person could clarify
in the next turn. For MCP it is not: the client's model sees the JSON Schema and nothing else, and a
field it has to guess at is a field it fills in wrong.

So every parameter of every exposed action gets a `description`, and
`tests/test_mcp_tools.py::test_every_exposed_field_is_described` fails on an empty one. Measured on
2026-09-09: 31 fields across 18 parameter models, none of them described today; five of the 26 actions
take no parameters at all. It is not optional — a tool a model cannot call correctly is not a shipped
tool — and it is the one task whose cost is proportional to the tool count rather than to the protocol.

Descriptions state what the value is and where it comes from ("the collection's name, as listed by
`knowledge_list_collections`"), not what the field is called.

## 9. Testing

| What | Where |
|---|---|
| JSON-RPC envelope, the three methods, notification handling | `tests/test_mcp_protocol.py` — pure, no app, golden messages from the spec |
| Name mapping: round-trip, collision-free, every exposed id maps | `tests/test_mcp_tools.py` |
| Every exposed field has a non-empty description | `tests/test_mcp_tools.py` |
| `authorize` agrees with `actions_for` for every action × permission set | `tests/test_chat_authz.py` — the parity that makes the extraction safe |
| Chat refusals unchanged after the extraction | the existing chat gate tests, untouched |
| Scoped key sees a short list; unscoped key sees more | `tests/test_mcp_server.py`, fake pool |
| Unknown, unauthorised and non-READ names give identical responses | `tests/test_mcp_server.py` |
| Exactly one log row per call; data tools keep rich fields; the other 23 get the fallback | `tests/test_mcp_audit.py` |
| Migration text: CHECK rewritten, action ids admitted | `tests/test_mcp_migration.py` |

No database: fake pools throughout, migrations asserted as SQL text, per this repo's convention.

## 10. Documentation

- `docs/MCP.md` — what the server is, how to point an agent at it, the tool list, the audit guarantee,
  and the two limits stated plainly: read-only, and service-account keys until OAuth lands.
- `frontend/app/connect/page.tsx` — one card naming the MCP endpoint beside the REST list, with the
  same key.
- `docs/POSITIONING_FIT_AUDIT.md` §7.1 축 A "MCP 엔드포인트" row flips to ○; §6.8 rank 4 is struck.
- `README.md` roadmap: the MCP bullet moves to Shipped, with "read-only, key-authenticated" attached.

## 11. Out of scope, deliberately

- **OAuth resource-server mode.** Its own spec. §4.4 is the seam it lands in.
- **Write actions.** They need the destructive gate: a person, a typed target, an approver.
- **Per-key rate limiting.** Ranked P2 in the fit audit and still unbuilt for REST; MCP inherits that
  gap rather than creating it. The rows §6 writes are what a later limit would be sized from.
- **MCP `prompts` and `resources`.** Tools only.
- **AgentCore Gateway target registration.** A customer runbook, not product code; §10's document
  describes the endpoint a gateway would point at.
