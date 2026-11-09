# Trino everywhere: one query engine, connectors as Trino catalogs

Date: 2026-11-09. Status: draft for review.

## Why

Two decisions the owner made on 2026-11-09, in this order:

1. **Data sources should be reached through Trino's connectors, not re-implemented
   one by one in Python.** Trino already federates 40-odd sources (PostgreSQL, MySQL,
   SQL Server, Oracle, MongoDB, Kafka, BigQuery, Snowflake, ...). DataPond's own
   connector layer (`backend/app/connectors/`) declares 13 `ConnectorType`s but really
   works for PostgreSQL/MySQL via SQLAlchemy + pandas, plus REST, Custom and S3. Every
   new source means a driver, schema introspection, incremental logic and PII handling
   written again, and every row passes through the backend pod's memory.
2. **The AWS reference stops using Athena and runs Trino like every other profile.**
   Connectors-as-Trino-catalogs only works where Trino runs; the AWS Single-Node
   Reference (`values-prod-single.yaml`) is the one profile without it. Rather than
   keep two engines, unify. The Athena path is removed, not kept as an option: CI
   (kind) cannot exercise it, nobody would run it, and a dead dialect branch rots.

Facts that informed the second decision (measured 2026-11-09 on the live stack):

| Fact | Value |
|---|---|
| Athena queries since 2026-10-16 | 50, all SUCCEEDED, 1.4 MB scanned in total (≈ $0) |
| Node memory (m6i.xlarge, 16 GB) | 3.6 GB used, 12 GB available |
| Chart's Trino defaults | requests 1 CPU / 2 Gi, limits 2 CPU / 4 Gi, `-Xmx2G`, `query.max-memory=2GB` |
| Glue catalog | 1 database (`default`), 23 tables |
| Backend engine abstraction | `QUERY_ENGINE=athena\|trino` already exists (`app/api/query_engine.py`), Trino is the default |
| Stored `AwsDataCatalog` references | `data_catalogs` 1 row, `semantic_metric_versions.catalog` 21, `semantic_joins.catalog` 3, `ai_chunks.source` 1 357 (`table:<catalog>.<schema>.<table>` keys), plus history/audit rows |

What Trino on one node gives up versus Athena: large scans (tens of GB and up) are bound
by one JVM's memory where Athena fans out; a spot interruption kills in-flight queries;
the 07:30 KST node start adds ~1 min of Trino warm-up. What it gains: sub-second
interactive queries (Athena has a 1–3 s queue + S3 result round trip per query), one
dialect and one error/type mapping, federated sources with a catalog file instead of a
per-source Lambda, and a reference deployment that matches the portability claim.

## Goals

1. **Phase 1 — engine.** The AWS Single-Node Reference runs Trino in-cluster, reading
   the existing Glue catalog and S3 warehouse. `QUERY_ENGINE` is Trino everywhere.
   Athena code, config, IAM, alarms and docs are removed in the same change set, after
   the live switch is verified.
2. **Phase 2 — connectors.** A connector *is* a Trino catalog. Creating a connection in
   the console registers a catalog; introspection reads the source's
   `information_schema` through Trino; a sync is a Trino `INSERT`/`MERGE` from the
   source catalog into the Iceberg catalog, with PII masking expressed in the SELECT.
   Rows never pass through the backend.
3. **Phase 2 — federation.** Registered source catalogs are directly queryable through
   the governed SQL path (`/queries/execute`, Query Lab, AI SQL, metrics), subject to
   the same per-caller access control as everything else.

## Non-goals

- EKS, multi-worker Trino, or HA. One coordinator-as-worker on the node, as the chart
  already renders it. If large-scan demand appears, the answer is a bigger node or
  workers, not Athena.
- Replacing the REST API, Custom (Python) and S3-object connectors. Trino has no
  connector for an arbitrary REST API or a Python callable; those keep the existing
  pyiceberg write path.
- Trino's *dynamic* catalog management (`catalog.management=dynamic`, `CREATE CATALOG`).
  The Trino docs mark it experimental and the full statement, secrets included, is
  logged and shown in the web UI. Not acceptable for a governance product.
- Airflow-driven sync schedules. Unchanged (and still inert where Airflow is off).
- Athena Federated Query as the connector mechanism. Rejected: per-source Lambda
  deployments, AWS-only.
- Keeping `QUERY_ENGINE=athena` as a dormant option (decided against, see Why).

## Anti-goals (would make this a failure even if it works)

