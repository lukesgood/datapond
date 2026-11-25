# Upgrading

Changes that alter behaviour for people already using a deployment. Everything else is
in the commit history; this file exists for the things an operator has to act on.

## 2.7 (2026-11) — Two catalogs at once, one writer per table

**Live AWS Single-Node Reference, 2026-11-12** (PR #259, release revisions 17–18, tag
`2.7.0-0065885`): migration 0028 applied; the rehearsal-only Polaris metadata database was
dropped and Polaris now runs **permanently beside Glue** — 2 replicas, metadata in Aurora,
catalog `lake` at `s3://datapond-iceberg/polaris/lake`, Trino catalog `polaris_lake`, no
shared locations and no location feature flags. Glue stays the default catalog (AWS
services read it). Verified: a sync with `target_catalog: polaris_lake` landed
`public.customers` (1,200 rows, equal to the source) in Polaris; a join across Polaris and
Glue answers; Glue's tables are unchanged; no mirrors exist; a source catalog as a sync
target is refused (400).

- **Migration 0028** adds `catalog_table_links` (owner/mirror per table) and
  `connector_sync_jobs.target_catalog`. Run the migration Job (CD does).
- **Export modes.** `POST /api/catalogs/{name}/export` takes `mode: mirror` (default — the
  source stays the owner, the target is a read-only mirror) or `move` (the target becomes
  the owner). Applied exports record the links; the response lists
  `allowed_locations_needed` (each table's parent prefix) for a Polaris target.
- **Guards.** Writes and DROPs through a mirror get 409 naming the owner; reads of a mirror
  run against the owner (its grants and policies). `GET /api/catalogs/mirrors`,
  `POST /api/catalogs/mirrors/check`; a background check every `MIRROR_CHECK_SECONDS`
  (default 300; `MIRROR_CHECK_ENABLED=false` turns it off) re-points stale mirrors and marks
  outside commits `diverged`.
- **Sync target.** `POST /connectors/{id}/sync` accepts `target_catalog` (lake catalogs only),
  remembered per table; omitted keeps the default catalog.
- **Polaris** no longer purges files on DROP when it shares locations
  (`polaris.storage.extraAllowedLocations` set).
- **`catalog:write` (2026-11-13, PR #263).** A new permission held by admins and the
  `data_engineer` role opens the catalog export and `GET`/`POST /api/catalogs/mirrors…` (they
  were admin-only). Console: Export… and Mirrors appear for those roles, also on the Catalog
  page. Creating, editing, defaulting and granting catalogs stay admin-only.
- **Migration 0029** adds the audit event types `catalog_exported`, `catalog_mirror_diverged`,
  `sync_target_recreated` and `sync_jobs_pruned`; until it ran, those audit rows were dropped
  silently (the insert is best-effort). Run the migration Job (CD does).
- **A PII column you name is never stored in the clear (2026-11-13).** Masking replaced only
  values that match a pattern (resident number, phone, email, card…), so a named column such
  as `full_name` passed through. A column listed by name in a table's PII columns is now
  pattern-masked and, when no pattern matched, replaced whole with `[개인정보]`. `*` (every text
  column) stays pattern-only. Takes effect on each table's next sync; a full sync rewrites it.
- **Polaris token key.** Every Polaris replica signs tokens with `POLARIS_TOKEN_KEY` (generated
  in `datapond-secrets`, lookup-preserved); before this, two replicas refused each other's
  tokens (401). On the AWS reference Polaris runs one replica with a 50m CPU request.

**Console menu by the data's path (2026-11-23).** Sections are now Data (Sources,
Transforms, Streaming, Catalog), Semantic (Semantic model — the former Metrics page, with
Metrics, Joins and Concepts tabs), Use (Analytics, Knowledge, Notebooks, Experiments,
Agents) and Operate (Governance, AI Gateway, Storage, Infrastructure, Settings). URLs are
unchanged; bookmarks keep working. Menus are not per role: each item is gated by its
permission as before, so a role sees only its own part of the path.

**Concept feedback (migration 0032, 2026-11-23).** With concepts on, every `/ai/sql`
generation (console and MCP `query_generate_sql`) writes one `concept_feedback` row: the
question masked like the tool-call log, matched concepts, joins between keys of different
concepts, and literal condition values (values holding personal data are dropped). Rows
older than 90 days are deleted as new ones arrive. `GET /api/semantic/concepts/feedback`
(governance:read) aggregates the last 30 days; nothing is bound automatically.

**Concept parent by id (migration 0033, 2026-11-23).** `ontology_concepts.parent_id`
references the parent concept and is backfilled from the text `parent` column, which is
no longer read or written and is dropped by a later contract migration. Renaming a concept
(`PATCH /api/semantic/concepts/{name}`, Semantic model › Concepts › Edit) keeps its
bindings and narrower concepts, and by default keeps the old name as one of its words. A
parent must name an existing concept and may not make a cycle (422); `/ai/concepts/import`
reports parents it could not resolve as `unresolved_parents`.

**Sources: what a sync runs, and masks on direct source reads (2026-11-23).**
- A bare job name saved before 2.5 (`customers`) that matches exactly one table the source
  lists (`public.customers`) is renamed to it on the next table list or sync, so its
  settings — PII columns included — follow the table. Before this, the qualified table
  looked new and would have synced without its masks.
- The first sync of a source adopts every table, as before. After that a table new in the
  source is listed as new and is not synced until someone turns it on. The full "Sync now"
  honours the per-table switch (it used to sync every listed table).
- Jobs for tables the source no longer lists are shown under "Not in the source any more"
  and can be deleted (`DELETE /api/connectors/{id}/jobs/{source_table}`); the lake table
  stays.
- A job's PII columns are also masked when its source catalog is queried directly, for
  every role, through the same enforcement as other masks (derived, not listed among
  Governance policies; refreshed within a minute of a change).
- Column masks now list the table's columns instead of `SELECT * EXCEPT (…)`, which Trino
  does not support: before this, any query on a table with a column mask failed with a
  syntax error. A masked table whose columns cannot be read is refused.

**Sources: syncs that outlive the page, one-request setup (2026-11-23).**
- A sync started from the console keeps running if the page closes or the connection
  drops, and writes its run history as usual; the stream sends a keepalive comment every
  15 s. The page says the connection was lost instead of staying on "Syncing…".
- New jobs store `datapond.default.<table>` (no source schema). Older rows that say
  `datapond.default.public.orders` land in the same table and are left as they are. A
  sync of such a row now marks RAG collections over `default.orders` stale; it used to
  look for `public.orders` and miss them.
- `PUT /api/connectors/{id}/tables` saves many tables' choices in one transaction (the
  setup wizard used two requests per table). After "Create and sync" the source page runs
  the first sync and shows its progress; the list's "Sync now" opens that page too.
- `GET /api/connectors/connections` returns each source's `tables` (enabled jobs),
  `last_rows` and `success_rate` (last 20 runs). The list column is now "Synced tables";
  it used to count every table the source lists, by asking each source live.

