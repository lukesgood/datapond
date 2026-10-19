# Demo script — one collection, two agents, two different answers

A 15-minute customer demo of what DataPond does that an agent gateway does not: the
same question, asked by two agents against the same collection, returns different
chunks; an agent over its budget is refused; every call is on the record. An optional
step (2f) shows a governed metric: a number an agent can cite, with version and SQL.

Everything here runs against a deployment you control with an **administrator's signed-in
session** (the setup steps are admin-only and a key cannot perform them). The agent calls
use service-account keys, exactly as a customer's agents would.

## 0. What you need

- `DP=https://<your-deployment>` and `ADMIN="<admin session token>"` (sign in, then copy
  the token from the browser's `datapond_token` cookie).
- The Knowledge capability on (every profile has it).

```bash
H=(-H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json")
```

## 1. Setup (once, ~3 minutes)

**Two agents.** One for HR, one for Sales, each with a key scoped to reading knowledge
and generating answers.

```bash
HR_ID=$(curl -s "${H[@]}" -X POST $DP/api/service-accounts -d '{"name":"hr-agent"}' | jq -r .id)
SALES_ID=$(curl -s "${H[@]}" -X POST $DP/api/service-accounts -d '{"name":"sales-agent"}' | jq -r .id)

HR_KEY=$(curl -s "${H[@]}" -X POST $DP/api/service-accounts/$HR_ID/keys \
  -d '{"name":"demo","scopes":["knowledge:read","ai:generate"],"expires_in_days":7}' | jq -r .key)
SALES_KEY=$(curl -s "${H[@]}" -X POST $DP/api/service-accounts/$SALES_ID/keys \
  -d '{"name":"demo","scopes":["knowledge:read","ai:generate"],"expires_in_days":7}' | jq -r .key)

# The attribute the chunk rule will match on.
curl -s "${H[@]}" -X PATCH $DP/api/auth/users/$HR_ID    -d '{"attributes":{"department":"hr"}}'
curl -s "${H[@]}" -X PATCH $DP/api/auth/users/$SALES_ID -d '{"attributes":{"department":"sales"}}'
```

**One collection, documents from both departments.** Each document carries the
department in its metadata.

```bash
curl -s "${H[@]}" -X POST $DP/api/ai/collections -d '{"name":"company_handbook"}'
curl -s "${H[@]}" -X POST $DP/api/ai/collections/company_handbook/ingest -d '{"documents":[
  {"source":"hr/leave.md","metadata":{"dept":"hr"},
   "text":"Parental leave is 16 weeks at full pay. Salary bands are reviewed every March."},
  {"source":"sales/pricing.md","metadata":{"dept":"sales"},
   "text":"Enterprise discounts above 20 percent need VP approval. Q4 quota is 1.2M per rep."},
  {"source":"all/holidays.md","metadata":{"dept":"hr"},
   "text":"The office is closed on Chuseok and Seollal."}]}'

for u in hr-agent sales-agent; do
  curl -s "${H[@]}" -X POST $DP/api/ai/collections/company_handbook/members \
    -d "{\"username\":\"$u\",\"role\":\"reader\"}"
done
```

## 2. The demo

**a. Without a rule, both agents see everything.** Ask about salary as the Sales agent:

```bash
curl -s -H "Authorization: Bearer $SALES_KEY" -H "Content-Type: application/json" \
  -X POST $DP/api/ai/search -d '{"collection":"company_handbook","query":"salary review","k":3}' \
  | jq '.results[] | {source, content}'
```

The HR document comes back. This is the problem: collection-level access is all or
nothing.

**b. Turn on the chunk rule** — in the console (Knowledge → company_handbook → Chunk
access: metadata key `dept`, user attribute `department`) or:

```bash
curl -s "${H[@]}" -X PUT $DP/api/ai/collections/company_handbook/chunk-access \
  -d '{"metadata_key":"dept","user_attribute":"department"}'
```

**c. Same question, two agents, two answers.**

```bash
for K in "$HR_KEY" "$SALES_KEY"; do
  curl -s -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
    -X POST $DP/api/ai/rag -d '{"collection":"company_handbook","question":"When are salaries reviewed?"}' \
    | jq '{answer, cited: [.citations[].source]}'
done
```

HR gets "every March" with `hr/leave.md` cited. Sales is answered from Sales documents
only — no `hr/` source is cited, so the model has nothing to say about salaries. The Sales
agent is not told that a better passage exists; that would itself be a leak.

**d. A budget is enforced, not reported.** In the console (Agents → the Sales agent →
Spend → Set a cap) set its cap to `0`, or:

```bash
curl -s "${H[@]}" -X PUT $DP/api/settings/ai/budgets/$SALES_ID -d '{"max_budget":0}'
```

Re-run the Sales call from step c: it now answers **402**. Clear the cap afterwards
(`{"max_budget":null}`).

**e. Everything is on the record.** Governance → Reports → Agent tool calls, or:

```bash
curl -s "${H[@]}" "$DP/api/audit/tool-calls?limit=10" \
  | jq '.rows[] | {actor_username, tool, outcome, hit_count, chunks_withheld, citation_sources}'
```

Point at three columns: who called, what was cited, and `chunks_withheld` — how many
nearer chunks the rule kept from that caller, recorded for the auditor and never
returned to the agent. The refused (402) call is there too.

**f. A number the agent can cite (governed SQL).** Needs the `query` capability (the
AWS Single-Node Reference has it: Glue/Athena). Uses the sample `orders` table; on
another catalog, change `catalog`, `base_table` and the columns.

Define and approve a metric (console: Metrics → New, then Approve), or as below. A
retired name cannot be reused, so for a second run pick a new name (`demo_order_count_2`).

```bash
curl -s "${H[@]}" -X POST $DP/api/semantic/metrics -d '{"name":"demo_order_count","label":"데모 주문 수","version":{"catalog":"AwsDataCatalog","base_table":"default.orders",
  "measure":"COUNT(*)","time_column":"ordered_at","grains":["month"],
  "dimensions":[{"name":"channel","column":"channel"},{"name":"customer_id","column":"customer_id"}]}}'
curl -s "${H[@]}" -X POST $DP/api/semantic/metrics/demo_order_count/versions/1/approve
```

Give the Sales agent a key that may read the catalog and run read-only queries, and ask
over MCP — the way an agent would:

```bash
SQL_KEY=$(curl -s "${H[@]}" -X POST $DP/api/service-accounts/$SALES_ID/keys \
  -d '{"name":"demo-sql","scopes":["catalog:read","query:run"],"expires_in_days":7}' | jq -r .key)

curl -s -H "Authorization: Bearer $SQL_KEY" -H "Content-Type: application/json" -X POST $DP/api/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"metric_query","arguments":
      {"metric":"demo_order_count","by":["customer_id"],"period":"2026-04-01..2026-08-31",
       "order_by":[{"field":"demo_order_count","desc":true}],"limit":5}}}' | jq .
```

Point at the citation: metric, version, who approved it, and the exact SQL that ran.
Ask it three times — the same five rows come back each time, ties included (the other
dimensions break ties), where a model writing its own SQL for "top 5 customers" varied
between runs. Then show the audit (step e): the call is a `metric.query` row citing
`metric:demo_order_count@v1`. Change the definition and approve v2: the next call cites v2,
and the v1 rows still say v1.

## 3. What to say

- A gateway decides **which tool** an agent may call. DataPond decides **which rows and
  chunks** that call may read, masks what it returns, and records what was cited.
- The rule is data-layer: it holds for REST, MCP (`POST /api/mcp`) and a gateway in
  front alike, and it holds for administrators too.
- Numbers come from definitions an administrator approved, with the version and SQL
  cited on every answer — the same RLS, masking and audit apply as to any query.
- It runs on the customer's AWS account (S3, Aurora, Bedrock) or fully on-prem (MinIO,
  Ollama) from the same chart.

## 4. Cleanup

```bash
curl -s "${H[@]}" -X DELETE $DP/api/ai/collections/company_handbook
curl -s "${H[@]}" -X DELETE $DP/api/service-accounts/$HR_ID
curl -s "${H[@]}" -X DELETE $DP/api/service-accounts/$SALES_ID
curl -s "${H[@]}" -X POST $DP/api/semantic/metrics/demo_order_count/retire   # if you made it in 2f
```

## Known limits to mention if asked

- A chunk rule relies on pgvector 0.8's iterative HNSW scan to fill k results from a small
  slice of a large collection. The live reference runs Aurora 15.19 / pgvector 0.8.2; on an
  older pgvector (Aurora < 15.12) DataPond falls back to a wider candidate list, which can
  still return fewer than k.
- OAuth resource-server mode (agents presenting the customer's IdP tokens instead of
  keys) is shipped but off by default and not yet exercised against a live IdP.