- Source credentials visible anywhere they are not today: Trino web UI, Trino logs,
  `kubectl describe`, catalog ConfigMaps. They go only into a Kubernetes Secret, and
  catalog files reference them as `${ENV:...}`.
- Knowledge/RAG, or any Portable Core page, depending on Trino. Rule 1 stands: the
  core must start with every add-on disabled; `connectors`, `catalog`, `query`,
  `dashboards` are the capabilities that now require Trino.
- A console user with `connector:write` being able to read a source table that the
  connector's owner never shared. Federation must respect `connector_members`.
- A silent data break on cutover: anything stored as `AwsDataCatalog.<schema>.<table>`
  must still resolve after the catalog is called `iceberg`.

## Constraints

- Trino reads static catalog `.properties` files at startup only (the chart already
  says so at `trino-deployment.yaml:27`). Adding or changing a catalog therefore means
  a Trino restart. On a single replica that is a ~30–60 s query outage. Accepted for an
  admin-only, infrequent action; the console must say so.
- The node IAM role already holds the Glue and S3 permissions Trino needs, and Trino's
  Iceberg connector with `iceberg.catalog.type=glue` uses the default AWS credential
  chain, i.e. IMDS. The chart's NetworkPolicy (`networkpolicy.yaml`, on in
  prod-single) denies 169.254.169.254 to every pod except `backend` and `litellm`, so
  Trino must be added to that allow-list. Doing so gives the Trino pod the whole node
  role (Glue, S3, Bedrock, SES, CloudWatch, ECR, STS). K3s has no per-pod IAM; the
  backend, which also executes untrusted caller input, already holds the same role. See
  "Decided by the owner" for the ruling on this.
- All 23 tables in Glue `default` are `table_type=ICEBERG` (checked 2026-11-09), so a
  single Iceberg catalog covers them; no `hive` catalog is needed.
- Memory budget on the m6i.xlarge: Trino at the chart defaults (2–4 Gi) fits beside
  backend ×2, frontend ×2, LiteLLM, MLflow, Valkey with headroom. No instance change.
- Repo conventions: merge only at 0 fail / 0 pending in CI; chart tests cover rendered
  templates; `docs/` is product truth and must be updated with the code.
- The 2026-11-06 re-provision runbooks (`DISASTER_RECOVERY.md` §A.2, `DEPLOY_SINGLE_NODE.md`)
  must still be correct after this: the first install on a fresh node and
  `deploy-aws.yml` both gain a Trino pod.

## Design

### Phase 1 — Trino replaces Athena on the AWS reference

**Chart.** `values-prod-single.yaml` sets `trino.enabled: true`, `polaris` stays off,
`catalog.backend: glue` stays. The Trino templates gain a Glue-typed Iceberg catalog:

```properties
connector.name=iceberg
iceberg.catalog.type=glue
hive.metastore.glue.region=<storage.region>
hive.metastore.glue.default-warehouse-dir=<catalog.glueWarehouse>
fs.native-s3.enabled=true
s3.region=<storage.region>
```

rendered when `catalog.backend == "glue"`, in place of the Polaris REST catalog that is
rendered today only when Polaris is on. The catalog name stays `iceberg` (what every
other profile already uses, and what `RLS_DEFAULT_CATALOG`/`TRINO_CATALOG` default to).
`trino.extraCatalogs` keeps working. The backend's derived env (`QUERY_ENGINE`,
`FEATURE_ATHENA`, `RLS_DEFAULT_CATALOG=AwsDataCatalog`, `RLS_DEFAULT_SCHEMA`, the
`athena*` catalog keys) collapses to the Trino values; `catalog.athenaOutputLocation`,
`athenaWorkgroup`, `athenaDatabase` are removed from values and templates.

**Backend.** Remove `AthenaEngine`, the Athena branch in `ai_vectors.py` (catalog
bridge preview), the `ATHENA` capability backend, `FEATURE_ATHENA` in
`service_registry.py`/`component_guard.py`, the `athena` dialect value, `pyathena`.
`catalog_registry.py` stops special-casing the engine name on the glue backend: a glue
catalog's `engine_catalog` is whatever Trino calls it (`iceberg` by default). The
"Amazon Athena" entry disappears from Services; Glue stays listed as the catalog.

