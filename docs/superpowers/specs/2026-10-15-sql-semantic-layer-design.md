# SQL semantic layer: governed metric definitions with cited SQL

Status: design, 2026-10-15. Approved section by section in conversation with the product
owner; implementation waits for review of this written spec and of the plan that follows.
Background and the go/no-go reasoning: `docs/ONTOLOGY_GRAPHRAG_REVIEW.md` (candidate A).

## 0. Purpose

**Traceability.** A number an agent reports from governed SQL should carry a citation —
which metric definition, which version, who approved it — recorded in the audit log, the
same way a cited RAG answer names its source chunks. Consistency (the same question gives
the same number) and accuracy follow from this; they are consequences, not the goal.

Shape of the feature:

- **Core:** a deterministic tool, `metric_query(metric="revenue", by=["region"],
  period="last_month")`. No LLM. Same input, same SQL. The SQL is built as a sqlglot AST
  in the engine dialect and executed through the existing governed path
  (`_execute_query_impl`), so the write classifier, hidden-catalog refusal, RLS, masking
  and LIMIT apply unchanged.
- **Assist:** `/ai/sql` receives approved definitions as prompt context and reports which
  it was *given*, never claiming the model used them.
- **Governance:** definitions are owned, versioned, approved objects. Catalog access
  applies to them: a metric over a catalog the caller cannot see does not exist for that
  caller.

Decided approach (A): definitions in PostgreSQL tables, our own sqlglot generator.
Rejected: YAML in git/ConfigMap (no per-caller visibility, no approval record in the
product), embedding MetricFlow (second SQL engine abstraction, bypasses our dialect and
RLS rewrite path).

### Scope

In v1:
- Metric definition: one aggregate expression over a base table, default filters, allowed
  dimensions, time column and grains, period cap.
- Approved joins: one hop, many-to-one only, within one catalog.
- Synonyms on the metric (glossary).
- Three read actions exposed over MCP: list, describe, query.
- Audit of metric id and version on every query.
- Definitions as `/ai/sql` context.
- Console page for authoring, approval, version history and joins.

Out of v1: pre-aggregation or result cache; cross-catalog joins; derived metrics (ratios,
cumulative, metric-of-metrics); graph, inference or write actions; BI integration;
Cube/dbt/MetricFlow/OSI import or export (next stage; OSI claims still unverified);
merging synonyms into the concept store (`FEATURE_ONTOLOGY`, runtime-created tables —
coupling would put metrics behind that flag); background re-validation of definitions;
a bytes-scanned cap.

## 1. Data model

Migration `0023_semantic_metrics` (`backend/migrations/versions/0023_semantic_metrics.sql`
+ `.py`).

**`semantic_metrics`** — one row per metric.

| Column | Meaning |
|---|---|
| `id` | serial PK |
| `name` | unique identifier, `^[a-z][a-z0-9_]{0,62}$`; used in tool calls and citations |
| `label`, `description` | display name and description shown to people and agents |
| `synonyms text[]` | other names (e.g. 매출액, sales) |
| `owner_id` | responsible user |
| `status` | `draft` / `approved` / `retired` |
| `current_version` | the approved version agents use; null until first approval |
| `created_at`, `updated_at` | |

**`semantic_metric_versions`** — one row per version, append-only.

| Column | Meaning |
|---|---|
| `metric_id`, `version` | PK; version is 1, 2, 3… per metric |
| `catalog` | catalog registry name (e.g. `AwsDataCatalog`) |
| `base_table` | `schema.table` |
| `measure` | aggregate expression, e.g. `SUM(amount)` |
| `filters` | boolean expression always applied, e.g. `status = 'paid'`; nullable |
| `time_column` | nullable; when set, `period` is required on query |
| `grains text[]` | subset of `day, week, month, quarter, year` |
| `max_period_days` | period cap; default 366 |
| `dimensions jsonb` | list of `{name, column, join?}`; `join` holds the join condition **copied by value** from the join library at authoring time |
| `created_by`, `created_at`, `change_note` | author and reason |
| `approved_by`, `approved_at` | set once on approval |

