# DataPond Portability and Exit Strategy

## Goal

DataPond is a lakehouse whose every layer is an open standard (`POSITIONING_V7.md`). An operator must be able to change object storage, the Iceberg catalog, where the Trino engine runs, PostgreSQL hosting, model provider, or Kubernetes environment without moving data through a proprietary format or rewriting SQL.

Portability is a tested property, not an “open source” label. Running many OSS services can create another form of lock-in and operational cost.

## Portability boundaries

| Asset | Portable boundary | Current move mechanism |
|---|---|---|
| Source/object data | S3 API | S3 copy/sync or compatible object migration |
| App metadata | PostgreSQL | `pg_dump`/restore, snapshot/PITR where supported |
| Vectors | pgvector columns | PostgreSQL backup/restore when embedding model is unchanged |
| Tables | Parquet + Apache Iceberg | Stay in place; register in another catalog with the catalog export |
| Catalog | Glue · Iceberg REST | `POST /api/catalogs/{name}/export` (Trino `register_table`, no data copy) |
| Query engine | Trino SQL | The same Trino and SQL on every profile; nothing to translate |
| Models | LiteLLM logical names | Change provider mapping and credentials |
| Identity | JWT/LDAP/WebAuthn/OIDC | Reconfigure issuer/directory; export local state with PostgreSQL |
| Deployment | OCI + Helm + Kubernetes | Apply profile/values to target cluster |
| APIs | REST/OpenAPI | Keep clients independent of provider implementation |

## Current exit paths

### S3 to another object store

1. Freeze or record writes.
2. Copy all object versions required by the recovery policy.
3. Verify count, byte size, checksums, and representative reads.
4. Change the object endpoint/credentials.
5. Rewrite stored source URIs only where the bucket/path changed.

S3-compatible does not guarantee every lifecycle, IAM, versioning, or consistency behavior is identical. Test the target.

### Aurora to PostgreSQL

1. Check PostgreSQL major version and installed extensions.
2. Take a consistent dump/snapshot.
3. Restore roles, schema, data, and `vector` extension.
4. Restore the same `ENCRYPTION_KEY` before starting the backend.
5. Validate collection/chunk counts, indexes, authentication, and credential decryption.

### Bedrock to another model provider

1. Preserve logical names (`embed`, `chat`, `rerank`).
2. Reconfigure LiteLLM mappings and credentials.
3. Run chat, streaming, timeout, and fallback conformance tests.
4. If embedding model or dimension changes, create a new embedding version and re-embed collections.
5. Compare retrieval and citation quality against a fixed evaluation set.

Store model name, provider/version, dimension, content hash, and embedding time with vector data when extending the schema.

### Glue to an Iceberg REST catalog (Polaris) — catalog export

An Iceberg table's state lives in its metadata files in object storage; a catalog only records where the current metadata file is. The catalog export re-records that location in another catalog through Trino, so nothing is copied and the source is unchanged.