**Stored names (alias, not rename).** The registry already distinguishes a catalog's
`name` (registry key, what users and stored rows say) from `engine_catalog` (what the
engine calls it), and `catalog_registry.resolve()` accepts either. So nothing stored is
rewritten: one data-only migration (`0025_engine_catalog_glue`) sets
`engine_catalog = <TRINO_CATALOG, default iceberg>` on the glue-kind row whose
`engine_catalog` is `AwsDataCatalog`, and `AwsDataCatalog` stays the registry name,
permanently valid as an alias. Everything that turns a stored catalog name into SQL
(`table_resolver`, `semantic/compile.py`, the catalog-bridge freshness run over
`ai_chunks.source`, and `rls/engine.py::_policy_key` when matching
`rls_policies.catalog_name` / `column_masking_policies.catalog_name`) must canonicalise
through the registry to the engine name before comparing or emitting. That is the
builder's checklist, and the tests for it are: a metric stored against
`AwsDataCatalog.default.t` compiles to `iceberg.default.t`; a row-filter policy stored
on `AwsDataCatalog.default.t` still applies to a query that says `iceberg.default.t`
or bare `t`. `catalog_grants.catalog_name` (FK to `data_catalogs.name`) is untouched.
History and audit tables are left alone. Live today: 0 RLS and 0 masking policies, so
the cutover risk is in the mechanism, not the data.

**Frontend.** Remove the Athena wording and the `query_engine === "athena"` branch in
`lib/product-profile.ts`; help pages (`help/sql-lab`, `help/catalog`) describe Trino
over Glue.

**Terraform.** Drop the `athena:*` actions from the node role, the
`athena_daily_scan` alarm and dashboard widgets, `var.athena_daily_scan_alarm_tb`. Glue
permissions stay. No new resources: Trino is a pod.

