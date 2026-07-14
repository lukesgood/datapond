# Athena Query Engine (B2 · Slice 2) — Design Spec

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Parent:** B2 — AWS-native serverless analytics. **Slice 1** (Glue ingestion + catalog) is merged + live. This **Slice 2** adds Athena as the serverless SQL query engine, re-enabling the **query (SQL Lab)** + **dashboards** capabilities.

## Problem

After Slice 1, the foundation profile can collect + browse Glue-registered Iceberg tables, but **cannot run SQL** — `capabilities.query`/`dashboards` gate on self-hosted Trino, which is disabled on AWS. `queries.py` executes user SQL through a Trino DBAPI connection (`get_trino_connection`), with a Trino-specific error taxonomy; `ai_sql.py` hard-codes the Trino dialect + `iceberg.` catalog prefix; the RLS SQL-rewrite emits `dialect="trino"`. Dashboards and SQL Lab both consume `/queries/execute` results (`{columns, rows}`), so swapping the engine behind that one endpoint transparently restores both.

## Goal

Execute user + AI-generated SQL over Glue-registered Iceberg tables via **Amazon Athena** (serverless, pay-per-scan), behind an engine abstraction so on-prem/Trino profiles are unchanged. Re-enable `query` + `dashboards`. Keep RLS working on Athena.

## Non-goals (deferred)

- **Lake Formation** row/column security (the Athena equivalent of the Trino ACL file / RLS "Layer 2" for direct-connect BI clients) — out of scope; backend-path RLS (Layer 1) is what `/queries/execute` uses.
- Athena workgroup cost controls / result caching / CTAS-materialization tuning.
- Federated queries, UNLOAD, prepared statements.

## Decisions (approved)

1. **pyathena (DBAPI)** for execution — preserves the `execute/fetchall/description` contract so `_run_blocking` barely changes (raw boto3 poll-model would be a rewrite).
2. **Engine abstraction** selected by the catalog backend (single source of truth): `catalog.backend=glue` → Athena engine + `FEATURE_ATHENA`; else Trino. Same derivation pattern as Slice 1's `FEATURE_GLUE`.
3. **RLS included** — switch the SQL-rewrite dialect `trino`→`athena` and re-point default catalog naming; the Trino ACL file (Layer 2) is simply not generated on Athena.

## Architecture

```
POST /queries/execute ─▶ get_engine()  (env QUERY_ENGINE: athena|trino, derived from catalog.backend)
                            │  athena → AthenaEngine (pyathena)
                            │  trino  → TrinoEngine  (existing code, wrapped)
                            ▼
        strip comments → RLS enforce(sql, dialect=engine.rls_dialect) → add_limit_to_query
                            ▼
        engine.execute(sql, user) → (rows, columns)      # pyathena cursor OR trino cursor
                            ▼  on error
        engine.map_error(exc) → detail string            # Athena vs Trino error taxonomy
                            ▼
        QueryResult{columns, rows, execution_time_ms, row_count} + QueryHistory
                            (catalog/schema labels from engine defaults)

ai_sql.py ─▶ prompt dialect + catalog prefix from get_engine(); schema context via Slice-1 CatalogReader (Glue), not Trino information_schema
```

### Component 1 — Engine abstraction (`backend/app/api/query_engine.py`, new)

`Engine` protocol:
- `execute(sql: str, user: str | None) -> tuple[list[list], list[str]]` — returns `(rows, columns)`.
- `map_error(exc: Exception) -> tuple[str, str, int]` — returns `(status, detail, http_code)` (e.g. `("error", "Table not found: …", 400)`, `("timeout", "…", 504)`).
- `default_catalog: str`, `default_schema: str` — for QueryHistory labels + table-name qualification.
- `rls_dialect: str` — `"trino"` | `"athena"` for the RLS sqlglot rewrite.
- `ai_dialect_prompt: str`, `ai_table_prefix: str` — injected into the AI-SQL prompt.