Join conditions are copied by value so that a past version reproduces the same SQL even
after the join library changes; otherwise an old audit citation would point at SQL that
can no longer be regenerated.

Append-only is enforced with the same trigger pattern as the audit tables
(`0005_audit_append_only`): UPDATE is refused except the single transition that sets
`approved_by`/`approved_at` on an unapproved row; DELETE is refused. **Limit, stated in
docs:** as with the audit tables, this stops the application's normal code paths, not the
owning database role, which can disable a trigger (`tests/test_audit_append_only.py`).
Never call it tamper-proof.

**`semantic_joins`** — the approved join library.

| Column | Meaning |
|---|---|
| `id` | serial PK |
| `catalog`, `from_table`, `to_table` | |
| `on_columns jsonb` | list of `[from_col, to_col]` pairs |
| `source` | `history` (mined from `query_history` via `catalog_graph.py`), `naming` (`catalog.explain_relationships`), `manual` |
| `approved_by`, `approved_at` | |

### Rules

1. **Many-to-one joins only.** A one-to-many join inflates `SUM`; v1 rules it out
   structurally. On approval, the target columns are checked for uniqueness with a query
   (`COUNT(*)` vs `COUNT(DISTINCT …)` on the target table) run through the governed path
   as the approving admin. It sees only the rows that admin's RLS allows: a duplicate key
   in rows hidden from the admin is not found.
2. **Agents use approved versions only.** A `draft` is runnable as a preview by its author
   and by admins. Approval is admin-only. Author ≠ approver is not enforced (impossible in
   a one-person deployment); the approver is recorded instead.
3. **Visibility follows catalog access.** A metric whose `catalog` the caller cannot see
   (`CatalogAccess.allows`) is absent from lists and returns the same 404 as a missing
   metric. Row-level RLS and masking apply at execution.

## 2. SQL generator and validation

Module `backend/app/semantic/compile.py`: pure functions, no database, network or model
calls.

```
compile_metric(version, by, period, grain, where, dialect, now) -> CompiledQuery(sql, citation)
```

### On save (new metric or new version), parsed with sqlglot 26.33

- `measure`: exactly one top-level aggregate — `SUM`, `COUNT`, `COUNT(DISTINCT …)`, `AVG`,
  `MIN`, `MAX`. Inside it only base-table columns, literals, arithmetic, `CASE`,
  `COALESCE`, `CAST`. Subqueries, window functions, multiple statements, nested
  aggregates and functions outside the allow-list are refused. The check walks AST node
  types, never strings.
- `filters`: comparisons, `IN`, `BETWEEN`, `IS [NOT] NULL`, `LIKE`, `AND`/`OR`/`NOT` over
  base-table columns and literals. No aggregates, no subqueries.
- Every column is checked against the table schema from the existing catalog index. An
  unknown column refuses the save.
- The author cannot name a catalog or table they cannot see.
- Refused on save: two dimensions reaching the same table through different joins (one alias per target table), and a dimension named like the metric.
- Dimension `join`s must reference an approved row in `semantic_joins` whose `from_table`
  is the base table.

### On query

- The SQL is assembled as a sqlglot AST and rendered in `get_engine().rls_dialect`
  (`athena` live, `trino` on OSS). No string concatenation of caller input.
- `by` accepts only dimension names registered on the version. A caller cannot name a
  column, so there is no path for arbitrary SQL.
- A joined dimension adds `LEFT JOIN` with the copied condition. Many-to-one, so the
  aggregate is not inflated.
- `period`: `last_month`, `this_month`, `last_quarter`, `this_quarter`, `last_year`,
  `this_year`, `last_n_days:N`, or a range `YYYY-MM-DD..YYYY-MM-DD` (the end date is inclusive). Resolved to date literals from
  `now` in the configured time zone (default `Asia/Seoul`). Required when the version has
  a `time_column`; refused if longer than `max_period_days`.
- `grain`: one of the version's `grains`; adds `DATE_TRUNC(grain, time_column)` as a
  dimension.
- `where`: list of `{dimension, op, value}`, op in `=`, `!=`, `in`, `>`, `<`, `between`;
  values become sqlglot literals.