**Docs.** `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `DEPLOYMENT_PROFILES.md`,
`DEPLOY_SINGLE_NODE.md`, `PORTABILITY.md`, `PRODUCT_CONCEPT.md`, `AWS_MVP_RUNBOOK.md`,
`DEMO_SCRIPT.md`, `RLS_DESIGN.md`, `UPGRADING.md`, `DISASTER_RECOVERY.md` and the other
files that say "Glue/Athena" now say "Glue catalog, Trino engine". The AWS reference
line becomes: S3, Aurora, Glue, Bedrock; Trino in-cluster.

**Cutover on the live node** (operator steps, in the plan): deploy the chart change
with Trino on and the backend still on Athena is *not* possible once the env derivation
changes, so the cutover is one `helm upgrade` from a build that already contains the
backend changes: Trino pod comes up → backend restarts on `QUERY_ENGINE=trino` →
migration renames stored catalog names → verify Query Lab, Catalog preview, a metric
query, and the catalog-bridge freshness run against Glue tables → then merge the
Athena-removal commits (they are in the same PR, ordered after the switch commit, so a
revert of the removal alone is a clean operation).

**Verification.** Chart tests for the Glue catalog rendering and for the absence of
Athena keys; backend tests updated where they asserted Athena behaviour (22 files
reference it today); acceptance run against the deployed target. Live check list above.

### Phase 2 — connectors as Trino catalogs

**Model.** A `connector_connections` row of a *Trino-backed* type maps 1:1 to a Trino
catalog named `src_<slug>` (slug from the connection name, unique, ≤ 32 chars, stable
after creation). Trino-backed types in the first cut: `postgresql`, `mysql`,
`sqlserver`, `oracle`, `mongodb`. (`kafka`, `kinesis`, `azure_blob`, `gcs`,
`database_url` follow the same shape and can be added when wanted; `rest_api`,
`custom`, `s3` stay on the Python path — see Non-goals.) The `ConnectorType` enum
gains an `engine` attribute: `trino` or `python`.

**Catalog delivery (my call).** The backend owns one Kubernetes Secret,
`trino-source-catalogs`, in the release namespace. Each key is a catalog file
(`src_<slug>.properties`) whose connection string and user are literal and whose
password is `${ENV:SRC_<SLUG>_PASSWORD}`; a second Secret, `trino-source-credentials`,
holds the passwords and is mounted as env into the Trino container. Both are created
empty by the chart and patched by the backend through the in-cluster service account
(RBAC: `get`/`patch` on exactly those two Secrets, `patch` on the Trino Deployment for
the restart annotation). Creating, updating the credentials of, or deleting a connection
patches the Secrets and bumps the restart annotation; the console shows "query engine
restarting (~1 min)" from the Trino readiness probe. The plaintext never touches a
ConfigMap, a log, or the Trino UI.

Why not the alternatives: Helm-values-only catalogs (operator edits values, no console
self-service) would remove the connectors UI the product already has; dynamic catalogs
are ruled out above.

The existing Fernet vault keeps the credentials in Aurora as today (the connection
form, test and edit flows are unchanged); the Secret is a projection of it, rebuilt
from the vault on backend start if missing (so a fresh cluster after DR recovers its
catalogs from the database + `ENCRYPTION_KEY`, consistent with the DR ordering rule).

**Test / introspect.** `POST /connectors/test` cannot go through Trino before the
catalog exists, and registering a catalog just to test it would cost a restart. So the
pre-create test stays driver-based in the backend, as today (the drivers are already
dependencies for PostgreSQL/MySQL; SQL Server, Oracle and MongoDB get the same thin
"can I connect" check via their Python drivers, a small, bounded amount of per-source
code and the only per-source Python that remains). Introspection after creation goes through Trino:
`SHOW SCHEMAS FROM src_x`, `information_schema.columns`. The table list the console
shows is Trino's view of the source, so types are already Trino types.

**Sync.** A sync of `src_x.s.t` into `iceberg.<ns>.<t>` is one Trino statement built
by the backend:

- full: `CREATE TABLE IF NOT EXISTS iceberg.ns.t (...) WITH (partitioning = [...])`
  from the introspected schema plus the job's partition spec (`partitioning.py` logic
  reused to produce Trino partitioning transforms), then `DELETE FROM iceberg.ns.t`
  + `INSERT INTO ... SELECT <projection> FROM src_x.s.t`;
- incremental with a watermark column: same `INSERT ... WHERE col > ?` with the stored
  watermark, then `SELECT max(col)` to advance it;
- with key columns: `MERGE INTO iceberg.ns.t USING (SELECT ... FROM src_x.s.t) ON keys
  WHEN MATCHED THEN UPDATE ... WHEN NOT MATCHED THEN INSERT ...`.

The `<projection>` applies the job's `pii_columns` using the masking expressions that
`app/rls/engine.py` already emits in Trino dialect, so masking-at-ingest is the same
function as masking-at-read. `rows_processed` is the statement's row count; progress
events come from Trino's query stats polled by the existing SSE stream. Lineage and
OpenMetadata registration (`register_lineage`, `register_om_table`) are unchanged;
`connector_sync_jobs` rows are written as today. Schema evolution: new source columns
are added with `ALTER TABLE ... ADD COLUMN` before the insert; type changes fail the
job with a message, as the pandas path does today.

Trino runs the statement as the DataPond backend's Trino user, not as the console
user, because a sync is a system action; the audit row records who triggered it.

**Federation.** Source catalogs are plain Trino catalogs, so `/queries/execute` can
read `src_x.s.t` with no new code path. Each `src_<slug>` is also a `data_catalogs`
row (new kind `trino_source`, `engine_catalog = src_<slug>`), created and deleted with
the connection, so the one existing per-catalog ACL applies: `catalog_grants`
(`catalog_access.py`, the `catalog_allowed` hook in `table_resolver`), Settings → Data
catalogs, the semantic layer's `catalog` column, the `metric_*` tools and catalog audit
all see a source catalog the same way they see `iceberg`. The connection's owner and
`connector_members` are projected into `catalog_grants` for that row on every
membership change, so there is one ACL, not two. The backend resolver refuses an
unqualified or qualified `src_*` reference from a caller without a grant (fail closed).
RLS Layer 2 (`trino.rls.enabled`, the Trino file ACL) stays **off** on the AWS
reference: Trino is ClusterIP-only and the backend is its only client, so Layer 1
enforcement in the backend is the boundary, as it is today for `iceberg`. Where an
operator does turn Layer 2 on, `trino_acl.generate_rules()` emits a `catalogs` section
from the same grants. Row filters and column masks defined on a source table FQN work
through the same policy tables as Iceberg tables.

**Capabilities.** `connectors` requires `TRINO` (drop `POLARIS`, `GLUE` from its
backend list). On the AWS reference this is now true; on `values-foundation.yaml` and
Sovereign Core it stays false, as it should.

**Removal.** `connectors/database.py` (SQLAlchemy/pandas sync for PostgreSQL/MySQL)
goes once the Trino sync is verified against the live PostgreSQL connection; the
`iceberg_writer.py` path stays for REST/Custom/S3.

**Verification.** Chart test: Secrets, RBAC, env mount rendered when `trino.enabled`.
Backend tests: catalog-file rendering (no plaintext password), statement builders
(full/incremental/merge/PII projection), refusal of `src_*` reads without a grant.
CI today runs Trino only in the multi-catalog job (`ci/values-multicatalog.yaml`,
Polaris-backed); the default kind run (`values-ephemeral.yaml`) has Trino off. Phase 2
adds a Trino-enabled acceptance job that registers the in-cluster PostgreSQL as a
connector (through a restricted DB role, see samples below), syncs one table and reads
it back federated. The Glue catalog template can only be exercised on the live node;
CI covers its rendering. Live: re-register the existing PostgreSQL connection on the
AWS node and run its sync history forward one more time.

**Sample sources and `database_url`.** Both SQL sample sources (`_add_postgres_sample`,
`_add_finance_sample`) connect to the application's own database with the backend's
credential, and the finance one is type `database_url`. Through Trino with that
credential the catalog would expose every schema of the app DB (users, keys, audit) to
anyone granted the sample catalog. Owner's decision: they go through Trino like any
other connection, but through a **restricted database role**: the backend creates (or
the schema migration creates) a login role `datapond_sample` with `USAGE` + `SELECT`
on the sample schema(s) only, generates its password, stores it in the vault like any
connector credential, and registers the sample catalog with that role. The
`database_url` type is folded into `postgresql`/`mysql` (a URL is just another way to
fill the same form; the enum value stays accepted on input and is normalised). With
that, `connectors/database.py` is removed entirely in Phase 2. "Add sample data" now
costs one engine restart (~1 min) before the activation sync can run; the console and
`DEMO_SCRIPT.md` say so.

**Extra Glue catalogs** (cross-account `catalog_id`/`role_arn` registry entries;
live has none) are not queryable through Trino in Phase 1: they stay catalog-bridge
only, and `_trino.tpl` does not grow a glue type for `extraCatalogs` yet. Documented
limitation; revisit with the Phase 2 Secret mechanism.

## Order and size

Two PRs, Phase 1 then Phase 2; Phase 2 depends on Trino being on the reference. Phase 1
is mostly deletion plus one catalog template and one data migration. Phase 2 is the
larger piece: catalog delivery, statement builders, federation ACL, UI copy.

## Decided by the owner

- Unify on Trino; remove Athena rather than keep it as an option (2026-11-09).
- Connectors go through Trino's connectors instead of per-source Python (2026-11-09).
- Glue stays as the catalog on AWS (confirmed by the owner's "Athena → Trino" framing;
  the catalog was never in question).
- Trino is added to the NetworkPolicy's IMDS allow-list and uses the node role
  (2026-11-09). Documented as a known limitation of the single-node reference: no
  per-pod IAM on K3s; a role split belongs to an EKS/IRSA profile, not this one.
- Sample SQL sources become Trino catalogs through a restricted `datapond_sample` DB
  role; `database_url` is folded into `postgresql`/`mysql`; `database.py` is removed
  (2026-11-09).

## My calls (check these)

- `AwsDataCatalog` becomes an alias (`engine_catalog` changes, stored names do not).
- Catalog delivery via backend-managed Secrets + Trino restart, not dynamic catalogs
  and not Helm-values-only.
- Catalog naming `src_<slug>`; Iceberg catalog stays `iceberg`; every `src_*` is a
  `data_catalogs` row and inherits the existing catalog ACL.
- RLS Layer 2 stays off on the AWS reference; the backend is the enforcement boundary.
- Extra Glue catalogs stay catalog-bridge-only in Phase 1.
- First-cut Trino-backed types: PostgreSQL, MySQL, SQL Server, Oracle, MongoDB.
- Connection *test* stays driver-based in the backend; introspection and sync go
  through Trino.
- Sync statements run as the backend's Trino identity; federation reads run as the
  caller.
- History/audit rows are not rewritten by the catalog-rename migration.
- Chart Trino sizing left at defaults (2–4 Gi, 2 G heap) on the m6i.xlarge.

## Left to the builder

- Exact Alembic migration mechanics and the dry-run report before it rewrites rows.
- How the console surfaces the Trino restart (polling the readiness probe vs a
  backend status endpoint).
- Trino type → Iceberg type mapping edge cases (e.g. MongoDB documents, Oracle NUMBER
  without scale).
- Whether `CREATE TABLE ... AS SELECT` is used for the very first full sync instead of
  create-then-insert.
- Test fixtures for the five Trino-backed types without live databases (statement
  builders are pure functions; CI only has PostgreSQL live).
- Order of doc edits and which "Glue/Athena" sentences become "Glue + Trino".
- Exact property names for Trino 482's Glue-typed Iceberg catalog (the ones above are
  from docs mirrors; confirm against the release's connector page before rendering).
