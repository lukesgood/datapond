# Glue-Native Ingestion + Catalog (B2 · Slice 1) — Design Spec

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Parent:** B2 — AWS-native serverless analytics layer (replaces self-hosted Trino/Polaris). This is **Slice 1 of 2**: ingestion (write) + catalog (read) via AWS Glue Data Catalog + pyiceberg. **Slice 2** (separate spec) adds Athena as the SQL query engine.

## Problem

DataPond's live AWS foundation profile has **no data-collection or analysis layer**. `capabilities.py` gates `connectors`/`catalog`/`query` on self-hosted `TRINO`/`POLARIS`, both disabled on AWS. So a user cannot connect a source, land data, or browse tables — only paste text / point at pre-existing S3 objects for RAG. For real use the platform needs an AWS-native on-ramp: connect a source → land governed Iceberg-on-S3 → browse it.

The code map shows the ingestion write path is **Trino-free** — it writes Parquet to S3 and commits snapshots via `pyiceberg` through one function, `iceberg_catalog.get_catalog()` (a `RestCatalog` pointed at Polaris). pyiceberg ships a native `GlueCatalog`. So the AWS-native port is: **point pyiceberg at Glue instead of Polaris**, and read the catalog (list/columns/preview) through the same pyiceberg catalog object instead of Polaris HTTP + Trino SQL.

## Goal

In the foundation profile, deliver a working end-to-end slice: **connect a source → sync → data lands in a Glue-registered Iceberg table on S3 → Catalog page lists it and previews rows**, using only AWS Glue Data Catalog + pyiceberg (no Athena, no self-hosted Trino/Polaris). Re-enable the **Connectors** and **Catalog** UI capabilities.

## Non-goals (deferred)

- **SQL query execution / SQL Lab / AI-SQL execution / BI dashboards** → Slice 2 (Athena). `query`/`dashboards` capabilities stay OFF in this slice.
- Migrating existing Polaris/SeaweedFS tables to Glue (live foundation has no such data — greenfield).
- Streaming (RisingWave), pipelines (Airflow), notebooks, experiments, OpenMetadata lineage.
- Cross-account Glue, Lake Formation fine-grained permissions (RLS on query is a Slice 2 concern).

## Decisions (approved)

1. **Catalog-backend abstraction selected by env** — `polaris` (existing) and `glue` (new); both write and read route through it, so on-prem/full and AWS/foundation profiles both work.
2. **One pyiceberg `GlueCatalog` object serves write + listing + preview + columns** (via `list_namespaces`/`list_tables`/`load_table` → `schema()`/`scan()`/snapshot summary). No separate boto3 Glue client, no Trino, no Athena in this slice.
3. **Query stays gated OFF** until Slice 2 — the thick Athena rewrite (poll-based execution, error taxonomy, RLS SQL) is isolated.

## Architecture

```
                       iceberg_catalog.get_catalog()  ← single pyiceberg catalog singleton
                          │  glue    → pyiceberg GlueCatalog
                          │  polaris → pyiceberg RestCatalog (existing)
        ┌─────────────────┴───────────────────────────┐
        ▼ (write)                                       ▼ (read, glue backend)
Connector sync ─▶ write_dataframe_to_iceberg      GlueCatalogReader reuses get_catalog()
   ▼                                                    ▼
Parquet → S3 (credential chain) + table in Glue    list_namespaces / list_tables / load_table
                                                        → schema / scan / snapshot summary

Catalog UI ─▶ catalog.py / queries.py catalog-tree ─▶ CatalogReader (env-selected)
                          │  glue    → GlueCatalogReader   (reuses the get_catalog() singleton)
                          │  polaris → PolarisCatalogReader (existing polaris_client + Trino)
                          ▼
        list_namespaces / list_tables / get_columns / preview / get_location / row_count
```

### Component 1 — Write catalog backend (Slice A)

`backend/app/connectors/iceberg_catalog.py`: `get_catalog()` becomes backend-aware.

- `ICEBERG_CATALOG_BACKEND` env (`glue` | `polaris`, default `polaris` to preserve on-prem behavior).
- When `glue`: build a singleton `pyiceberg.catalog.glue.GlueCatalog(name="datapond", **{"type": "glue", "warehouse": GLUE_WAREHOUSE, "glue.region": S3_REGION, **_s3_fileio_props()})`, where `GLUE_WAREHOUSE = s3://<data-bucket>/warehouse`. Glue + S3 both use the default AWS credential chain (node instance profile) — `_s3_fileio_props()` already omits static keys on AWS.
- When `polaris`: unchanged (existing `RestCatalog`).
- Every `create_table`/`append`/`overwrite`/`upsert`/`update_schema` call in `iceberg_writer.py` works unchanged against either catalog — no other write-path change.

### Component 2 — Catalog reader abstraction (Slice B)

New `backend/app/api/catalog_backend.py` exposing a `CatalogReader` with:

- `list_namespaces() -> list[str]`
- `list_tables(namespace: str) -> list[str]`
- `get_columns(namespace, table) -> list[{name, type, nullable}]`
- `get_location(namespace, table) -> str | None`
- `row_count(namespace, table) -> int | None`
- `preview(namespace, table, limit: int) -> {columns: list[str], rows: list[list]}`

Two implementations, chosen by `ICEBERG_CATALOG_BACKEND`:

- **`GlueCatalogReader`** (new): uses the shared pyiceberg `GlueCatalog`. `list_namespaces()`/`list_tables()` from the catalog; `load_table(f"{ns}.{table}")` gives `.schema()` (→ columns), `.metadata.location` (→ location), `.current_snapshot().summary["total-records"]` (→ row_count, `None` if no snapshot), and `.scan().limit(n).to_arrow()` (→ preview rows). Never runs a full-table `COUNT(*)`.
- **`PolarisCatalogReader`** (new thin wrapper): delegates to the existing `polaris_client` listing + the existing Trino `information_schema`/`SELECT *` code paths already in `catalog.py`/`queries.py`, preserving current behavior byte-for-byte.

`catalog.py` and the catalog-tree endpoints in `queries.py` (`/catalog/schemas`, `/catalog/columns`, `/catalog/tables/{ns}/{table}`, `/preview`) call `CatalogReader` instead of Polaris/Trino directly. Valkey caching + lazy-load pattern preserved (engine-agnostic).

### Component 3 — Preview + column stats (Glue path)

For the Glue backend, `preview()` returns `table.scan().limit(min(limit, 500)).to_arrow()` converted to `{columns, rows}`; the existing Python-side column statistics (null-rate, distinct count, min/max) computed over the preview rows are reused unchanged (they already run in Python, not SQL). No Trino/Athena.

### Component 4 — Capability gating

`backend/app/capabilities.py`:

```python
glue = _feat(env, "GLUE")          # FEATURE_GLUE
lake = trino or polaris or glue
# connectors/catalog → lake (now true when glue)
# query/dashboards → trino  (unchanged — Athena is Slice 2)
```

Helm `backend-deployment.yaml`: inject `FEATURE_GLUE` alongside the other `FEATURE_*` flags.

### Component 5 — IAM (terraform)

Extend the node app-role policy (`terraform/iam.tf`) with Glue permissions (S3 already granted):
`glue:GetDatabase`, `glue:GetDatabases`, `glue:CreateDatabase`, `glue:GetTable`, `glue:GetTables`, `glue:CreateTable`, `glue:UpdateTable`, `glue:DeleteTable`, `glue:BatchCreatePartition`, `glue:GetPartitions`, `glue:BatchGetPartition` — scoped to the account's Glue catalog + `datapond*` databases where practical. Athena permissions are **not** added in this slice.

### Component 6 — Config / Helm

`values-prod-single.yaml` / `values-foundation.yaml`:
- `FEATURE_GLUE: true`
- `backend.env` (or a `catalog:` block): `ICEBERG_CATALOG_BACKEND=glue`, `GLUE_WAREHOUSE=s3://<data-bucket>/warehouse`, `S3_REGION`.
- `connectors`/`catalog` capabilities become visible; `query` stays hidden.

## Data flow

1. User creates a connector (existing UI/API — now visible) → `POST /connectors/{id}/sync`.
2. `sync_to_iceberg` → `write_dataframe_to_iceberg` → `GlueCatalog.create_table`/`append`/`upsert` → Parquet to `s3://bucket/warehouse/...` + table registered in Glue database.
3. Catalog page → `/catalog/schemas` lists Glue databases/tables via `GlueCatalogReader`.
4. Expand a table → `/catalog/columns` from `table.schema()`; preview → `table.scan().limit()`.

## Error handling

- `get_catalog()` / `CatalogReader` failures degrade gracefully: listing returns `[]` + a logged warning (mirrors current best-effort Polaris behavior); preview/columns return a clean 4xx/5xx with the Glue/boto3 error message mapped to a short string.
- Missing snapshot (never-synced table) → `row_count = None`, empty preview, no crash.
- `ICEBERG_CATALOG_BACKEND=glue` but Glue unreachable/misconfigured → capability still shows (presentation-gating only), but list/preview surface the error; documented in the runbook.

## Testing

- `catalog_backend` selection: `ICEBERG_CATALOG_BACKEND=glue` → `GlueCatalogReader`; default → `PolarisCatalogReader`.
- `GlueCatalogReader` methods against a **mocked pyiceberg catalog** (fake `load_table` returning a stub with `schema()`/`metadata.location`/`current_snapshot().summary`/`scan()`): columns mapping, location, row_count (incl. `None` when no snapshot), preview shape.
- `get_catalog()` builds a `GlueCatalog` (mock pyiceberg) when backend=glue and a `RestCatalog` when backend=polaris; singleton behavior.
- `capabilities.py`: `FEATURE_GLUE=true` → `connectors`/`catalog` true, `query` false; all-off → all false.
- Helm render: `FEATURE_GLUE` + `ICEBERG_CATALOG_BACKEND` env present in `values-prod-single` render.

## Migration / compatibility

- Additive: `ICEBERG_CATALOG_BACKEND` defaults to `polaris`, so on-prem/full profiles are unchanged.
- Live foundation is greenfield (Polaris/connectors were off → no existing Iceberg data to migrate).
- `pyiceberg[pyarrow]==0.11.1` already includes `GlueCatalog`; `boto3==1.34.0` already present — **no new dependency**. The plan must verify `from pyiceberg.catalog.glue import GlueCatalog` imports under the pinned versions.

## Risks & follow-ups

- **pyiceberg 0.11.1 GlueCatalog surface**: confirm `warehouse`/`glue.region` property names and `create_table` partition behavior under 0.11.1 (API has shifted across pyiceberg releases). Plan includes an import + smoke check.
- **Preview cost**: `scan().limit()` on a large unpartitioned table still reads file(s); acceptable for a bounded LIMIT, matches current Trino preview cost.
- **Slice 2 (Athena)**: SQL execution, AI-SQL execution, dashboards, and RLS-over-query. Separate spec; this slice deliberately leaves `query` gated off.
- OpenMetadata best-effort registration in `connectors.py` (`_trino_table_columns`) still references Trino — out of scope here (best-effort, non-load-bearing); note for Slice 2 or a cleanup.
