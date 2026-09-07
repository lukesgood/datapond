# Positioning gap closure — design

**Status:** proposed · 2026-09-07 · closes the three gaps named in `docs/POSITIONING_FIT_AUDIT.md` §7.2
**Positioning it serves:** `docs/PRODUCT_CONCEPT.md` v6.0 — a governed data tool server that agents call
directly, with per-caller collection/row access, citation- and masking-level audit, and per-caller spend.

## 1. What this is

Three independent pieces, one per plan. Each ships on its own and makes one false or missing
claim in the positioning true.

| Piece | Claim it makes true | Plan |
|---|---|---|
| A. Tool call log | "what was cited and what was masked, per caller" — today no successful `/ai/search`, `/ai/rag`, `/ai/sql` or `/queries/execute` call leaves an audit row | `2026-09-07-tool-call-log.md` |
| B. Agent onboarding journey | "agents call it directly with a scoped service-account key" — today the UI issues keys with no scopes and no expiry, and nothing points from a collection to "use this from your app" | `2026-09-07-agent-onboarding.md` |
| C. Sovereign core profile | "on-prem is the one place AWS native cannot go" — today the only on-prem profile enables all eight unsupported add-ons and is labelled `community` | `2026-09-07-sovereign-core-profile.md` |

Out of scope, deliberately: MCP server, OIDC resource-server mode, per-caller budget enforcement,
chunk-level filters, gateway OpenAPI subset, UI copy replacement. Each is listed in the audit with its
own rank; none is a precondition for these three.

## 2. Piece A — tool call log

### 2.1 Decision

A new table `tool_call_log`, separate from `security_audit_log`. The existing table records
authorization *decisions* and its writer deliberately skips `query:run`/`ai:generate` allows to keep
read paths free of a DB write (`app/security_audit.py` header). That decision stays: the new log is
a different fact ("a tool returned data") with different columns, and mixing them would either bloat
every auth decision row with nulls or force the auth writer to learn about collections.

### 2.2 Row

```sql
CREATE TABLE public.tool_call_log (
    id             bigserial PRIMARY KEY,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    actor_id       uuid REFERENCES public.users (id) ON DELETE SET NULL,  -- service accounts are users; nullable like security_audit_log (internal principal has no id)
    actor_username text        NOT NULL,
    actor_kind     text        NOT NULL CHECK (actor_kind IN ('human','service')),
    tool           text        NOT NULL CHECK (tool IN ('ai.search','ai.rag','ai.sql','query.execute')),
    resource_kind  text        NOT NULL CHECK (resource_kind IN ('collection','tables','none')),
    resource       text[]      NOT NULL DEFAULT '{}',  -- collection name, or resolved table names
    request_hash   text        NOT NULL,           -- sha256 of the PII-masked question/SQL
    request_masked text,                           -- first 512 chars of the masked question/SQL
    hit_count      integer     NOT NULL DEFAULT 0,
    citation_sources text[]    NOT NULL DEFAULT '{}',  -- distinct `source` values returned
    pii_masked     integer     NOT NULL DEFAULT 0,
    outcome        text        NOT NULL CHECK (outcome IN ('ok','degraded','error')),
    duration_ms    integer,
    client_address text,                           -- text, as in security_audit_log
    via            text                            -- 'api' | 'ui' | 'chat'
);
CREATE INDEX tool_call_log_actor_time ON public.tool_call_log (actor_id, occurred_at DESC);
CREATE INDEX tool_call_log_time ON public.tool_call_log (occurred_at DESC);
```

Rules:

- **Masked before stored.** `request_masked` and `request_hash` are computed from the text *after*
  `pii_ko` masking, using the same guard the endpoint already applied. Nothing raw is written.
- **Never blocks the caller.** The writer catches and logs; a failed insert never fails the tool call
  (same contract as `security_audit.record`).
- **Service accounts cannot opt out.** `save_history=false` on `/queries/execute` continues to control
  the *user-facing* query history only; the tool call log is written regardless.
- **Append-only** by the same trigger + `REVOKE UPDATE` pattern as migration `0005`, with the same
  honesty note: the app role owns the table, so this is not WORM.
- **Retention** joins the existing prune (`app/audit_retention.py`), same floor and default.
- `outcome='degraded'` is `/ai/rag` with `has_ai=false` (hits returned, no answer).

### 2.3 Where it is written

| Endpoint | resource_kind / resource | hit_count | citation_sources | pii_masked |
|---|---|---|---|---|
| `POST /api/ai/search` | collection / [name] | `len(results)` | distinct `source` of results | response `pii_masked` |
| `POST /api/ai/rag` | collection / [name] | `len(citations)` | distinct `source` of citations | response `pii_masked` |
| `POST /api/ai/sql` | none / [] (generation only) | 0 | [] | response `pii_masked` |
| `POST /api/queries/execute` | tables / resolved qualified names | `row_count` | [] | 0 |

