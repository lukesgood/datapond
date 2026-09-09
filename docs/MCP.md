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
needs — `knowledge:read` and `ai:generate` cover search and cited answers. OAuth is not
supported yet, so hosted clients that require it cannot connect; `resolve_principal` in
`app/mcp/server.py` is where that would land.

## Point an agent at it

    curl -sX POST https://<your-deployment>/api/mcp \
      -H "Authorization: Bearer $DATAPOND_KEY" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

The list is the caller's own: a key holding only `knowledge:read` sees the knowledge
tools and nothing else, and a tool whose component this deployment does not run is
absent for everyone — capabilities come from the server's own environment, never from
the request. A tool you may not use is indistinguishable from one that does not exist —
that is deliberate, so a call cannot be used to enumerate your scopes or this
deployment's components.

## What it costs

`knowledge_answer_with_citations` and `query_generate_sql` call a model, and that spend
is attributed to the calling service account exactly as it is over REST — the MCP
executors call the same underlying functions the REST routes do. The other tools read
from PostgreSQL and the configured adapters.

A few advertised parameters do not shape their result yet, and their descriptions say
so: `catalog.explain_relationships`'s `days` (relationships come from column naming, not
query history), `catalog.find_tables`'s `query` (matches table and namespace names only,
not columns), and `spend.summarize`'s `days` (the summary is always all-time).

## What it records

Every call writes one row to `tool_call_log` with `via='mcp'`, visible under
`GET /api/audit/tool-calls` and in Governance → Reports → Agent tool calls. A refused
call — unknown tool, unauthorized tool, or write action — writes no row. Calls that read
a collection carry the collection, the hit count, the cited sources and the number of
PII matches masked; the rest carry the tool, the caller and the outcome. An action whose
REST route already writes a row keeps that richer one; the MCP dispatcher does not add a
duplicate.

## Limits

- Read-only, and no write action will be added without the approval gate the console has.
- No per-key rate limit yet; an agent loop can call as fast as it likes.
- No enforced per-caller budget on this path — spend is attributed and reported, not capped.
- `prompts` and `resources` are not implemented. Tools only.