`TrinoEngine`: wraps the existing `get_trino_connection` + `_run_blocking` cursor path + the current Trino error taxonomy; `default_catalog="iceberg"`, `default_schema="default"`, `rls_dialect="trino"`, prefix `iceberg.<schema>.<table>`.

`AthenaEngine`: `pyathena.connect(s3_staging_dir=ATHENA_OUTPUT_LOCATION, region_name=S3_REGION, work_group=ATHENA_WORKGROUP, schema_name=ATHENA_DATABASE, catalog_name="AwsDataCatalog")`; execute via the pyathena DBAPI cursor (same `execute/fetchall/description`); `map_error` parses `pyathena.error.OperationalError`/`DatabaseError` (Athena `StateChangeReason` messages like `line 1:8: Column 'x' cannot be resolved`, `TABLE_NOT_FOUND`, timeouts) into the same user-facing message style; `default_catalog="AwsDataCatalog"`, `default_schema=ATHENA_DATABASE`, `rls_dialect="athena"`, prefix `AwsDataCatalog.<database>.<table>` (or bare `<database>.<table>`).

`get_engine()`: reads `QUERY_ENGINE` env (`athena`|`trino`, default `trino`) and returns a cached engine instance.

### Component 2 — `queries.py` routes through the engine

`execute_query` delegates: build engine = `get_engine()`; RLS `enforce(sql, ..., dialect=engine.rls_dialect)`; `add_limit_to_query` unchanged (LIMIT n is Athena-safe); `rows, columns = await asyncio.to_thread(engine.execute, safe_query, trino_user)`; on exception `status, detail, code = engine.map_error(exc)`. `QueryHistory.catalog`/`schema` set from `engine.default_catalog`/`default_schema`. The Trino-specific `get_trino_connection` + error block move into `TrinoEngine`. `QueryResult` model + history persistence unchanged. The catalog-tree `/catalog/schemas` label (currently hardcoded `"iceberg"`) becomes `engine.default_catalog`.

### Component 3 — AI-SQL engine-aware (`ai_sql.py`)

`_build_messages` uses `get_engine().ai_dialect_prompt` (e.g. "The query engine is Amazon Athena (Trino/Presto SQL, engine v3)") and `ai_table_prefix` instead of hard-coded "Trino"/`iceberg.`. **Schema context** (`_fetch_schema_context`) switches from a Trino `information_schema` query to the **Slice-1 `CatalogReader`** (`list_namespaces`/`list_tables`/`get_columns`) — removing the second Trino coupling and reusing the Glue path. Cache/prewarm behavior preserved.

### Component 4 — RLS on Athena (`app/rls/engine.py`)

`enforce(...)` takes a `dialect` param (default `"trino"` for back-compat) threaded from `engine.rls_dialect`; sqlglot `parse(read=dialect)` / `.sql(dialect=dialect)` / `parse_one(read=dialect)` use it. `_qualify`/`DEFAULT_CATALOG` default naming re-points to the engine's catalog convention when Athena. Mask expressions (`to_hex/sha256/to_utf8/regexp_replace/substr/concat`) + `SELECT * EXCEPT` are Athena engine-v3 (Trino-based) compatible — unchanged. **`app/rls/trino_acl.py` (Layer 2) is not generated when the engine is Athena** (guard its deploy hook on `QUERY_ENGINE == trino`).

### Component 5 — Capability gating

`capabilities.py`: `athena = _feat(env, "ATHENA", default=False)`; `query = trino or athena`; `dashboards = trino or athena`. Helm derives `FEATURE_ATHENA` + `QUERY_ENGINE` from `catalog.backend` (glue → athena/true), mirroring `FEATURE_GLUE`.

### Component 6 — IAM (terraform) + config

`terraform/iam.tf` — add an Athena statement to the node app-role: `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`, `athena:StopQueryExecution`, `athena:GetWorkGroup`. Glue read (Slice 1) + S3 (existing `S3Data` covers the results prefix under the data bucket) already suffice for Athena planning + result staging.