**Sources: data quality checks read the right table (2026-11-23, migration 0034).**
- Quality checks now query the lake table the sync wrote (`default.orders` for
  `public.orders`). They used to query `iceberg.default.public.orders`, so the null-rate
  checks of every schema-qualified table failed silently since 2.5.
- Checks written as `orders` (before 2.5) and `public.orders` are one table: the source
  page shows the newest, and the row-count comparison reads the previous count under either
  name. `GET /api/connectors/{id}/quality` returns `table_key` for grouping.
- A column can be marked expected to be mostly empty
  (`PUT /api/connectors/{id}/tables/{table}/expected-nulls`, `{column, expected}`): its null
  rate is still recorded but no longer warns, on the check already shown and on later ones.
  Migration 0034 adds `connector_sync_jobs.expected_null_columns` (expand-only).
- Smaller: the empty Sources page lists the source types that can actually be added; SSL
  help no longer says "JDBC"; source status reads "Active"; the table browser also hides
  `pg_toast`; the unused `table-selector` component is gone.

**Catalog: source keys and table profile (2026-11-23, migration 0035).**
- The relationship graph reads primary and foreign keys declared in source databases
  (PostgreSQL sources, through Trino's `system.query`; cached), and carries them to the
  lake tables those sources sync into when both ends are synced. A declared key shows as a
  solid edge marked "declared key" (or "key (from source)") with a JOIN to open, even if
  nobody has run it; a name-match guess for the same pair is dropped.
- `GET /api/catalog/tables/{ns}/{t}/keys` and `/profile`. The table page has a Profile
  tab: per-column empty share, distinct estimate and range from the table's statistics (no
  scan), recent Iceberg snapshots, and the keys. Under a row policy the table-wide figures
  are withheld; masked and PII-bound columns show no range. The Schema tab marks PK/FK.
- A join proposed from a foreign key records `source = 'fk'` (migration 0035 widens the
  `semantic_joins` source check; the previous release never writes it).

**Catalog: search by column and business word (2026-11-24, no migration).**
- `GET /api/catalog/search?q=` (`catalog:read`) matches table names, column names, concepts
  (name and aliases) and metrics (name, label, synonyms). A matched concept brings the
  columns bound to it (key and attribute bindings) and its segments, so 고객 finds
  `customers.id` and `orders.customer_id`. Every hit says why. Only catalogs the caller may
  use are searched; nothing reads a row.
- The column index is one `information_schema.columns` read per catalog, cached five
  minutes per backend process (live: four catalogs, about 3 s uncached). A catalog that
  cannot be read is skipped, so one source down does not empty the search.
- The Catalog search box now also shows what it found beyond names (a summary line and
  Concepts / Columns / Segments / Metrics) and adds those tables to the list, each with its
  reason. The agent tool `catalog.find_tables` is unchanged (names only).

**Catalog: Data map with four modes, and column drill-down (2026-11-24, no migration).**
- The Catalog's "Relationship map" is now **Data map**: one centre table, four modes.
  Relationships (as before); Lineage (upstream and downstream from the flow map: syncs,
  streams, transforms); Schema (the centre and up to five known neighbours — columns,
  source PK/FK, concept chips, join columns, snapshots); Concepts (approved concepts on the
  table and the other tables holding each). Picking a table in any mode re-centres all.
- `GET /api/catalog/tables/{ns}/{t}/columns/{col}/values` (`query:run`): top 20 values by
  rows, empty share and a distinct estimate, run through the governed query path as the
  caller (grants, row policies, masks, PII guardrail, tool-call audit). A masked column, a
  PII-bound column or a complex type returns counts only (`hidden` with the reason).