1. Make the target catalog queryable by Trino: on OSS profiles it is the chart's Polaris; on the AWS reference, add it as `trino.extraCatalogs` (Iceberg REST) and register it under Settings → Data catalogs.
2. Let the target accept the existing table locations. For Polaris set `polaris.storage.extraAllowedLocations` to the Glue warehouse (e.g. `s3://<bucket>/warehouse`) and enable, for the migration only, `polaris.extraFeatures` `ALLOW_UNSTRUCTURED_TABLE_LOCATION` and `ALLOW_EXTERNAL_TABLE_LOCATION` (a registered table lives outside the catalog's own layout; two Polaris catalogs sharing a store also need `ALLOW_OVERLAPPING_CATALOG_URLS`). These flags widen where a writer may put data — CVE-2026-42812 needs exactly this combination with broad allowed locations — so keep the locations narrow and turn the flags off afterwards. Trino's `iceberg.register-table-procedure.enabled=true` is set by the chart on every Iceberg catalog it renders.
3. Plan: `POST /api/catalogs/AwsDataCatalog/export` with `{"target": "<new catalog>"}` (optionally `schema`, `tables`). Each table is `register`, `exists` (the target already has it, left alone) or `skip` (a view or unreadable table, with the reason).
4. Apply: the same call with `"apply": true`. Each table is `registered` (row counts equal on both sides), `mismatch`, or `failed` with the engine's message; one failure does not stop the others. The call is audited as `catalog_exported`.
5. Point users at the new catalog (make it the default under Settings → Data catalogs), and stop writing through the old one before you drop it: two catalogs committing to the same table would diverge.

CI exercises steps 3–4 on every pull request between two Polaris catalogs on MinIO (`.github/scripts/multicatalog_check.py` §7).

**Live rehearsal, 2026-11-12 (AWS Single-Node Reference).** Polaris was run beside Glue (metadata in Aurora, `polaris.catalogName: lake`, base location `s3://datapond-iceberg/polaris/lake`, `extraAllowedLocations: [s3://datapond-iceberg/warehouse]`, `extraFeatures` `ALLOW_UNSTRUCTURED_TABLE_LOCATION` + `ALLOW_EXTERNAL_TABLE_LOCATION`, Trino catalog `polaris_lake`). The export planned 23 of 23 tables of `AwsDataCatalog.default` as `register` (4 s) and registered all 23 with equal row counts on both sides (28 s; 6,000 orders, 30,000 page events, …). The same SQL answered through `/api/queries/execute` against `polaris_lake`, a join across the two catalogs worked, and every Glue table's current metadata file was unchanged afterwards. Polaris was then turned off again (registry entry removed, flags cleared) — Glue stays the live catalog. Left behind on purpose: the `polaris_catalog` database in Aurora (Polaris's own metadata, small). A later move should start from a fresh export rather than reuse it: the registrations there point at the metadata files of 2026-11-12. The rehearsal found two chart gaps, both fixed before it passed: Polaris assumed the in-cluster PostgreSQL (#257), and its catalog-init Job rendered only with MinIO (#258). Provider-specific grants (Lake Formation) are not in Iceberg metadata and need separate handling; DataPond's own catalog grants are re-entered for the new catalog.

### Two catalogs at once — one writer per table

Several lake catalogs can be registered side by side (e.g. Glue for tables AWS services read, Polaris for new data); queries join across them. The rule that keeps this safe: **each table has one owner catalog it is written through.** A table registered in a second catalog by the export is a **read-only mirror** (`mode: mirror`, the default; `mode: move` makes the target the owner and the source the mirror). The links live in `catalog_table_links` (migration 0028; `GET /api/catalogs/mirrors`).

| Risk | Guard (2.7) |
|---|---|
| A write through the mirror forks the table | `/queries/execute` refuses INSERT/UPDATE/DELETE/MERGE/CREATE AS/ALTER/DROP/TRUNCATE on a mirror with 409 naming the owner; a sync whose target is a mirror fails before writing |
| A DROP through a Polaris mirror deletes the owner's files | the same refusal, and Polaris's purge-on-drop is off whenever it shares locations (`extraAllowedLocations` set) |
| A mirror read bypasses the owner's grants or sees old data | DataPond routes reads of a mirror to the owner table, so the owner's catalog grant, row filters and masks apply and the data is current |
| A mirror falls behind for engines outside DataPond | the freshness check (every `MIRROR_CHECK_SECONDS`, default 300, leader-locked; or `POST /api/catalogs/mirrors/check`) re-points the mirror at the owner's current snapshot — unregister + register, no copy |
| Someone commits through the mirror from outside DataPond | the check marks it `diverged`, logs an error and writes an audit row; it is never overwritten |
| A sync lands in the wrong catalog | `target_catalog` per sync (request or remembered per table); lake catalogs only |

Not guarded: an outside engine writing to the mirror is detected afterwards, not refused — restrict writes on the mirror side (Polaris principal roles, Glue IAM/Lake Formation) for that. CI exercises every guard above in the kind job (`multicatalog_check.py` §8, `trino_connector_check.py` §4c).

## Critical non-portable state

- `ENCRYPTION_KEY`: mandatory to decrypt stored credentials.
- external provider credentials and IAM policies.
- DNS/TLS and environment-specific ingress configuration.
- AWS-specific alarms, schedules, and service settings.
- Iceberg metadata URIs if warehouse paths change.
- embeddings when provider/model/dimension changes.

Keep these in an explicit environment manifest and secure secret backup.

## Export bundle design

A future portable export should contain:

```text
manifest.json
postgres/
  schema.sql
  data.dump
catalog/
  tables.json
  iceberg-metadata-locations.json
models/
  logical-model-mapping.yaml
policies/
  collections.json
  sharing.json
  table-policies.json
lineage/
  events.jsonl
checksums/
  objects.sha256
```

Secrets should not be included by default. Export references and rebind them on import.

Proposed CLI—**roadmap, not currently implemented**:

```bash
datapond export --output s3://backup/export/ --include catalog,policies,collections,lineage,model-config
datapond import --source s3://backup/export/ --catalog iceberg-rest --query-engine trino
```

## Exit drill

Run at least quarterly for production environments.

1. Restore PostgreSQL into an isolated target.
2. Copy a representative object/Iceberg dataset.
3. Rebind to a different object endpoint or account.
4. Rebind logical model names to a different provider; re-embed a test collection if required.
5. Register representative tables in an alternate catalog, if table workflows are used.
6. Verify authentication, collection access, PII masking, citations, usage attribution, and audit.
7. Record RPO, RTO, data mismatches, provider-specific blockers, and remediation.

## Acceptance criteria

- No customer object or PostgreSQL state is accessible only through a proprietary DataPond format.
- Core Knowledge APIs run after provider rebinding.
- Restored credentials decrypt with the preserved encryption key.
- Collection and chunk counts match.
- RAG evaluation remains within an agreed quality tolerance.
- Optional table schemas, snapshots, and representative row counts match.
- The operator can identify all remaining provider-specific resources.

## Open-core policy

Data export, provider rebinding, and migration documentation belong in Community. Enterprise may provide orchestrated multi-environment migration, policy packs, verified tools, and support, but should not block access to customer data.

## Roadmap

- versioned `datapond export/import`
- provider conformance test suite
- OpenLineage-compatible durable event export
- a recurring (scripted) Glue → Polaris acceptance drill; the one live rehearsal (2026-11-12) was run by hand
- Delta Lake → Iceberg migration for teams leaving Databricks
- embedding version migration workflow
- automated quarterly exit drill
- documented cross-cloud reference profile