Helm/config: `ATHENA_OUTPUT_LOCATION=s3://datapond-iceberg/athena-results/`, `ATHENA_WORKGROUP=primary`, `ATHENA_DATABASE` (the Glue database, default the ingestion namespace), `QUERY_ENGINE` (derived). `requirements.txt` — add `pyathena` (verify it resolves against the pinned boto3/botocore; the runtime already carries a newer boto3).

## Data flow

1. SQL Lab / dashboard mini-chart → `POST /queries/execute {query}` (unchanged frontend).
2. `get_engine()` = AthenaEngine (glue profile) → RLS rewrite (athena dialect) → LIMIT → `pyathena` executes → Athena scans Glue/Iceberg-on-S3, writes results to `ATHENA_OUTPUT_LOCATION`, pyathena fetches them → `(rows, columns)`.
3. `QueryResult{columns, rows, …}` → frontend renders table/chart (unchanged).

## Error handling

- `AthenaEngine.map_error` maps pyathena/Athena errors to the same taxonomy shape the UI already reads (`detail` string, `status`, HTTP code): syntax/column-resolution → 400 "Syntax error / column not resolved: …"; table/schema/database not found → 400/404; access denied → 403; timeout → 504; connection/config → "Cannot reach Athena / check ATHENA_OUTPUT_LOCATION".
- RLS denials (`RlsDenied`) → 403; RLS internal error → fail closed (unchanged).
- Missing `ATHENA_OUTPUT_LOCATION` → clear startup/first-query error.

## Testing

- `get_engine()` selection: `QUERY_ENGINE=athena` → AthenaEngine; default → TrinoEngine.
- `add_limit_to_query` unchanged (LIMIT idempotency, DDL skip) — still passes.
- `AthenaEngine.map_error` with fabricated pyathena error objects → correct (status, detail, code) for the main cases.
- AI-SQL prompt uses the engine's dialect/prefix (assert Athena prompt contains "Athena" + `AwsDataCatalog`, not "Trino"/`iceberg.`).
- RLS `enforce(dialect="athena")` round-trips a simple policy (sqlglot athena dialect) and qualifies to the Athena catalog naming — with mocked policies.
- Capability gating: `FEATURE_ATHENA=true` → query/dashboards true.
- pyathena is mocked in unit tests (fake cursor `execute/fetchall/description`); **real Athena execution is validated live** (mirrors Slice 1 — the pyathena/Athena API is only proven against real AWS).

## Migration / compatibility

- `QUERY_ENGINE` defaults `trino` → on-prem/full profiles unchanged. `enforce(dialect=...)` defaults `"trino"`.
- New env additive. `pyathena` new dep — must not break the boto3/botocore resolution (runtime already has a compatible boto3).
- Foundation profile (catalog.backend=glue) auto-selects Athena + turns on query/dashboards.

## Risks & follow-ups

- **pyathena dependency resolution** vs the `boto3==1.34.0` pin (comment warns about botocore constraints; the live venv already runs boto3 1.42.x). Plan verifies the install in CI + live.
- **Athena SQL compatibility for RLS masks** — engine v3 is Trino-based so `sha256/regexp_replace/SELECT * EXCEPT` should work; validate live with RLS enabled on a test policy.
- **Live-only validation** — like Slice 1, real Athena queries (StartQueryExecution + result read) are only proven on the live AWS deploy; treat the bring-up as the true test. Needs `terraform apply` (Athena IAM) + redeploy.
- **Athena cost** — $5/TB scanned; mitigated by Iceberg partitioning + Parquet + the enforced `LIMIT`. Zero idle cost.
- Lake Formation (direct-connect BI RLS) is a separate future slice.
- Stale frontend copy ("Set ANTHROPIC_API_KEY" toast; `iceberg`-labelled catalog selector) — minor cleanup, fold in where cheap.