- The drill-down (Profile tab "values ›", or a column in Schema mode) shows the values, what
  the column means (segments, concept bindings) and its declared joins, and can make a value
  a segment (new concept under the table's key concept, or an existing one) or bind the
  column to a concept — through the existing concept and binding APIs and their
  permissions; a non-admin's binding is a proposal. A new concept name that already exists
  is refused (creating it would overwrite the existing one).

## 2.6 (2026-11) — Lakehouse first: catalog export, Trino workers, menu

Positioning v7 (`docs/POSITIONING_V7.md`): DataPond is a lightweight open lakehouse; the AI
features are a layer on top of it. Nothing is removed and no migration is added.

**Live AWS Single-Node Reference: deployed 2026-11-12** (PR #256, release revision 12, tag
`2.6.0-01a1ef2`). Verified on the node: Trino reloaded with `register-table-procedure`;
Glue and source-catalog queries answer (6,000 each); the export refuses a source catalog
and the same catalog with 400; no worker (none configured); the new menu is in the build.
Same day, a live Glue → Polaris rehearsal registered all 23 `default` tables in a
temporary Polaris (revisions 13–16; row counts equal, Glue untouched), then turned Polaris
off again. It needed two chart fixes (#257 Polaris on the external database, #258 its
catalog on native S3). Record: `PORTABILITY.md`.

- **Catalog export.** `POST /api/catalogs/{name}/export` (admin) registers a catalog's
  Iceberg tables in another catalog without copying data — plan by default, `apply: true`
  to register and compare row counts. The chart now sets
  `iceberg.register-table-procedure.enabled=true` on every Iceberg catalog it renders
  (Trino restarts once on upgrade). A Polaris target must accept the source's location
  (`polaris.storage.extraAllowedLocations`) and, for the migration only, the opt-in feature
  flags in `polaris.extraFeatures`. Procedure and the security caveat: `PORTABILITY.md`.
- **Trino workers.** `trino.workers.replicas` (default 0 — unchanged). With workers the
  coordinator only plans (`node-scheduler.include-coordinator=false`); workers read the
  same catalogs and credentials, are restarted with the coordinator when source catalogs
  change, and `GET /api/connectors/engine` reports ready only when both are back. Sizing:
  `trino.workers.heap`, `.maxMemoryPerNode`, `.resources`.
- **Console menu.** Lakehouse (Catalog, Analytics, Sources, Metrics) leads; Knowledge,
  Agents and AI Gateway move into an AI section; Operate keeps Governance, Storage,
  Infrastructure and Settings. The dashboard's core workflow is Connect → Organize →
  Query → Govern → Add AI on profiles with a query engine, and unchanged without one.

## 2.5 (2026-11) — Database sources are Trino catalogs

A database connection is now a Trino catalog, and Trino does the reading and the
syncing. Phase 2 of `docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md`
(plan: `docs/superpowers/plans/2026-11-10-trino-connectors-phase2.md`).

**Live AWS Single-Node Reference: cut over 2026-11-10** (PR #251, release revision 6, tag
`2.5.0-fb4121d`, deployed through `deploy-aws.yml` from `main`). Verified on the node: migrate Job
`backend-migrate-6` ran 0026 and 0027; the two pre-existing SQL sample connections became
`src_sample_e_commerce_db` and `src_sample_finance_db` at backend start with no
re-registration (the finance row, stored as `database_url`, was rewritten as PostgreSQL);
Trino restarted once (annotation `datapond.io/source-catalogs-restarted-at`) and
`SHOW CATALOGS` lists both; `SELECT count(*) FROM src_sample_e_commerce_db.public.orders`
answers 6,000 through SQL Lab's route; the samples re-added through
`POST /connectors/sample-sources` connect as `datapond_sample`, which the app database
refuses (`SELECT 1 FROM users` → insufficient privilege) and the sample database serves. A follow-up the same day (PR #252, release revision 7, tag `2.5.0-4090015`) let a `decimal(p,s)` source load into the `double` targets the pandas path had written — the first sync forward of `public.orders` had refused `total_amount`. The review's deferred minors followed on 2026-11-11 (PR #253, release revision 9, tag `2.5.0-ec8ee4a`); live check: `PUT /catalogs/src_sample_e_commerce_db/grants` answers 409, grants still read, federation answers 6,000.

- **Five source types, one engine.** PostgreSQL, MySQL, SQL Server, Oracle and MongoDB
  connections are Trino catalogs named `src_<slug>` (slug from the connection name;
  `src_sales_db`, `src_sales_db_2` on a clash). The Sources page browses them through
  Trino, SQL Lab federates them (`SELECT … FROM src_crm.public.orders JOIN iceberg.default.…`),
  and a sync is Trino SQL: `CREATE TABLE IF NOT EXISTS` with the table's partitioning,
  `CREATE OR REPLACE TABLE … AS SELECT` (full: one Iceberg commit, so a reader during the
  load sees the previous rows and a failed load changes nothing; the previous snapshot
  stays in the table history), `MERGE` on the key columns or `INSERT … SELECT` with a
  bound watermark cast to the column's type (incremental), `ALTER TABLE … ADD COLUMN`
  for new source columns. A column whose type changed stops the sync with a message
  naming it, except a target column that is wider than the source (`bigint` for
  `integer`, `double` for `real` or `decimal(p,s)` — the pandas path wrote every
  NUMERIC as a double): the load casts up. PII columns are masked inside the
  `SELECT` (`pii_ko.mask_sql`) — the raw value never reaches the lake.
- **A source catalog's grants are the source's share list.** `PUT /catalogs/src_x/grants`
  answers 409; share or unshare the source (Sources, or `POST`/`DELETE
  /connectors/{id}/members`) and the grants follow. Source previews are ordered by
  their first column so pages are stable; the Secret projection runs under a Postgres
  advisory lock, so two replicas starting together restart Trino once.
- **Unqualified table names resolve against the lake catalogs only.** A source catalog
  is a customer's live database; `SELECT … FROM orders` never reaches it. Federate it by
  its qualified name: `src_crm.public.orders`.
  Nothing passes through the backend's memory any more.
- **Two Secrets, one restart.** The backend renders the catalog files into the Secret
  `trino-source-catalogs` and the passwords into `trino-source-credentials` (both
  lookup-preserved; the backend Role may `get`/`patch` exactly these two), then bumps
  the `datapond.io/source-catalogs-restarted-at` annotation on the `trino` Deployment.
  Trino reads catalog files only at start, so **creating a connection, changing its
  credentials or deleting it restarts the engine (~1 min)**. The console shows a banner
  and holds Sync; `GET /api/connectors/engine` reports `restarting`/`ready`;
  `POST /connectors/sample-db/activate` waits up to 180 s and answers 503 if the
  engine is still down.
- **Existing PostgreSQL/MySQL connections need nothing.** On the first backend start
  after the upgrade every stored connection of a Trino type without a registry row is
  registered (`source_catalog.ensure_rows`) and projected; its owner and members become
  catalog grants. No re-registration, no re-entry of credentials. Targets the pandas
  path wrote (`bigint`/`double` where the source says `integer`/`real`) load with casts.
  Migration `0027` widens the registry's kind check to admit `trino_source` — the
  migration Job must run before the first connection is created on 2.5.
- **The engine status is time-bound.** `GET /api/connectors/engine` reports
  `restarting` for up to 10 minutes after a projection; an engine that is down later
  reports `ready: false, restarting: false` and the console says so instead of
  "restarting (~1 min)".
- **`database_url` is folded.** The SQLAlchemy URL type is gone from the create form and
  `/connectors/available`. Stored rows of that type keep working: the backend reads the
  URL as a PostgreSQL or MySQL source (other dialects are refused with 422 naming the
  type). On the first backend start after the upgrade such rows are rewritten as that
  type (`source_catalog.rewrite_legacy_rows`), so the console edits them with the
  PostgreSQL/MySQL form; a config save does the same. New payloads naming
  `database_url` are normalised at once.
- **Samples connect as a read-only role.** The e-commerce and finance samples are
  PostgreSQL sources whose user is `datapond_sample`, created by **migration 0026** from
  `SAMPLE_DB_PASSWORD` (the chart generates and preserves it in `datapond-secrets`;
  override with `postgres.auth.samplePassword`, letters and digits only). Run the
  migration Job once after the upgrade; without the variable the sample routes answer
  409 and say so. The application's own PostgreSQL password is no longer stored in any
  connection.
- **`connectors` capability needs `trino` only.** A profile with a Glue or Polaris
  catalog and no Trino has a Catalog page and no Sources page (it could not sync anyway).
  Portable Core · AWS and Sovereign Core are unchanged: no engine, no Sources.
- **RLS Layer 2:** the generated `rules.json` gains a `catalogs` section on the next
  apply — granted users read their `src_*` catalogs, open ones are readable by everyone,
  every other `src_*` is denied, `iceberg` is unchanged.
- **Removed:** `backend/app/connectors/database.py` (the pandas sync path), the
  `PostgreSQLConnector`/`MySQLConnector`/`DatabaseURLConnector` classes, and the
  SQLAlchemy-URL connector type in the console. Drivers for the five types are present
  only for the pre-create test and the pre-create column listing (`app/connectors/probe.py`).
- **Support:** the five types are supported as Trino 482's connectors expose them.
  PostgreSQL is exercised end to end on every CI run (kind); MySQL, SQL Server, Oracle
  and MongoDB are verified by unit tests and the pre-create probe only — `SUPPORT.md`.

## 2.4 (2026-11) — Athena removed; Trino is the query engine on every profile

The AWS Single-Node Reference used Amazon Athena to query the Glue catalog. It now runs
the same in-cluster Trino the OSS profiles run, over the same Glue catalog. One engine,
one SQL dialect, one RLS path; Phase 2 of the same design adds external sources as Trino
catalogs (`docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md`).

- **`catalog.backend=glue` requires `trino.enabled=true`.** The chart refuses to render
  otherwise (`datapond.engineGuard`). `values-prod-single.yaml` sets it; a deployment that
  holds stored release values from before 2.4 (`trino.enabled: false`) must re-supply its
  overrides once with `helm upgrade --reset-values -f values-prod-single.yaml -f
  <overrides>` — `DEPLOY_SINGLE_NODE.md` §5b has the exact steps. The node needs ~2 GiB
  more memory for the Trino coordinator (m6i.xlarge or t3.xlarge is fine).
- **`catalog.athenaOutputLocation`, `catalog.athenaWorkgroup`, `catalog.athenaDatabase`**
  are gone from the chart and ignored if still present in stored values. The backend env
  `FEATURE_ATHENA`, `ATHENA_*` and `QUERY_ENGINE` are no longer read: the engine is
  always Trino, and `/api/capabilities` reports `"query_engine": "trino"`.
- **Trino must reach IMDS.** The NetworkPolicy allow-list for the node's instance role
  now includes the `trino` pod (it reads Glue and S3 with that role). No new IAM:
  the `GlueDataCatalog` and `S3Data` statements already cover it; the `AthenaQuery`
  statement, the Athena scan alarm and the two Athena dashboard widgets are removed
  from Terraform.
- **Migration 0025** changes `data_catalogs.engine_catalog` from `AwsDataCatalog` to
  `iceberg` (`TRINO_CATALOG`) on the glue row and nothing else. The registry name stays
  `AwsDataCatalog`, so stored metric versions, joins, chunk sources and RLS policies keep
  working: `catalog_registry.resolve()` accepts either name and the RLS policy key is
  canonicalised through it. Both names resolve in SQL (`/queries/execute` rewrites a
  three-part `AwsDataCatalog.<schema>.<table>` to the engine name before the grant
  check and RLS, so stored dashboards and saved queries keep running) and in the console.
- **`pyathena` is no longer a dependency.** `RLS_DEFAULT_CATALOG` is `iceberg` and
  `RLS_DEFAULT_SCHEMA` is `default` on every profile.
- **Support:** Trino leaves the "add-ons this release does not support" list in
  `SUPPORT.md`. It is supported as the chart configures it; a Trino cluster, catalog or
  setting outside that configuration is upstream Trino.
- **Expect** the Glue databases `raw`, `refined`, `serving` to appear after the first 2.4
  backend start (the medallion layout the OSS profiles already have).

## 2026-10 — Governance has a Tool calls tab; "Audit Log" is now "Query log"

- **Governance → Tool calls** (first tab, opens by default) lists every caller's tool
  calls — search, cited answers, metrics, SQL — newest first, with outcome, hits, chunks
  withheld, PII masked and cited sources, filterable by caller and window. Until now the
  console showed them only per agent (Agents → the agent → Activity) or as the Reports
  export. It needs `audit:read`, like the export.
- The tab formerly called **Audit Log** listed SQL executions only and is renamed
  **Query log**. Nothing about what it shows changed.

## 2026-10 — Agents menu; service accounts moved there; the virtual-key card is gone

- **Agents** (`/agents`, administrators) lists every service account and opens one page
  per agent: identity and role, keys (issue, rotate, revoke, OAuth client), the
  collections and catalogs it may read, its attributes, spend and cap, its recent tool
  calls, and disable / delete. Settings → Service accounts is gone;
  `/settings?tab=service` redirects to `/agents`.
- **Disable is now a button** (Agents → agent → Danger zone). It applies within 30
  seconds, the key cache lifetime on each replica; the replica that served the change
  applies it at once.
- AI Gateway → **Caller budgets** shows an agent's cap read-only and links to its page,
  where it is set. People stay editable there.
- New routes behind the page: `GET /api/service-accounts/{id}`,
  `GET /api/service-accounts/{id}/catalogs`, and idempotent
  `PUT|DELETE /api/catalogs/{name}/grants/user/{principal}`.
- **Virtual Keys & Budgets (AI Gateway) is removed.** Nothing in DataPond used those
  LiteLLM keys, and a call made with one bypasses the tool-call log, collection ACLs,
  masking and caller caps. The routes `/api/settings/ai/keys` are **deprecated and will
  be removed in the next release**. **Action:** if your deployment issued any, list and
  delete them while the routes exist:

  ```bash
  curl -s -H "Authorization: Bearer $ADMIN_TOKEN" https://<your-domain>/api/settings/ai/keys
  curl -s -X DELETE -H "Authorization: Bearer $ADMIN_TOKEN" \
       "https://<your-domain>/api/settings/ai/keys/<token>"
  ```

  The live reference deployment had none.

## 2026-10 — Model spend has one view: AI Gateway

Spend was shown four ways. Governance → Cost was a second, smaller copy of AI Gateway's
usage view (same endpoint, `spend:read`; every role that sees Governance also holds
`spend:read`) and is removed. The signed-in person's own spend moved from the top of
Knowledge to Your account, where every role that can spend sees it. Overview keeps
its one-line spend figure, now a link to AI Gateway; a service account's own spend
stays on its row in Settings → Service accounts.

## 2026-10 — Instructions moved out of working pages into Help

- Settings → System (Helm values, upgrade commands, Airflow SMTP) is now Help → Change
  the configuration (`/help/operate`), still filled in for this deployment's profile and
  namespace. Settings keeps only settings.
- A collection's "Use from app" tab is gone. Its calls, with the collection's name
  filled in, are in the integration guide (`/help/integrate?collection=<name>`), linked
  from the collection's Members tab.
- New guide: Approved metrics (`/help/metrics`). The Help card that linked to the AI
  Gateway page (not a guide) is gone; "SQL Lab" in Help is now Analytics, the menu's
  name for it.

## 2026-10 — "API & MCP" is now the integration guide; keys are issued in Settings

The "API & MCP" menu page held the MCP endpoint, the agent-gateway OpenAPI download and
the REST endpoint list, plus a second copy of the service-account manager. The
reference moved into Help → Integrate (`/help/integrate`), which also lists the key
scopes by what the agent does; service accounts and keys are issued only in Settings
→ Service accounts (`/settings?tab=service`). The menu item is gone and `/connect`
redirects to the guide, so bookmarks still work. Nothing changed in the API.

## 2026-10 — A cap set in Settings → Budgets holds on every backend replica at once

The pre-call check below cached each caller's cap for 15 seconds per replica, and a
cap change cleared only the cache of the replica that served it. With the reference's
two backend replicas (HPA minimum 2), a caller capped at 0 was answered again by the
other one (seen live on 2026-10-16; only the gateway's own check, which is not
reliable for this, refused the probe). A cap set through DataPond is now also kept in
Postgres (`ai_budget_caps`, migration 0024) and read before every model call; only the
spend is cached. A cap of 0 refuses without asking the gateway. **Action:** caps set
before this upgrade live only in the gateway and keep the old per-replica behaviour;
set them again in Settings → Budgets (or `PUT /api/settings/ai/budgets/{user_id}`) to
have them recorded. Clearing a cap removes the row, so the gateway's cap — including a
deployment default — applies again; a replica may refuse for up to 15 seconds after a
cap is cleared, never the other way round.

## 2026-10 — Reranking works on the AWS Single-Node Reference (it never did)

`values-prod-single.yaml` registered `rerank` as `bedrock/amazon.rerank-v1:0`, a model
Bedrock does not offer in us-east-1, and as a bare ID, which LiteLLM hands to Bedrock as
an invalid ARN. Every rerank call failed and search and RAG silently kept vector order.
It is now the full ARN of Cohere Rerank 3.5,
`bedrock/arn:aws:bedrock:us-east-1::foundation-model/cohere.rerank-v3-5:0`. **Action:**
Cohere is an AWS Marketplace model, so subscribe the account to it once (Bedrock
console → Model catalog); until then reranking keeps failing the same silent way. Separately, the
backend asked the rerank model for more results than it had sent documents whenever a
search returned fewer than `k` hits, which Bedrock also refuses; it now asks for at most
as many as it sent. Expect result order to change for searches that return more than
one hit: results now carry a `rerank_score`. Each rerank is a billed Bedrock call
attributed to the caller. A deployment that set its own `rerank` model is unaffected by
the model change; if it is a Bedrock model, give it as a full ARN. To keep vector order, set `ai.rerankModel: ""`.

## 2026-10 — A spend cap is checked before the model call; a cap of 0 means no calls

The gateway judges "spend > cap" on spend it has already written, writes spend
asynchronously and caches the customer row, so a caller capped a moment ago, or capped
at 0 before its first call, could get one more answer (seen live on 2026-10-13). Every
search, rag, embed and SQL-generation call now asks the gateway for the caller's spend
and cap first (one lookup per caller per 15 seconds; forgotten at once when the cap is
changed through Settings → Budgets on the same backend replica) and answers the same
402 with a `refused` row when spend >= cap. Two consequences: a cap of 0 refuses the
very next call, and a caller is refused when it *reaches* its cap, not one call after.
A gateway that cannot be asked does not block the call; the gateway's own check still
applies to it.

## 2026-10 — The console's session is an HttpOnly cookie, not localStorage

Signing in through the console used to put the JWT in the browser's `localStorage`
(and a cookie JavaScript could read) and send it as a Bearer header itself; anything
that ran on the page could read the session. `POST /api/auth/login`, the passkey
sign-in and the SSO callback now set `datapond_token` as an HttpOnly, SameSite=Lax
cookie, the browser sends it on its own, and the API reads it when no Authorization
header is present. `POST /api/auth/logout` clears it. The login body still carries
`access_token` for scripts (`scripts/validate-deployment.sh` is unchanged), and
service-account keys and IdP tokens keep travelling in the header, unaffected.

Two things to know. The cookie is marked Secure only when the request came in over
https (directly or with `X-Forwarded-Proto: https` from the ingress), so a plain-http
development server keeps working. And a cookie-borne identity on a state-changing
request (anything but GET/HEAD/OPTIONS) is accepted only when the request's Origin or
Referer is this host; a request without either is treated as signed out. A browser
sends Origin on every such request, so people see no difference; a script that
somehow carried the cookie instead of the header would.

People signed in before the upgrade are signed in still: their old cookie has the
same name and is read the same way until it expires. The token an older build left in
`localStorage` is removed the next time they sign out or their session expires.

## 2026-10 — An over-budget `/ai/rag` call answers 402, like every other tool

A caller past its model spend cap used to get HTTP 200 from `/ai/rag` with the answer
"(Model spend budget reached for this caller) Returning search results only." and the
retrieved chunks. It now gets `402` with the gateway's spend and cap figures, the same
as `/ai/search`, `/ai/embed` and `/ai/sql`. An agent that treated a 200 as an answer
will now see the refusal; one `refused` row is written to the tool call log (no
`error` row on top of it), and that row says `ai.rag` whether the gateway refused
the question's embedding or the generation.

Two other things changed underneath. The gateway has a second wording for the same
cap ("Budget has been exceeded! EndUser=…", type `budget_exceeded`) that was not
recognised and surfaced as `502 Embedding failed`; it is now a 402 too. And deleting
a service account removes its customer row (spend and cap) from the gateway, so the
list under Settings → Budgets stops showing callers that no longer exist. The gateway
can re-create that row from the account's last calls (its spend write is
asynchronous), so the audit retention tick re-sends the delete for accounts removed
in the previous seven days; with `AUDIT_RETENTION_ENABLED=false` only the delete-time
attempt runs. Rows left behind by accounts deleted before this change stay until
removed at the gateway.

## 2026-09 — The API and MCP endpoint can accept your IdP's access tokens

Off by default; nothing changes until `auth.oauthResourceServer.enabled` is set with an
`issuer`. When on, `/api/*` and `/api/mcp` accept RS256/ES256 access tokens from that
issuer alongside session tokens and `dp_sk_` keys, so OAuth-only MCP clients can connect
and an agent behind AgentCore Gateway (outbound `TOKEN_EXCHANGE`) reaches DataPond as the
user it acts for, not as one shared key. It is in the community edition.

A token is accepted only if its audience is this deployment, its subject matches a user
that already exists, and it carries `datapond:<permission>` scopes (role ∩ scopes; none
→ `403 insufficient_scope`). Link an agent's OAuth client to a service account with
`PUT /api/service-accounts/{id}/oauth-client`; set a person's `external_id` with
`PATCH /api/auth/users/{id}` when the IdP's API subject differs from the SSO one (Entra
`oid`). Details and IdP notes: `docs/MCP.md`.