- Output is ordered by the dimensions in the order given. Row limit follows the existing
  LIMIT rule. Determinism (same input and `now` → identical SQL text) is fixed by tests.

### Execution and citation

The compiled SQL is passed to `_execute_query_impl` as the caller. Nothing about metrics
bypasses governance. The response carries:

```json
{"columns": [...], "rows": [...],
 "citation": {"metric": "revenue", "version": 3, "approved_by": "admin",
              "approved_at": "...", "sql": "SELECT ...",
              "rls_applied": true, "pii_masked": 0}}
```

`sql` is the compiled statement before RLS rewriting, so a person can re-run it.
`rls_applied` is true when any RLS policy or mask applied to the statement — including a
mask alone, with no row filter; `pii_masked` counts values masked. `rls_applied` tells the reader that the same definition can give different numbers to
different callers.

## 3. Tools, API, audit

### Actions (registry → MCP tools generated automatically; 26 → 29)

| Action / MCP name | Permission | Kind | Content |
|---|---|---|---|
| `metric.list` / `metric_list` | `catalog:read` | READ | approved metrics visible to the caller: name, label, synonyms, description |
| `metric.describe` / `metric_describe` | `catalog:read` | READ | dimensions, grains, filters, period cap, current version, approver |
| `metric.query` / `metric_query` | `query:run` | READ | compile, execute, return rows + citation |

All three carry `capability="query"`; absent on the Portable Core.

**Why `metric.query` is READ while `query.run` is CREATE.** `query.run` is CREATE
(`app/chat/analysis/query.py`) because Athena bills by bytes scanned and a statement the
user did not write can read the wrong table. For a metric, the table and expression were
approved by an admin, so the wrong-table risk is gone. Cost is bounded by the mandatory
period and `max_period_days` plus the existing per-key rate limit. Residual risk: an
unpartitioned table is scanned in full even with a period. Partition information is reported as `"unknown"` for every current reader, so the approval
screen always warns about a possible full scan; the admin decides. A bytes-scanned cap is
out of v1.

### REST (`/api/semantic/...`; console only, not MCP)

- `GET` list/describe as above.
- Create metric, create version, preview a draft: `governance:write` and a signed-in person (service-account keys and IdP tokens are refused).
- `POST /semantic/metrics/{name}/query` (`query:run`) is the console/SQL Lab route for `metric.query`.
- A non-current version (approved or not) is reachable only by its author or a signed-in admin.
- Approve version, retire metric: `require_admin`. Service-account keys and IdP tokens
  never pass it, so **agents cannot change definitions**. Approval only moves forward: a
  version older than the current one is refused (409).
- Describe shows authors and approvers the newest unapproved version as `pending` (its
  measure, filters, base table and example SQL), which is what "Approve" approves; other
  viewers see approved versions only.
- Joins: list candidates (history + naming), approve (`require_admin`, runs the
  many-to-one check), manual entry (same check).

### Audit

