# MCP server

DataPond speaks the Model Context Protocol at `POST /api/mcp`, so an agent can discover
its tools instead of being wired to them by hand.

**Read-only.** The 26 read actions are exposed; nothing that writes is reachable, by
three separate refusals. Changing configuration or data still goes through the console
or the typed REST endpoints.

**Protocol.** 2026-07-28, stateless HTTP. One endpoint, no session.

**Authentication.** The service-account key you already use for REST:
`Authorization: Bearer dp_sk_…`. A person's own session token works too, resolved the
same way. Issue a key under Settings → Service accounts with the scopes the agent
needs — `knowledge:read` and `ai:generate` cover search and cited answers.

**OAuth (optional).** With `auth.oauthResourceServer.enabled`, the endpoint also accepts
access tokens from your IdP (Okta custom authorization server, Entra ID, Cognito), which
is what OAuth-only MCP clients and AgentCore Gateway's token exchange send. A 401 says
where the protected resource metadata is (`/.well-known/oauth-protected-resource/api/mcp`,
RFC 9728), which names your IdP as the authorization server. Three rules:

- The token's audience must be this deployment (`https://<domain>` or
  `https://<domain>/api/mcp`, or `audiences`); a Cognito token without `aud` is accepted
  only for a client listed in `clientIds`.
- The subject must match a DataPond user that already exists: a person who signed in
  through SSO (or whose `external_id` an admin set — Entra deployments match on `oid`),
  or a service account linked to the token's client with
  `PUT /api/service-accounts/{id}/oauth-client`. Nothing is created from a token.
- Permissions are the user's role narrowed by the token's `datapond:<permission>` scopes
  (`datapond:knowledge:read`, `datapond:ai:generate`, …). A token with none gets
  `403 insufficient_scope`, and a refused permission names the scope to request.

The token is validated and never forwarded; model calls use DataPond's own gateway key.
OAuth callers share the per-caller request budget of API keys.

## Point an agent at it

    curl -sX POST https://<your-deployment>/api/mcp \
      -H "Authorization: Bearer $DATAPOND_KEY" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

The list is the caller's own: a key holding only `knowledge:read` sees collection
metadata (list, composition, freshness diagnosis) but not `knowledge_search` or
`knowledge_answer_with_citations` — both spend a model call, so both need
`ai:generate` — and a tool whose component this deployment does not run is absent for
everyone, since capabilities come from the server's own environment, never from the
request. A tool you may not use is indistinguishable from one that does not exist —
that is deliberate, so a call cannot be used to enumerate your scopes or this
deployment's components.

## What it costs

`knowledge_search`, `knowledge_answer_with_citations` and `query_generate_sql` call a
model — `knowledge_search` embeds the query, plus a rerank call when `AI_RERANK_MODEL`
is configured, and it is the highest-volume tool on this surface. That spend is
attributed to the calling service account exactly as it is over REST — the MCP
executors call the same underlying functions the REST routes do. The other tools read
from PostgreSQL and the configured adapters. `knowledge_search` and
`knowledge_answer_with_citations` both need `ai:generate`, not `knowledge:read` alone.

A few advertised parameters do not shape their result yet, and their descriptions say
so: `catalog.explain_relationships`'s `days` (relationships come from column naming, not
query history), `catalog.find_tables`'s `query` (matches table and namespace names only,
not columns), and `spend.summarize`'s `days` (the summary is always all-time).

## What it records

Every call writes one row to `tool_call_log` with `via='mcp'`, visible under
`GET /api/audit/tool-calls` and in Governance → Reports → Agent tool calls. A refused
call — unknown tool, unauthorized tool, or write action — writes a row with
`outcome='refused'` (an unknown name is logged as `mcp.unknown_tool`). Calls that read
a collection carry the collection, the hit count, the cited sources and the number of
PII matches masked; the rest carry the tool, the caller and the outcome. An action whose
REST route already writes a row keeps that richer one; the MCP dispatcher does not add a
duplicate.

## Limits

- Read-only, and no write action will be added without the approval gate the console has.
- Each key or OAuth caller has a request rate limit (`API_KEY_RATE_LIMIT_PER_MINUTE`,
  default 600, per replica); over it, the call gets 429 with `Retry-After`.
- A per-caller spend budget, when set, is enforced on the model calls behind these tools:
  over it, the call gets 402 and a refused audit row.
- `prompts` and `resources` are not implemented. Tools only.