The ingress gains a `/.well-known/oauth-protected-resource` path to the backend (RFC
9728 metadata; 404 while the mode is off), and 401 responses carry a
`resource_metadata` challenge when it is on. `APP_BASE_URL` must be set for the default
audiences and the metadata URL to be right. Okta org-authorization-server tokens cannot
be validated; use a custom authorization server.

## 2026-09 — A collection can narrow retrieval to the chunks a caller may see

A collection can now carry a chunk access rule:
`PUT /api/ai/collections/{name}/chunk-access` with
`{"metadata_key": "department", "user_attribute": "department"}` (owner, editor or
admin). With a rule, search and RAG return only chunks whose `metadata[metadata_key]`
is one of the caller's `users.attributes[user_attribute]` values — the attributes the
table RLS engine already uses. `DELETE` on the same path removes the rule.

**It fails closed.** A chunk without the key is hidden, and a caller without the
attribute gets no results. Admins are held to it too, as `RLS_ADMIN_BYPASS=false` holds
them to table policies. So label the chunks and set the attributes before turning a rule
on, not after.

Labels reach chunks at ingest: an Iceberg source takes `label_column` (its value is
stored under the column's name), any source takes constant `labels`
(`{"department": "hr"}` for an S3 prefix only HR writes to), and pasted documents carry
their own `metadata`. Scheduled re-embeds keep both, because they are stored with the
schedule. Chunks ingested before this change carry no labels; re-ingest the source.

The caller is never told how many chunks were withheld. The tool call log is:
`tool_call_log.chunks_withheld` counts, per call, how many of the nearest chunks the
rule kept back. Migration 0017 adds that column and `ai_collections.chunk_access`; both
are inert until a rule is set.

**Known limit.** The filter runs inside the vector query, so a caller gets its top-k from
what it may see. With the HNSW index a very selective rule can return fewer than k
results, the same way the collection filter already can on a large, mixed table. There
is no UI for the rule yet; it is API-only.

## 2026-09 — An OpenAPI document an agent gateway accepts

`GET /api/tools/openapi.json` serves the four data tools (`search_knowledge`,
`answer_with_citations`, `generate_sql`, `run_sql`) as OpenAPI 3.0 with no
`anyOf`/`oneOf`/`allOf`, no `$ref`, and no security schemes, which is what AgentCore
Gateway requires of an OpenAPI target. It lists only the tools the requesting
credential can call, so fetch it with the agent's own key. The server URL comes from
`APP_BASE_URL`; if that is unset it falls back to the request's host, which behind a
proxy may be the wrong scheme — set `APP_BASE_URL` before registering. The API page has
a download button. Nothing changes for existing callers.

## 2026-09 — API keys have a request budget, and can be rotated

**Every service-account key is now limited to 600 requests a minute** by default, per
backend replica (a token bucket, so short bursts up to the full minute are allowed). A
call over the budget gets `429` with a `Retry-After` header before the route runs, and
the backend logs a warning naming the key id. People signed in to the UI are not
limited. Set `API_KEY_RATE_LIMIT_PER_MINUTE` on the backend to change it; `0` turns it
off. If an existing integration runs batch jobs faster than this, raise the value before
upgrading. It has no Helm value: add it through `backend.env` or your own overlay.

**Keys can be rotated**: `POST /api/service-accounts/keys/{id}/rotate` (and the rotate
button in Settings → Service accounts) issues a successor with the same name and
scopes. The old key keeps working for `grace_hours` (default 24, at most 168, `0`
revokes it at once) but never past its own expiry. The successor gets the old key's full
lifetime. Migration 0016 adds the `api_key_rotated` audit event. Other backend replicas
may accept a revoked key for up to 30 seconds (the key cache TTL), as with revocation.

## 2026-10 — SQL semantic layer (migration 0023)

Migration `0023_semantic_metrics` adds `semantic_metrics`, `semantic_metric_versions` and
`semantic_joins`. The version table is append-only by trigger, the same strength as the
audit tables: it stops the application's normal code paths, not the owning database role,
which can disable a trigger. It is not tamper-proof. The MCP surface grows from 26 to 29
read actions (`metric_list`, `metric_describe`, `metric_query`), available only where the
`query` capability is on. No setting is required; no metric exists until an administrator
approves one under Metrics in the console. Named periods (`last_month`, `this_quarter`, …)
resolve in `SEMANTIC_TIMEZONE`, default `Asia/Seoul`; set it on the backend if your
business calendar is elsewhere. The same migration widens `tool_call_log`'s
`resource_kind` constraint to allow `metric`, the kind each `metric_query` audit row carries. `/ai/sql` responses gain `metrics_provided` and
`suggested_metric`.

## 2026-09 — An MCP endpoint, read-only, on the key you already have

`POST /api/mcp` speaks MCP 2026-07-28 and exposes the read actions as tools (26 at the time; 29 since the semantic layer below),
authenticated with a service-account key. Nothing that writes is reachable. Each call
writes one `tool_call_log` row with `via='mcp'`; migration 0009 widens that table's
`tool` constraint so a row can name the action it logged. No configuration is required
to turn this on — `main.py` mounts the route unconditionally, with no capability flag —
so every existing service-account key gains this surface on upgrade, scoped to
whatever permissions it already holds. There is no setting to decline it; the read
actions and the permission gate are the only boundary.

## 2026-09 — Service-account keys carry scopes and an expiry

Keys issued from Settings → Service accounts default to `knowledge:read` + `ai:generate`
and 90 days. Keys issued before this change keep their previous (role-wide, non-expiring)
grants; revoke and reissue them to narrow. `GET /api/service-accounts/{id}/collections`
lists what an account can read. `/api/api-surface` (the API page) now includes
`POST /api/queries/execute`.

## 2026-09 — Every data-tool call leaves an audit row

Every `/api/ai/search`, `/api/ai/rag`, `/api/ai/sql` and `/api/queries/execute` call —
successful, degraded (no AI backend configured) or failed — now writes one row to
`public.tool_call_log` (who, which tool, which collection or tables, hit count, cited
sources, PII masked). The row is written after PII masking and is append-only under the
same trigger as the security audit log. `save_history=false` no longer hides a query from
the audit trail — it only controls the user-facing history. Retention: same window as
`AUDIT_RETENTION_DAYS`. New read endpoints under `/api/audit/tool-calls` (`audit:read`).
The governance compliance report gains an "Agent tool calls" section. Expect one extra
INSERT per tool call.

Masking for the log is applied unconditionally — regardless of `PII_GUARDRAIL_MODE` —
so a row never carries raw text even when the mode is `block` or `off` and the caller
itself receives the unmasked text or a rejection. `pii_ko` only covers structured Korean
identifiers (주민번호, 휴대전화, 사업자번호, 카드, 이메일 등); names and addresses are not
masked, so free-text questions to `/ai/search` and `/ai/rag` are newly persisted (up to
512 masked characters), while `/queries/execute` SQL was already stored raw in
`query_history`. `via` is `api` or `chat` — browser and agent HTTP traffic both record
`api`; only calls made through the chat executor path record `chat`.

## 2026-08 — `query:run` no longer means "may change the database"

**What changed.** Running a statement that changes data or schema now needs a new
permission, `query:write`. `query:run` narrows to statements that only read.

**Why.** Nothing in the execute path had ever looked at what the statement was, so
every role holding `query:run` could also `DROP TABLE` — `viewer` included. The only
sign it had been considered was a comment reading "Don't add LIMIT to DDL or SHOW
commands", written on the assumption that DDL flows through. It did.

**Who has it.** `admin` and `data_engineer` — the roles that already own the data
plane through connectors. Everyone else keeps `query:run` and loses nothing they were
supposed to have: `viewer`, `business_analyst`, `auditor`, `ai_engineer` and
`data_scientist` are SELECT-only.

**How statements are judged.** By parsing, not by pattern-matching the text. SELECT,
WITH, SHOW, DESCRIBE, USE and plain EXPLAIN read. Everything else writes, including
`CREATE TABLE … AS SELECT`, and including `EXPLAIN ANALYZE`, which executes what it
claims to describe.

It fails closed: anything unparseable counts as a write. The two errors are not
symmetric — refusing a legitimate SELECT is an annoyance a permission grant fixes, and
allowing a DROP is a restore. If a valid read is refused, that is a parser gap worth
reporting rather than a policy to relax.

**One layer, not two.** This is enforced in the application. It is *not* enforced in
IAM, because the same credential the application queries with is the one connector
syncs write Iceberg tables through — a read-only policy would break ingestion.
Separating those is a second credential and a separate change. Until then, anything
that reaches Trino outside this application is not covered.

**What to do.** Nothing, unless someone reports a 403. The refusal names the
permission, so they can tell you what to grant.

## 2026-08 — Migrations move out of Helm hooks

**What changed.** The migration Job was a `pre-install,pre-upgrade` hook. It is now an
ordinary manifest resource, and the backend waits for it in an init container.

**Why.** A pre-install hook cannot work on a first install. The Secret it reads its
credentials from is created in the main phase, so the Job pod sat in
`CreateContainerConfigError`; and with an in-cluster database there is no database yet,
because hooks run before the Postgres the same release creates. Moving it to
`post-install` is worse: readiness records `base_schema` once at startup, so a backend
that starts before the tables exist is not slow — it is permanently NotReady.

Both failures were found by the ephemeral install job, which exists to catch what an
upgrade of a running deployment never exercises.

**What is unchanged.** The migration still runs exactly once, in one pod, before the
backend serves anything. The application still never migrates — the init container
waits and applies nothing. `backoffLimit` is still 0: one attempt, then a human reads
the log. Waiting for the database to accept connections is separate and happens inside
the container, because a closed socket is not a failed migration.

**What to expect.** Backend pods spend a few seconds in `Init` on every rollout. The
Job is named `backend-migrate-<release revision>` — a Job's pod template is immutable,
so a fixed name would fail the second upgrade with `field is immutable`. Successful
Jobs clear themselves after an hour; a failed one is kept.

**If you install with your own command**, add `--namespace <ns> --create-namespace`.
The chart no longer renders a Namespace on the profile that uses it — see the note
below on why nothing may leave the manifest.

## 2026-08 — Infrastructure keeps an event history

**What changed.** Infrastructure has a third tab, **Events**, backed by a new
`system_events` table and an in-process collector.

Before this, the only event surface read live Kubernetes Events for pods that
currently exist. That loses everything twice: the apiserver expires Events after an
hour, and a pod that has been replaced cannot be queried at all — which makes the pod
worth asking about the one you cannot ask about. On 2026-08-27 the live node had
rebooted four hours and fifty-two minutes earlier and `kubectl get events` held
twenty-seven minutes of history.

**What it records.** Pod restarts, OOMKills, probe failures, image-pull and mount
failures, crash loops, evictions, and node reboots. Not request logs, not pod stdout,
not authentication, not queries — those have their own homes and stay there.

A condition that repeats is one row with a count and a first/last seen, not one row
per occurrence.

**One limit worth knowing.** Nothing is collected while the backend is down. A node
reboot is therefore detected after the fact, and the reboot row says the cause is not
recorded rather than inferring one. An empty window is not proof that nothing
happened, and the empty state says so.

**Who can see it.** `service:manage`, the same permission as the rest of
Infrastructure. No new permission was added. `auditor` holds `audit:read` but not
`service:manage`, so it cannot reach Infrastructure at all — unchanged by this, and a
separate decision if you want it.

**Tunable** via `backend.systemEvents`: `enabled` (default true), `tickSeconds`
(120), `retentionDays` (30). Retention has a floor of one day rather than an off
switch — unbounded growth is not acceptable on a single node.

## 2026-08 — Two role changes, and where AI Gateway lives now

**`data_scientist` gains `connector:read`.** They could query a table through Catalog
and Analytics but not see Sources, so "how old is this data?" had no answer for the
person analysing it. Read-only: nothing about it lets them run a sync or edit a
connector.

**Curating concepts is `knowledge:write`, no longer admin.** Concept expansion
rewrites a query before retrieval, which makes the term list a retrieval-quality
control — and the role accountable for retrieval quality already creates the
collections, ingests into them, and schedules their re-embedding. Being unable to
say that two words mean the same thing was the wrong line. Reading the list is
`knowledge:read`; it used to require only a login, which put it outside the
permission vocabulary entirely.

If you would rather keep vocabulary changes with administrators, no role other than
`admin`, `ai_engineer` and `data_scientist` holds `knowledge:write` — restricting it
further means moving those roles, not changing this.

**AI Gateway moved from "Build AI" to "Operate".** Nothing on that page builds
anything: it registers providers, issues keys and reports spend. The audience settled
it — every role that can see it holds `spend:read`, so `data_scientist` and
`business_analyst` could not, while `auditor`, who builds nothing, could. The URL is
unchanged.

**New: Build AI → Connect.** How to call the retrieval and cited-answer endpoints
from your own application, with copyable snippets and the scopes to ask an
administrator for. Visible to roles holding `ai:generate`.

**New: your own model spend.** `GET /api/settings/ai/usage/me` returns only the
caller's. The deployment-wide view still needs `spend:read` — which is the permission
to see *everyone's*, an operator's question — but a role trusted to spend can now see
what it spent.

## 2026-08 — Sign-in is rate limited

**What changed.** Login had no rate limit, no lockout, and no backoff. The endpoint
is on the public internet and verifies a bcrypt hash on every attempt, so it was both
a credential-guessing oracle and a way to spend a single-node deployment's CPU from
anywhere.

Failures are now counted two ways. **Per account**, five failures lock that username
for a minute, doubling with each further failure up to fifteen. **Per address**,
twenty failures in five minutes blocks that address — the per-account counter never
fires against a spray that tries one password against each of many accounts.

Both counters forget: failures older than the window no longer count, so a mistyped
password last month cannot combine with today's to lock a real user out. A successful
sign-in clears that account immediately.

**Tunable** if the defaults do not suit you — `LOGIN_MAX_FAILURES`,
`LOGIN_LOCKOUT_SECONDS`, `LOGIN_LOCKOUT_MAX_SECONDS`, `LOGIN_IP_MAX_FAILURES`,
`LOGIN_IP_WINDOW_SECONDS`.

**One thing to check if you do not use our ingress.** The per-address counter is only
correct if the deployment can see the real client address. Helm sets
`LOGIN_TRUST_PROXY` from `ingress.enabled`, which is the right answer for every
profile in this chart. If you front the backend with your own proxy and disable our
ingress, set it yourself — otherwise every request appears to come from the proxy, and
the per-address budget becomes one bucket shared by everyone, which a single attacker
can exhaust to lock out your whole organisation.

**Known limit.** The counters are per backend replica. With the one or two replicas
this product runs, that costs at most a factor of two on the thresholds. A shared
store is the fix at higher replica counts.

## 2026-08 — Every mutating route is authorized

**What changed.** The previous entry enforced roles on the routes the core UI calls.
It did not cover the rest: an inventory of the running application found **67 mutating
endpoints that required only a login**. Among them, any authenticated user could
create and delete RLS and column-masking policies — the governance system could be
switched off by the people it governs — trigger and delete Airflow DAG runs, drop
streaming sources and sinks, delete pipelines and transforms, and run notebooks.

Every one of them now carries a permission. A test walks the application's own route
graph and fails the build if a mutating endpoint has no authorization dependency, so
this cannot reopen quietly; the exceptions are thirteen routes listed by name with a
reason: four that precede identity (login, logout, and password recovery), two more for
passwordless login, five that act only on the caller's own account, and the two chat
approvals, which authorize against the specific invocation rather than the role.

**Who is affected.** Anyone who was using these endpoints with a role that does not
carry the matching permission — most often `viewer`.

**Two new permissions.** Notebooks and experiment tracking had no permission that
could describe them. A notebook runs arbitrary code against the cluster, so `query:run`
does not cover it.

| Permission | Covers | Held by |
|---|---|---|
| `workbench:read` | browsing notebooks and tracked experiments | every role except `viewer` |
| `workbench:write` | running notebooks, kernels, experiment changes | `admin`, `data_engineer`, `ai_engineer`, `data_scientist` |

**One narrowing worth calling out.** `POST /api/ai/search` now requires `ai:generate`,
not `knowledge:read`. Searching a collection embeds the query, which spends model
tokens — the same reason `ai:generate` exists at all. A `viewer` and a
`business_analyst` can still read collections and open cited answers others produced,
but can no longer run a search themselves. Give them `ai_engineer` or `data_scientist`
if they should.

**What to do.** Nothing, unless someone reports a 403. The refusal names the permission
they need, so they can tell you what to grant.

## 2026-08 — Roles are enforced

**What changed.** Five roles were seeded into the database from the start, but nothing
outside the RLS engine ever read them: the application layer enforced a single
distinction, admin or not. A "viewer" could create, edit, and delete connectors and
knowledge collections, run syncs, and spend model tokens without limit. Three of the
five roles could not even be assigned — the user API allowlisted `admin` and `viewer`
and rejected the rest.

Permissions are now enforced per role. See `app/permissions.py` for the matrix and
`docs/RLS_DESIGN.md` for the separate question of which *rows* a role may read.

**Who is affected.** Every non-admin account. They are all `viewer` today, because
that was the only other assignable role.

**What a viewer keeps:** reading the catalog and knowledge collections, and running
queries. The work people do all day is unchanged.

**What a viewer loses:**

| Capability | Permission now required |
|---|---|
| Create, edit, delete connectors; run a sync | `connector:write` |
| Create, ingest into, delete knowledge collections | `knowledge:write` |
| Save or delete dashboards | `dashboard:write` |
| Ask AI, RAG answers, embedding — anything spending model tokens | `ai:generate` |

This is the removal of access that was granted by accident, not a new restriction. But
it is a behaviour change, and someone relying on it will notice.

**What to do.** Decide which of your users are actually operators and give them a role
that says so:

| Role | For |
|---|---|
| `data_engineer` | brings data in — sources, catalog, transforms |
| `ai_engineer` | builds on it — knowledge collections, RAG, model usage |
| `data_scientist` | queries, collections, dashboards |
| `business_analyst` | queries and dashboards |
| `auditor` | reads governance, the audit log, and spend; writes nothing |
| `viewer` | reads and queries |

Settings → Users, or `PATCH /api/users/{id}` with `{"role": "..."}`. All six are
assignable now.

**If you would rather not decide yet:** promoting existing accounts to `data_engineer`
restores everything they could do before except `ai:generate`. That one is deliberately
separate — per-user model spend is a governance claim this product makes, and an
unbounded ability to spend for anyone who can log in contradicts it.

**Menus follow permissions.** A page appears when the deployment has the feature *and*
the role may use it, so people will see fewer items. The API enforces the same rule;
the menu is not the control.

## 2026-08 — `ADMIN_PASSWORD` is bootstrap-only

Not a change, but a recurring surprise worth stating. The `ADMIN_PASSWORD` value in
`datapond-secrets` seeds the admin hash **once**, on first run. After anyone changes
the admin password — Settings → Reset Password, or the change-password flow — the
database holds a different hash and the secret no longer opens the account. That is
deliberate: the bootstrap must never silently revert an operator's password change.

If the documented `kubectl get secret … ADMIN_PASSWORD` value returns a 401, that is
the expected result of a password change, not a broken secret. Recover through the
password-reset flow.

### Catalog: concept page, ontology map, and what uses a table (2026-11-25, no migration)

Data Map step 4. Nothing to run on upgrade.

- **Concept page** at `/metrics/concepts/<name>`. It shows what the concept is, the concepts related to it (one table holds keys of both), its narrower concepts and columns, where those rows come from (the flow map), the metrics built on its tables, and what needs attention (personal data with no column mask, bindings waiting for approval). It also has *Show on map* (Catalog data map, Concepts mode) and *Ask in Analytics* (a first count query). Concept names in Catalog search, the data map and Semantic model → Concepts link to it.
- **Ontology map**: Semantic model → Concepts has a Matrix / Map switch. Concepts are nodes. A solid line means one table holds keys of both concepts, and is labelled with that table. A dashed arrow points to a narrower concept, and segments are small pills beside their parent. Every line comes from approved bindings or a concept's parent; none is drawn by hand.
- **What uses this table**: the data map's Lineage mode now also lists metrics on the table, concept bindings on its columns, saved dashboards whose query reads it, and how often it was queried in the last 30 days, from `GET /api/catalog/impact?table=catalog.ns.table` (`catalog:read`, up to 12 tables). It never reads the table's rows. Table names in the tool-call log are matched across catalog aliases (`AwsDataCatalog` and `iceberg`). Only readers with `governance:read` see who queried; everyone else sees counts only. Dashboards follow the dashboard list's rule: admins see all, others see their own and public ones.
- `/catalog?table=…&map=lineage|schema|concepts|relationships` opens the data map in that mode.

### Source schedules run in the backend, without Airflow (2026-11-25, migration 0037)

A source's sync schedule used to be written out as an Airflow DAG. The AWS reference and the Core profiles run no Airflow, so the console hid the schedule card there and every sync was manual. Schedules now run in the backend (`app/sync_scheduler.py`) on every profile: one loop per replica, leader-locked through Postgres like the RAG and connection-check loops.

- `0037_source_schedule_runs` adds three nullable columns to `connector_connections`: `schedule_set_by`, `schedule_anchor_at`, `schedule_last_status`. Expand only. Schedules that already exist start counting from the upgrade, so nothing they "missed" runs at once.
- A run is made as whoever saved the schedule (the owner for an older schedule), re-checked on every run: active, holding `connector:write`, and still allowed to change the source. Otherwise the run is skipped, the reason is shown on the source, and a denial goes to the security audit log. Paused sources never run.
- A fire time missed while the node was stopped runs once when it starts, not once per missed time.
- Cron hours are read in `backend.syncScheduler.timezone` (default `UTC`; `values-prod-single.yaml` sets `Asia/Seoul`). The schedule route returns the zone, the next run and the last run. Turn the loop off with `backend.syncScheduler.enabled: false`; the capability `scheduled_sync` follows it.
- Saving a schedule no longer writes a DAG, and removes one left from before. On a profile that runs Airflow, the same sync no longer runs twice.
- Bad cron expressions are refused with 400 when saved, instead of becoming a broken DAG.

### Concepts: the old text parent column is dropped (2026-11-25, migration 0036)

`0036_drop_concept_parent_text` is the contract step of 0033: `ontology_concepts.parent` (the parent's name as text) is dropped. Parents have been read and written through `parent_id` since 0033, so no running release reads the column. On the live reference, all 11 concepts with a parent had matching values in both columns before the drop. The downgrade restores the column and fills it from `parent_id`.

### MCP: catalog.find_tables also finds columns and business words (2026-11-25, no migration)

`catalog.find_tables` still returns `tables`, the tables whose name or namespace matches, unchanged. It now also returns:

- `matches`: tables found by column name or business word, each with why (`concept 고객`, `segment 취소 주문`, `2 columns`);
- `concepts`: the concepts the words name, with their key columns;
- `metrics`: metrics whose name, label or synonym matches.

It uses the same search as `GET /api/catalog/search` (`catalog_search.search_for`), limited to the catalogs the caller may use. If that lookup fails, the extra keys are left out and the tool still answers.