The chat panel's `knowledge.search` / `knowledge.answer_with_citations` executors call the same route
functions, so they are logged with `via='chat'` for free.

### 2.4 Read surfaces

- `GET /api/audit/tool-calls` — paged list, `audit:read`, filters `actor_id`, `tool`, `since`, `until`.
- `GET /api/audit/tool-calls/export` — NDJSON, same window semantics as `/audit/export`.
- The governance compliance report gains a fourth checkbox, **Agent tool calls**, whose section is the
  per-actor aggregate: calls, distinct collections/tables, total hits, total pii_masked, plus the raw rows
  when the window is small enough (same `capped` flag the report already uses).
- `audit.activity_summary` (chat action) includes tool-call counts.

### 2.5 Not in this piece

A per-caller screen ("this agent read these collections") — it is a consumer of this log and is the
audit's rank 8; it can be built once rows exist.

## 3. Piece B — agent onboarding journey

### 3.1 Decision

The first journey is *admin creates an agent identity and hands a key to a developer*. Everything in
this piece serves that: scoped and expiring keys in the UI, collection grants visible from the account,
a snippet on the collection, governed SQL visible on `/connect`, and a call-to-action that starts the
journey from the dashboard.

### 3.2 Changes

1. **Key issuance form** (`components/settings/service-accounts.tsx`): scope checkboxes seeded with the
   role's permissions (from `assignable`/effective permissions the backend already returns or computes),
   default-checked `knowledge:read` + `ai:generate`; an expiry select (30 / 90 / 365 days / no expiry)
   with **90 days** default. Posts `scopes` and `expires_in_days`. The backend already validates both.
2. **Account-side collection grants**: a new `GET /api/service-accounts/{id}/collections` returning the
   collections the account owns or is a member of, and the panel lists them with a link to each
   collection's Members tab. No new write path — grants stay on the collection, where the ACL lives.
3. **Collection "Use from your app" panel** (`components/knowledge/use-from-app-panel.tsx`): a tab on the
   collection page with a curl and a Python `requests` snippet for `/api/ai/search` and `/api/ai/rag`,
   collection name prefilled, key shown as `$DATAPOND_KEY`, and a one-line pointer to Settings →
   Service accounts.
4. **`/connect` surface**: `api_surface.py` keeps its `/api/ai/` prefix and adds an explicit allowlist
   for `POST /api/queries/execute` and `GET /api/ai/collections`, so governed SQL and collection
   discovery appear with the same generated curl.
5. **Dashboard step 04** becomes "Connect your agent" with a button to `/connect`.
6. **Help topic** "Integrate an application or agent": the four steps above in prose, service-key curl.

### 3.3 Not in this piece

MCP, OAuth, rate limits, key rotation, group membership.

## 4. Piece C — sovereign core profile

### 4.1 Decision

A new values file, `helm/datapond/values-sovereign-core.yaml`, is the on-prem twin of
`values-foundation.yaml`: backend, frontend, in-cluster PostgreSQL/pgvector, LiteLLM, Valkey, in-cluster
MinIO, and a local model path. All eight add-ons are stated `false`. Profile identity:

```yaml
product:
  profile:
    id: sovereign-core
    label: Sovereign Core
    maturity: supported-starter
    topology: kubernetes
```

`values-onprem.yaml` is untouched and stays `community`; it remains the extended stack.

### 4.2 Model path

LiteLLM maps `embed`, `chat`, `default` to an OpenAI-compatible endpoint given by one value
(`ai.llmEndpoint`), with Ollama in-cluster as the documented default. The embedding dimension must be
1024 to match `ai_chunks.embedding vector(1024)`; the file names a 1024-dimensional model and
`docs/SOVEREIGN_CORE_PROFILE.md` says what to do if a different model is chosen (new deployment or
full re-embed, never a version bump).

### 4.3 Proof

- `backend/tests/test_helm_addon_defaults.py` gains the profile in its per-profile Deployment pin: none
  of the eight add-on Deployments render; `minio` renders; `postgres` renders.
- CI's profile render/lint loop gains the file.
- `docs/DEPLOYMENT_PROFILES.md` gains the row; `docs/SOVEREIGN_CORE_PROFILE.md` mirrors
  `FOUNDATION_PROFILE.md`; `README.md` and `SUPPORT.md` name it as the supported on-prem starter.

### 4.4 Not in this piece

A live on-prem acceptance run (needs a self-hosted cluster; tracked separately), air-gap bundle refresh.

## 5. Acceptance across the three

- The positioning sentence's three lead claims each point at shipped code: access (existing), audit
  (Piece A), spend attribution (existing) — with budget *enforcement* still marked roadmap.
- `docs/POSITIONING_FIT_AUDIT.md` §7.1 rows for the items these pieces cover flip from ✕ to ○ in a
  follow-up edit after each plan lands.