- Each `metric.query` writes one `tool_call_log` row: `tool="metric.query"`,
  `resource_kind="metric"` (0023 widens 0008's `resource_kind` CHECK to allow it), `resource=["revenue"]`,
  `citation_sources=["metric:revenue@v3"]`, `pii_masked`, `outcome`, `duration_ms`, and
  the compiled SQL in `response_text`.
- Execution calls `_execute_query_impl` directly, not the `/queries/execute` wrapper, so
  no second `query.execute` row is written.
- Refusals are recorded too: hidden or missing metric, unknown dimension, missing or
  over-cap period.
- Definition changes (create, version, approve, retire, join approval) go to the existing
  admin audit log (`security_audit.py`).

## 4. `/ai/sql` integration and console UI

### `/ai/sql`

- `_build_messages` adds an "Approved metric definitions" block under the schema: only
  approved metrics the caller can see (and only the requested `catalog`, if given), one
  line each (name, label, synonyms, measure, filters, base table, time column). At most
  20: metrics whose label or synonym appears in the question first, then by name. Plus
  one rule: "If the question asks for one of these metrics, use its expression and
  filters exactly."
- Metric context is bounded by a 2 s timeout and never blocks `/ai/sql`; on failure the prompt simply has no definitions. `metrics_provided` is set only when a model call happened (the no-AI and empty-catalog paths provide none).
- `AskResponse` gains:
  - `metrics_provided: list[str]` — e.g. `["revenue@v3"]`, the definitions **put in the
    prompt**. No claim that the model used them.
  - `suggested_metric: {name, dimensions} | null` — set only when a metric label or
    synonym occurs verbatim in the question (deterministic string match, no LLM). Points
    agents and people to the cited `metric_query` path.
- Audit: the existing `/ai/sql` row records `citation_sources=["context:metric:revenue@v3"]`;
  the `context:` prefix separates "given as context" from an execution citation.
- PII guard, egress guard, EXPLAIN validation and budget cap are unchanged.

### Console

- New page `/metrics` under the Catalog menu, shown only when the `query` capability is
  true. (Not `/catalog/metrics`: it would shadow a namespace named `metrics` under
  `/catalog/[namespace]`.)
- **List:** name, label, status, current version, owner, last approver and date.
- **Detail:** current definition, an example of the compiled SQL, version history (author,
  note, approver, text diff against the previous version), recent query count from
  `tool_call_log`. A "broken" badge when the definition no longer matches the table
  schema (checked when the page opens).
- **Editor** (`governance:write`): catalog/table picker, measure, filters, dimensions
  (base columns or columns through approved joins), time column, grains, period cap,
  change note. Validation errors shown per field. "Preview" runs the draft as the author.
- **Approve** (admin): shows the compiled SQL and, when the base table has no partition
  information, a full-scan warning.
- **Joins tab:** candidates with source (history candidates show usage count),
  many-to-one check result, approve; manual entry with the same check.
- **SQL Lab, Ask AI result:** a "provided definitions: revenue v3" chip; when
  `suggested_metric` is set, a "Query as metric" button that re-runs it through
  `metric.query` to get a cited result.

## 5. Errors, tests, measurement

### Errors (all recorded in `tool_call_log` with an `outcome`)

| Case | Response |
|---|---|
| Metric missing, on a hidden catalog, or without an approved version | 404, identical message |
| Unknown dimension, grain or op | 400 with the allowed list (agents can self-correct) |
| Period missing or over cap | 400 with `max_period_days` |
| Definition invalid on save | 422 with per-field reasons |
| Join target not unique | 422 with a duplicate count |
| Refused at execution (RLS, hidden table) | the existing `_execute_query_impl` response |
| Engine error or timeout | the engine's own status is kept (400/403/504), plus a hint that the definition may need re-validation; 401/403 are returned unchanged |

### Tests

- `tests/test_semantic_compile.py` (no DB): accepted and refused expressions (subquery,
  window, unlisted function, multiple statements, no aggregate, nested aggregate); golden
  SQL for dimensions, joins, grains and periods in both `athena` and `trino`; determinism;
  quotes and comment markers in `where` values stay literals.
- API and action tests (fake pool, as existing tests): list filtering and 404 by catalog
  access; key and IdP token refused on approve; drafts not queryable by agents; audit
  `citation_sources`; no duplicate `query.execute` row; MCP tool list grows 26 → 29.
- `/ai/sql`: only visible metrics, at most 20, in the prompt; `metrics_provided`;
  deterministic `suggested_metric`; `context:` prefix in audit.
- Migration: after `0023`, UPDATE (other than approval) and DELETE on
  `semantic_metric_versions` fail, as in the existing append-only test.
- Frontend: editor validation display and chip/button conditions as pure functions in
  `lib/*.test.ts`.

### Measurement (to confirm the effect, not a gate)

1. Before implementation: 20 metric-style questions over the live Athena sample data,
   each asked of `/ai/sql` three times. Record accuracy against a reference SQL and
   agreement across the three answers.
2. After implementation: the same 20 through (a) `/ai/sql` with definitions as context and
   (b) `metric_query`.
3. Record results in an appendix to this spec. (b) is deterministic, so its agreement is
   100% by construction; the meaningful numbers are (a)'s improvement and how many of the
   20 questions (b) can answer at all.
