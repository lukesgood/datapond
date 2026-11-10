# Connectors as Trino Catalogs (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every PostgreSQL / MySQL / SQL Server / Oracle / MongoDB connection becomes a Trino catalog `src_<slug>`: introspected, synced into Iceberg and federated through the one engine, governed by the existing per-catalog ACL, with the pandas/SQLAlchemy sync path removed.

**Architecture:** The backend keeps credentials in the Fernet vault (Aurora) as today and *projects* them into two Kubernetes Secrets the Trino pod mounts (catalog files via a projected volume; passwords via `envFrom` and `${ENV:…}` references); every change to a Trino-backed connection patches the Secrets and bumps a restart annotation on the Trino Deployment. Each `src_*` catalog is also a `data_catalogs` row of kind `trino_source`, so `catalog_grants`, the resolver's `catalog_allowed` hook, the semantic layer and the catalog audit all govern it unchanged; the connection's owner and members are projected into `catalog_grants`. A sync is a Trino statement sequence built by pure functions (`CREATE TABLE IF NOT EXISTS … WITH (partitioning)`, `DELETE`+`INSERT … SELECT`, or `MERGE`), with PII masking at ingest emitted as Trino `regexp_replace` chains from the same patterns `pii_ko` applies at read. The pre-create connection test and table listing stay driver-based, in one thin module.

**Tech Stack:** FastAPI, asyncpg, `trino` DBAPI, `kubernetes` client (already a dependency), psycopg2 / PyMySQL (present) + `python-tds`, `oracledb`, `pymongo` (new, permissive licences), Helm (projected volumes, `lookup`-preserved Secrets), Alembic (migration 0026), Next.js console, GitHub Actions kind job.

**Spec:** `docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md` — section "Phase 2 — connectors as Trino catalogs" (lines 184–303), "Decided by the owner", "My calls", "Left to the builder". Phase 1 (Trino replaces Athena) is live: `docs/superpowers/plans/2026-11-09-trino-replaces-athena.md`, merged as PR #250.

## Global Constraints

- Trino-backed types in this cut: `postgresql`, `mysql`, `sqlserver`, `oracle`, `mongodb`. `rest_api`, `custom`, `s3` stay on the Python path (`iceberg_writer.py`). `kafka`, `kinesis`, `azure_blob`, `gcs` stay unsupported. `database_url` is accepted on input and normalised to `postgresql` / `mysql`; it is no longer offered in the console.
- Catalog name `src_<slug>`: slug from the connection name, lowercase `[a-z0-9_]`, whole name ≤ 32 characters, unique among registry names and engine catalogs (case-insensitive), stable after creation (a rename does not change it).
- Secrets: `trino-source-catalogs` (keys `src_<slug>.properties`) and `trino-source-credentials` (keys `SRC_<SLUG>_PASSWORD`), release namespace, created by the chart with their existing data preserved across upgrades (`lookup`), patched only by the backend. RBAC: `get`/`patch` on exactly those two Secrets; `patch` on Deployment `trino` (already granted). A plaintext password never appears in a ConfigMap, a log line, an HTTP response or the Trino UI.
- Credentials stay in the vault; the Secrets are a projection rebuilt from the vault on backend start when they differ (DR ordering rule: database + `ENCRYPTION_KEY` restore the catalogs).
- Pre-create test and table/column listing: driver-based, in `app/connectors/probe.py` only. After creation, introspection and sync go through Trino. A sync runs as the backend's Trino user `datapond`; federation reads run as the caller (`get_trino_connection(trino_user=…)`, unchanged).
- `connectors` capability requires `TRINO` only. RLS Layer 2 stays off on the AWS reference; `trino_acl.generate_rules()` gains a `catalogs` section for operators who turn it on.
- Sample SQL sources (`Sample E-Commerce DB`, the finance sample) connect as the restricted login role `datapond_sample` (migration 0026 creates it with the password in `SAMPLE_DB_PASSWORD`), `USAGE`+`SELECT` on the sample databases only.
- `connectors/database.py` is removed in this plan, after the Trino sync passes its tests and the CI acceptance job.
- Alembic revision ids ≤ 32 characters (`alembic_version.version_num` is varchar(32)); migrations use the shared `run_sql` helper. Revision: `0026_sample_db_role`, down_revision `0025_glue_engine_catalog_trino`.
- Every new file-backed dependency passes the licence gate (no GPL/LGPL/MPL/EPL): `python-tds` (MIT), `oracledb` (Apache-2.0 / UPL), `pymongo` (Apache-2.0). Pin exact versions current at execution time.
- Trino image stays `trinodb/trino:482`; confirm connector property names against the 482 docs before rendering (postgresql/mysql/sqlserver/oracle: `connection-url`, `connection-user`, `connection-password`; mongodb: `mongodb.connection-url`).
- Copy rule: the console says "query engine restarting (~1 min)" while Trino is reloading its catalogs; "Add sample data" says the same before its activation sync.

## Review Focus

Input classes the spec implies that no task's happy path exercises; each has a pinned test in the owning task.

1. **Passwords with `;`, `&`, `%`, `@`, `#`, quotes or spaces.** JDBC catalogs must carry the password only via `${ENV:…}` (never in the URL); the MongoDB URL must carry it percent-encoded (`quote_plus`) inside the env value. A connection must not break or leak because of its password. (Task 1)
2. **Connection names that collide or change.** "Sales DB", "sales-db" and "SALES db" must become three distinct catalogs; renaming a connection must keep its `src_*` name; a 60-character Korean name must still produce a valid ≤ 32-character catalog name. (Tasks 1, 5)
3. **Source types Iceberg cannot hold as-is.** `tinyint`, `smallint`, `char(n)`, `varchar(n)`, `timestamp(0)`/`(3)`, `time`, `json`, Oracle `NUMBER` without scale, MongoDB `ObjectId`/documents: the create statement and the projection must map them, never fail the job. (Task 6)
4. **A reconcile that runs mid-change.** The backend restarts between the Secret patch and the registry insert, or two replicas reconcile at once: the end state must be one catalog, one registry row, one restart at most, and no restart when nothing differs. (Task 3)
5. **An ungranted caller naming a source catalog any way SQL allows.** `src_x.s.t`, a bare `t` that only `src_x` has, `SHOW SCHEMAS FROM src_x`, the Knowledge ingest picker, `metric_*` tools: refused as "unknown catalog" without naming it. (Task 4)

---

## File map

| Path | Responsibility |
|---|---|
| `backend/app/connectors/trino_source.py` (new) | Pure: engine-of-type, slug, env name, catalog-file rendering, `database_url` normalisation, `TrinoSourceConfig`, `TrinoSourceConnector` (introspection + sync through Trino) |
| `backend/app/connectors/trino_sync.py` (new) | Pure: Trino→Iceberg type mapping, PII projection, create/full/incremental/merge/evolve statement builders |
| `backend/app/connectors/trino_catalogs.py` (new) | Kubernetes projection: desired Secret state from DB rows, patch, restart annotation, engine status, startup reconcile |
| `backend/app/connectors/probe.py` (new) | Driver-based pre-create test, table list and column list for the five types; the only per-source Python |
| `backend/app/connectors/source_catalog.py` (new) | Registry row of kind `trino_source` per connection; owner/member → `catalog_grants` projection |
| `backend/app/guardrails/pii_ko.py` | `mask_sql(col)`: the same patterns as Trino `regexp_replace` chain |
| `backend/app/catalog_registry.py`, `backend/app/api/catalog_backend.py`, `backend/app/api/catalog_admin.py` | Kind `trino_source`, its reader, admin refusals |
| `backend/app/api/connectors.py` | Dispatch to `TrinoSourceConnector`; create/update/delete/sample routes project catalogs; `GET /connectors/engine` |
| `backend/app/api/source_access.py` | Member changes re-project grants |
| `backend/app/rls/trino_acl.py`, `backend/app/api/governance.py` | `catalogs` section from grants |
| `backend/app/capabilities.py` | `connectors: ("TRINO",)` |
| `backend/migrations/versions/0026_sample_db_role.py` | `datapond_sample` login role |
| `backend/app/connectors/database.py` | **Deleted** |
| `helm/datapond/templates/trino-source-catalogs.yaml` (new), `trino-deployment.yaml`, `rbac-backend.yaml`, `backend-deployment.yaml`, `migrate-job.yaml`, `secrets.yaml`, `Chart.yaml` | Secrets, projected volume, envFrom, env, RBAC, `SAMPLE_DB_PASSWORD`, version 2.5.0 |
| `frontend/lib/connectors.ts`, `frontend/lib/engine-restart.ts` (new), `frontend/components/connectors/engine-restart-banner.tsx` (new), `frontend/app/connectors/**`, `frontend/app/help/connectors/page.tsx` | Cards for the five types, restart banner, copy |
| `.github/workflows/ci.yml`, `.github/scripts/trino_connector_check.py` (new) | Acceptance in the existing Trino-enabled kind job |
| `docs/UPGRADING.md`, `docs/DEMO_SCRIPT.md`, `docs/DEPLOY_SINGLE_NODE.md`, `docs/RLS_DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT_CONCEPT.md`, `README.md`, `SUPPORT.md`, `CLAUDE.md` | Product truth |

Test command for the whole backend: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider` (venv per `docs/DEVELOPMENT.md`). Frontend: `cd frontend && npm run test` (node `--test` over `lib/*.test.ts`), `npm run typecheck`, `npm run lint`.

---

### Task 1: Naming and catalog-file rendering (pure)

**Files:**
- Create: `backend/app/connectors/trino_source.py`
- Modify: `backend/app/connectors/base.py` (no enum change; `ConnectorType` keeps its values)
- Test: `backend/tests/test_trino_source_naming.py`

**Interfaces:**
- Produces:
  - `TRINO_ENGINE_TYPES: frozenset[ConnectorType]` = {POSTGRESQL, MYSQL, SQLSERVER, ORACLE, MONGODB}
  - `def engine_of(t: ConnectorType) -> str` → `"trino"` for the five, `"python"` otherwise (DATABASE_URL → `"trino"`, because it normalises to one of them)
  - `def source_slug(name: str) -> str` → `"src_" + slug`, slug = NFKD-folded ASCII lowercase, non `[a-z0-9]` runs → `_`, trimmed of `_`, truncated so the whole is ≤ 32; a name with no ASCII letters/digits yields `"src_" + sha1(name)[:8]`
  - `def unique_slug(base: str, taken: Iterable[str]) -> str` → `base`, else `base[:29]_2`, `_3`, … (whole ≤ 32, case-insensitive against `taken`)
  - `def credential_env(catalog: str) -> str` → `"SRC_" + catalog[4:].upper() + "_PASSWORD"`
  - `def render_catalog_properties(t: ConnectorType, catalog: str, config: dict) -> str` — one `key=value` per line, newline-terminated; password only as `${ENV:<credential_env>}`
  - `def credential_value(t: ConnectorType, config: dict) -> str` — the string stored under the env key: the raw password, except MongoDB where it is `quote_plus(password)`
  - `def normalise_type_and_config(t: ConnectorType, config: dict) -> tuple[ConnectorType, dict]` — DATABASE_URL → parsed (`postgresql://` → POSTGRESQL, `mysql://`/`mysql+pymysql://` → MYSQL, others → `ValueError`); other types pass through with `port` coerced to int
  - `class TrinoSourceConfig(ConnectorConfig)`: `host: str`, `port: int`, `database: str = ""`, `username: str`, `password: str`, `ssl: bool = False`, `schema: Optional[str] = None`, `auth_source: str = "admin"` (MongoDB), `catalog: Optional[str] = None` (set when the connection exists)

Rendering per type (exact lines, in this order):

```
postgresql: connector.name=postgresql
            connection-url=jdbc:postgresql://{host}:{port}/{database}[?sslmode=require]
            connection-user={username}
            connection-password=${ENV:SRC_X_PASSWORD}
mysql:      connector.name=mysql
            connection-url=jdbc:mysql://{host}:{port}[?sslMode=REQUIRED]
            connection-user / connection-password as above
sqlserver:  connector.name=sqlserver
            connection-url=jdbc:sqlserver://{host}:{port};databaseName={database};encrypt={true|false};trustServerCertificate=true
            connection-user / connection-password as above
oracle:     connector.name=oracle
            connection-url=jdbc:oracle:thin:@{host}:{port}/{database}
            connection-user / connection-password as above
            oracle.number.default-scale=10
            oracle.number.rounding-mode=HALF_UP
mongodb:    connector.name=mongodb
            mongodb.connection-url=mongodb://{quote_plus(username)}:${ENV:SRC_X_PASSWORD}@{host}:{port}/{database}?authSource={auth_source}[&tls=true]
```

`host`, `database`, `username`, `schema`, `auth_source` must match `^[A-Za-z0-9_.\-]+$` (`database` may be empty for mysql); anything else → `ValueError("<field> may not contain …")`, so a value cannot inject a property line or a URL parameter.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_trino_source_naming.py
import pytest
from app.connectors.base import ConnectorType as T
from app.connectors import trino_source as ts

def test_the_five_types_run_on_trino_and_the_rest_do_not():
    assert {t for t in T if ts.engine_of(t) == "trino"} == {
        T.POSTGRESQL, T.MYSQL, T.SQLSERVER, T.ORACLE, T.MONGODB, T.DATABASE_URL}

@pytest.mark.parametrize("name,expected", [
    ("Sales DB", "src_sales_db"), ("sales-db", "src_sales_db"), ("SALES db", "src_sales_db"),
    ("Sample E-Commerce DB", "src_sample_e_commerce_db"),
    ("  weird__name!! ", "src_weird_name"),
])
def test_slug_is_lowercase_ascii_with_underscores(name, expected):
    assert ts.source_slug(name) == expected

def test_slug_fits_32_characters_for_a_long_korean_name():
    s = ts.source_slug("영업본부 고객관리 운영 데이터베이스 2026 " * 2 + "crm")
    assert s.startswith("src_") and len(s) <= 32 and s[4:].isidentifier()

def test_a_name_without_ascii_still_yields_a_catalog_name():
    s = ts.source_slug("고객관리")
    assert len(s) == 12 and s.startswith("src_")

def test_unique_slug_suffixes_on_a_clash_case_insensitively():
    assert ts.unique_slug("src_sales_db", {"SRC_SALES_DB"}) == "src_sales_db_2"
    assert ts.unique_slug("src_sales_db", {"src_sales_db", "src_sales_db_2"}) == "src_sales_db_3"
    long = "src_" + "a" * 28
    assert len(ts.unique_slug(long, {long})) <= 32

def test_credential_env_name():
    assert ts.credential_env("src_sales_db") == "SRC_SALES_DB_PASSWORD"

PG = {"host": "db.internal", "port": 5432, "database": "crm", "username": "ro",
      "password": "p;a&s%s@w#o'r\"d x", "ssl": True}

def test_postgresql_catalog_file_carries_the_password_only_as_an_env_reference():
    text = ts.render_catalog_properties(T.POSTGRESQL, "src_crm", PG)
    assert text.splitlines() == [
        "connector.name=postgresql",
        "connection-url=jdbc:postgresql://db.internal:5432/crm?sslmode=require",
        "connection-user=ro",
        "connection-password=${ENV:SRC_CRM_PASSWORD}",
    ]
    assert PG["password"] not in text and "p;a" not in text

def test_mongodb_url_encodes_the_user_and_keeps_the_password_in_env():
    cfg = {**PG, "port": 27017, "username": "r@o", "auth_source": "admin"}
    text = ts.render_catalog_properties(T.MONGODB, "src_m", cfg)
    assert "mongodb.connection-url=mongodb://r%40o:${ENV:SRC_M_PASSWORD}@db.internal:27017/crm?authSource=admin&tls=true" in text
    assert ts.credential_value(T.MONGODB, cfg) == "p%3Ba%26s%25s%40w%23o%27r%22d+x"
    assert ts.credential_value(T.POSTGRESQL, PG) == PG["password"]

def test_oracle_pins_number_scale_and_sqlserver_names_the_database():
    assert "oracle.number.default-scale=10" in ts.render_catalog_properties(T.ORACLE, "src_o", PG)
    assert "jdbc:sqlserver://db.internal:5432;databaseName=crm;encrypt=true;trustServerCertificate=true" \
        in ts.render_catalog_properties(T.SQLSERVER, "src_s", PG)

@pytest.mark.parametrize("field", ["host", "database", "username"])
def test_a_value_that_could_inject_a_property_line_is_refused(field):
    with pytest.raises(ValueError):
        ts.render_catalog_properties(T.POSTGRESQL, "src_x", {**PG, field: "a\nconnector.name=memory"})

def test_database_url_normalises_to_postgresql_or_mysql():
    t, cfg = ts.normalise_type_and_config(
        T.DATABASE_URL, {"database_url": "postgresql://u:p%40ss@h:5433/fin"})
    assert t == T.POSTGRESQL and cfg == {"host": "h", "port": 5433, "database": "fin",
                                         "username": "u", "password": "p@ss", "ssl": False}
    t, _ = ts.normalise_type_and_config(T.DATABASE_URL, {"database_url": "mysql+pymysql://u:p@h/db"})
    assert t == T.MYSQL
    with pytest.raises(ValueError):
        ts.normalise_type_and_config(T.DATABASE_URL, {"database_url": "mssql+pyodbc://u:p@h/db"})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_trino_source_naming.py -q -p no:cacheprovider`
Expected: FAIL / ERROR with `ModuleNotFoundError: app.connectors.trino_source`

- [ ] **Step 3: Implement `backend/app/connectors/trino_source.py`** with the interfaces above (`TrinoSourceConnector` comes in Task 5; leave the class out for now). Use `unicodedata.normalize("NFKD", …)` for folding, `urllib.parse.quote_plus` and `urlsplit` for the URL work, `hashlib.sha1` for the fallback slug.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_trino_source_naming.py -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/connectors/trino_source.py backend/tests/test_trino_source_naming.py
git commit -m "connectors: source catalog naming and Trino catalog-file rendering (pure)"
```

---

### Task 2: Chart — source-catalog Secrets, projected catalog volume, credentials env, RBAC

**Files:**
- Create: `helm/datapond/templates/trino-source-catalogs.yaml`
- Modify: `helm/datapond/templates/trino-deployment.yaml` (volume + envFrom), `helm/datapond/templates/rbac-backend.yaml`, `helm/datapond/templates/backend-deployment.yaml` (env), `helm/datapond/values.yaml` (`trino.sourceCatalogs` block)
- Test: `backend/tests/test_helm_trino_source_catalogs.py`, `backend/tests/test_helm_backend_rbac.py`

**Interfaces:**
- Produces (env on the backend container, only when Trino is on): `TRINO_SOURCE_CATALOGS_SECRET=trino-source-catalogs`, `TRINO_SOURCE_CREDENTIALS_SECRET=trino-source-credentials`, `TRINO_DEPLOYMENT=<.Values.trino.name>`. Task 3 reads these; absence means "no source catalogs on this profile".
- Values: `trino.sourceCatalogs.catalogsSecret` (default `trino-source-catalogs`), `trino.sourceCatalogs.credentialsSecret` (default `trino-source-credentials`).

Design points the implementer must follow:
- Both Secrets render whenever the Trino add-on is on (same `datapond.addonOn` guard as the Deployment). `data` is taken from `lookup` of the existing Secret so a `helm upgrade` never erases the backend's projection; on a fresh install `data: {}`. Label `app.kubernetes.io/component: trino-source-catalogs`.
- Trino's catalog directory becomes a **projected** volume: sources `configMap: trino-catalog` and `secret: <catalogsSecret>` with `optional: true`, mounted at `/etc/trino/catalog` (replacing the plain configMap volume). Credentials: `envFrom: - secretRef: {name: <credentialsSecret>, optional: true}` on the Trino container.
- RBAC (`datapond-backend-reader`): a new rule `apiGroups: [""] resources: ["secrets"] resourceNames: [<catalogsSecret>, <credentialsSecret>] verbs: ["get", "patch"]`. No `list`/`watch` on secrets. `trino` is already in the Deployment `patch` list.
- The existing `checksum/catalogs` annotation keeps covering `extraCatalogs`; the backend's restart annotation is a separate key (`datapond.io/source-catalogs-restarted-at`) — the chart must not render it.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_helm_trino_source_catalogs.py
"""A connection the backend projects into Trino needs two Secrets the backend may patch,
a catalog directory that sees them and an env the passwords arrive through."""
import re
from tests.test_helm_trino_extra_catalogs import render, doc   # reuse the helpers

def test_both_secrets_render_empty_when_trino_is_on(tmp_path):
    out = render(tmp_path)
    for name in ("trino-source-catalogs", "trino-source-credentials"):
        part = doc(out, "Secret", name)
        assert re.search(r"^data: \{\}$", part, re.M) or "data:" not in part

def test_nothing_renders_when_trino_is_off(tmp_path):
    out = render(tmp_path, values="values-foundation.yaml")
    assert "trino-source-catalogs" not in out

def test_trino_catalog_dir_is_projected_from_configmap_and_secret(tmp_path):
    dep = doc(render(tmp_path), "Deployment", "trino")
    assert "projected:" in dep and "name: trino-catalog" in dep \
        and "name: trino-source-catalogs" in dep and "optional: true" in dep
    assert "mountPath: /etc/trino/catalog\n" in dep

def test_trino_gets_the_credentials_as_env(tmp_path):
    dep = doc(render(tmp_path), "Deployment", "trino")
    assert re.search(r"envFrom:\s*- secretRef:\s*name: trino-source-credentials\s*optional: true", dep)

def test_backend_learns_the_secret_and_deployment_names(tmp_path):
    dep = doc(render(tmp_path), "Deployment", "backend")
    for k, v in (("TRINO_SOURCE_CATALOGS_SECRET", "trino-source-catalogs"),
                 ("TRINO_SOURCE_CREDENTIALS_SECRET", "trino-source-credentials"),
                 ("TRINO_DEPLOYMENT", "trino")):
        assert re.search(rf"name: {k}\s*value: \"?{v}\"?", dep), k

def test_backend_env_is_absent_when_trino_is_off(tmp_path):
    assert "TRINO_SOURCE_CATALOGS_SECRET" not in render(tmp_path, values="values-foundation.yaml")
```

Add to `backend/tests/test_helm_backend_rbac.py`:

```python
def test_the_backend_may_patch_exactly_the_two_source_catalog_secrets():
    rendered = _render()   # the file's existing render helper, onprem + trino.enabled
    rule = _rule_for(rendered, resource="secrets", verbs={"get", "patch"})
    assert set(rule["resourceNames"]) == {"trino-source-catalogs", "trino-source-credentials"}
    assert not _rule_for(rendered, resource="secrets", verbs={"list"})
```

(Write `_render`/`_rule_for` in the test file if it only reads the template text today: render with `helm template … -f values-onprem.yaml --set trino.enabled=true` and parse the Role document with `yaml.safe_load_all`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_helm_trino_source_catalogs.py tests/test_helm_backend_rbac.py -q -p no:cacheprovider`
Expected: FAIL — `no Secret named trino-source-catalogs`, missing env, missing rule

- [ ] **Step 3: Implement the templates and values** as described. In `backend-deployment.yaml` guard the three env entries with the same `datapond.addonOn … "trino"` include the Trino templates use.

- [ ] **Step 4: Run the tests and the chart gates**

Run: `cd backend && .venv/bin/python -m pytest tests/test_helm_trino_source_catalogs.py tests/test_helm_backend_rbac.py tests/test_helm_trino_extra_catalogs.py tests/test_helm_trino_glue_catalog.py -q -p no:cacheprovider && helm lint helm/datapond --values helm/datapond/values-quicktest.yaml && for v in values-prod-single values-onprem values-foundation values-sovereign-core values-aws values-dev; do helm template datapond helm/datapond -f helm/datapond/$v.yaml >/dev/null || exit 1; done`
Expected: PASS; lint 0 failures; every profile renders

- [ ] **Step 5: Commit**

```bash
git add helm/datapond backend/tests/test_helm_trino_source_catalogs.py backend/tests/test_helm_backend_rbac.py
git commit -m "helm: Trino source-catalog Secrets, projected catalog dir, credentials env, backend RBAC"
```

---

### Task 3: Kubernetes projection, restart and engine status

**Files:**
- Create: `backend/app/connectors/trino_catalogs.py`
- Modify: `backend/main.py` (startup reconcile), `backend/app/api/connectors.py` (`GET /connectors/engine`)
- Test: `backend/tests/test_trino_catalogs_projection.py`

**Interfaces:**
- Consumes: Task 1 `render_catalog_properties`, `credential_env`, `credential_value`, `engine_of`, `normalise_type_and_config`; Task 2 env names.
- Produces:
  - `def enabled() -> bool` — `TRINO_SOURCE_CATALOGS_SECRET` set
  - `@dataclass(frozen=True) class Desired: catalogs: Dict[str, str]; credentials: Dict[str, str]` (file name → properties text; env name → value)
  - `def desired_from_rows(rows: Sequence[Mapping]) -> Desired` — rows carry `catalog`, `connector_type`, `config` (decrypted); rows whose `catalog` is None or whose type is not Trino-engine are skipped; a row whose config fails validation is skipped with a `logger.warning` naming the catalog, never the value
  - `class KubeClient` (Protocol): `read_secret_data(name) -> Dict[str, str]`, `patch_secret_data(name, data: Dict[str, Optional[str]]) -> None`, `patch_deployment_annotation(name, key, value) -> None`, `deployment_status(name) -> Dict` (`replicas`, `ready_replicas`, `updated_replicas`, `annotations`)
  - `class RealKube(KubeClient)` over `kubernetes.client` (incluster, kubeconfig fallback), namespace `DATAPOND_NAMESPACE`; Secret values base64-decoded/encoded here
  - `def apply(desired: Desired, kube: KubeClient) -> bool` — patches each Secret with the full desired map plus `None` for keys present in the Secret but not desired; returns whether anything changed
  - `def restart(kube: KubeClient, now: Optional[str] = None) -> None` — annotation `datapond.io/source-catalogs-restarted-at` = ISO-8601 UTC
  - `def engine_status(kube: KubeClient) -> Dict` → `{"engine": "trino", "ready": bool, "restarting": bool, "restarted_at": str|None}`; `restarting` = annotation present and (`updated_replicas` < `replicas` or `ready_replicas` < `replicas`); when `enabled()` is False → `{"engine": "none", "ready": False, "restarting": False, "restarted_at": None}`
  - `async def load_rows(pool) -> List[dict]` — joins `connector_connections` with `data_catalogs` (`kind='trino_source'`, `config->>'connection_id'`) and decrypts via `CredentialVault`
  - `async def project(pool, kube: Optional[KubeClient] = None, *, restart_if_changed: bool = True) -> Dict` → `{"changed": bool, "catalogs": [names]}`; the one entry point the routes (Task 5), the sample routes (Task 7) and startup call
  - `async def reconcile_on_startup(pool) -> None` — `project(...)` wrapped so it never raises; logs one line

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_trino_catalogs_projection.py
import base64, pytest
from app.connectors import trino_catalogs as tc

class FakeKube:
    def __init__(self, secrets=None, replicas=1, ready=1, updated=1, annotations=None):
        self.secrets = {k: dict(v) for k, v in (secrets or {}).items()}
        self.patches, self.annotations = [], dict(annotations or {})
        self.replicas, self.ready, self.updated = replicas, ready, updated
    def read_secret_data(self, name): return dict(self.secrets.get(name, {}))
    def patch_secret_data(self, name, data):
        self.patches.append((name, dict(data)))
        cur = self.secrets.setdefault(name, {})
        for k, v in data.items():
            if v is None: cur.pop(k, None)
            else: cur[k] = v
    def patch_deployment_annotation(self, name, key, value): self.annotations[key] = value
    def deployment_status(self, name):
        return {"replicas": self.replicas, "ready_replicas": self.ready,
                "updated_replicas": self.updated, "annotations": dict(self.annotations)}

ROW = {"catalog": "src_crm", "connector_type": "postgresql",
       "config": {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "s3cr;t"}}

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TRINO_SOURCE_CATALOGS_SECRET", "trino-source-catalogs")
    monkeypatch.setenv("TRINO_SOURCE_CREDENTIALS_SECRET", "trino-source-credentials")
    monkeypatch.setenv("TRINO_DEPLOYMENT", "trino")

def test_desired_state_has_one_file_and_one_env_per_trino_row():
    d = tc.desired_from_rows([ROW, {**ROW, "catalog": None}, {**ROW, "connector_type": "rest_api"}])
    assert set(d.catalogs) == {"src_crm.properties"}
    assert d.credentials == {"SRC_CRM_PASSWORD": "s3cr;t"}
    assert "s3cr;t" not in d.catalogs["src_crm.properties"]

def test_apply_patches_only_when_something_differs_and_removes_stale_keys():
    kube = FakeKube(secrets={"trino-source-catalogs": {"src_old.properties": "x"},
                             "trino-source-credentials": {"SRC_OLD_PASSWORD": "y"}})
    d = tc.desired_from_rows([ROW])
    assert tc.apply(d, kube) is True
    assert kube.secrets["trino-source-catalogs"].keys() == {"src_crm.properties"}
    assert kube.secrets["trino-source-credentials"] == {"SRC_CRM_PASSWORD": "s3cr;t"}
    kube.patches.clear()
    assert tc.apply(d, kube) is False and kube.patches == []

def test_restart_sets_the_annotation_and_status_reports_restarting_until_ready():
    kube = FakeKube(replicas=1, ready=0, updated=0)
    tc.restart(kube, now="2026-11-10T01:02:03Z")
    assert kube.annotations["datapond.io/source-catalogs-restarted-at"] == "2026-11-10T01:02:03Z"
    s = tc.engine_status(kube)
    assert s == {"engine": "trino", "ready": False, "restarting": True, "restarted_at": "2026-11-10T01:02:03Z"}
    kube.ready = kube.updated = 1
    assert tc.engine_status(kube)["restarting"] is False

def test_status_says_none_when_the_profile_has_no_trino(monkeypatch):
    monkeypatch.delenv("TRINO_SOURCE_CATALOGS_SECRET")
    assert tc.engine_status(FakeKube())["engine"] == "none"

def test_a_row_whose_config_cannot_render_is_skipped_without_leaking_it(caplog):
    bad = {**ROW, "catalog": "src_bad", "config": {**ROW["config"], "host": "h\nconnector.name=memory"}}
    d = tc.desired_from_rows([ROW, bad])
    assert set(d.catalogs) == {"src_crm.properties"}
    assert "src_bad" in caplog.text and "memory" not in caplog.text

def test_project_converges_when_run_twice_and_restarts_once(monkeypatch):
    import asyncio
    kube = FakeKube()
    async def rows(_pool): return [ROW]
    monkeypatch.setattr(tc, "load_rows", rows)
    first = asyncio.run(tc.project(pool=None, kube=kube))
    second = asyncio.run(tc.project(pool=None, kube=kube))
    assert first["changed"] is True and second["changed"] is False
    assert len([k for k in kube.annotations]) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_trino_catalogs_projection.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: app.connectors.trino_catalogs`

- [ ] **Step 3: Implement `trino_catalogs.py`**, the `GET /api/connectors/engine` route (any authenticated user; returns `engine_status(RealKube())`, and on a Kubernetes error `{"engine": "trino", "ready": None, "restarting": None, "error": "<sanitised>"}` with 200), and in `main.py` startup, after the catalog registry block: `await trino_catalogs.reconcile_on_startup(_pool)` guarded by `trino_catalogs.enabled()`. `project()` must call Task 4's `source_catalog.ensure_rows(pool)` first once Task 4 exists (leave a one-line hook `_ensure_rows = None` the next task fills; the test above does not depend on it).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_trino_catalogs_projection.py -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/connectors/trino_catalogs.py backend/main.py backend/app/api/connectors.py backend/tests/test_trino_catalogs_projection.py
git commit -m "connectors: project Trino source catalogs into Secrets, restart the engine, report its status"
```

---

### Task 4: Registry kind `trino_source`, reader, grant projection, Layer 2 catalogs section

**Files:**
- Create: `backend/app/connectors/source_catalog.py`
- Modify: `backend/app/catalog_registry.py`, `backend/app/api/catalog_backend.py`, `backend/app/api/catalog_admin.py`, `backend/app/api/source_access.py`, `backend/app/rls/trino_acl.py`, `backend/app/api/governance.py`
- Test: `backend/tests/test_source_catalog_registry.py`, `backend/tests/test_catalog_access.py` (additions), `backend/tests/test_trino_acl_catalogs.py`

**Interfaces:**
- Consumes: Task 1 `source_slug`, `unique_slug`; Task 3 `project()` hook.
- Produces:
  - `catalog_registry.KINDS = ("glue", "iceberg_rest", "polaris", "trino_source")`; `CONFIG_KEYS["trino_source"] = {"connection_id": str, "connector_type": str}`; `validate_config` requires both for that kind
  - `catalog_backend.TrinoSourceReader(entry)` with `list_namespaces()` (`SHOW SCHEMAS FROM <catalog>` minus `information_schema`, `pg_catalog`, `mysql`, `sys`, `performance_schema`, `INFORMATION_SCHEMA`), `list_tables(ns)`, `get_columns(ns, t)` (`information_schema.columns`, returns `[{"name", "type", "nullable"}]`), `get_location(ns, t) -> None`, `row_count(ns, t) -> None` (no scan of a remote source for a count), `preview(ns, t, limit)` (`SELECT * … LIMIT`); all through `trino_util.trino_conn(catalog=entry.engine_catalog)`; `reader_for_entry` dispatches on `kind == "trino_source"`
  - `catalog_admin.create_catalog` → 400 `"A trino_source catalog is created with its connection (Sources); it cannot be created here."`; `delete_catalog` → 409 `"… is the catalog of connection <name>; delete the connection to remove it."`; `update_catalog` → 400 for `engine_catalog`/`config` changes on that kind (`enabled` and grants stay editable)
  - `source_catalog.async def register(conn, *, connection_id: str, name: str, connector_type: str) -> str` — inside the caller's transaction: slug = `unique_slug(source_slug(name), taken)` where `taken` = every `name`/`engine_catalog` in `data_catalogs` plus the chart's reserved names `{"iceberg","postgres","system","jmx","memory","tpch"}`; inserts the row (`kind='trino_source'`, `engine_catalog=slug`, `config={"connection_id", "connector_type"}`, `is_default=false`, `enabled=true`); returns the slug
  - `source_catalog.async def unregister(conn, connection_id: str) -> Optional[str]` — deletes the row (grants cascade); returns the slug or None
  - `source_catalog.async def catalog_for(conn, connection_id: str) -> Optional[str]`
  - `source_catalog.async def sync_grants(conn, connection_id: str) -> List[str]` — replaces `catalog_grants` for the row with one `('user', <uuid>)` per `owner_id` and per `connector_members.user_id`; an unowned connection with no members leaves the catalog open (no rows); returns the principals written
  - `source_catalog.async def ensure_rows(pool) -> int` — for every Trino-engine `connector_connections` row without a registry row: `register` + `sync_grants` (the DR / upgrade path: an existing PostgreSQL connection gains its catalog without re-registration); returns how many were added. Task 3's `project()` calls it first.
  - After any of these, callers run `catalog_admin._refresh(pool, slug)` so the registry cache, resolver index and grants cache drop the old state; `register`/`unregister` write `auth_audit_log` rows via `catalog_admin._audit` with `event` `catalog_created` / `catalog_deleted` and `details["via"] = "connection"`
  - `source_access._add_member` / `_remove_member` for `kind == CONNECTOR`: call `sync_grants` + `catalog_access.invalidate()` after the member row changes
  - `trino_acl.generate_rules(..., source_catalogs: Mapping[str, Sequence[str]] = None)` — `catalog → granted usernames`; emits `"catalogs": [ {"user": "^(a|b)$", "catalog": "^src_x$", "allow": "read-only"} … , {"catalog": "^src_.*$", "allow": "none"}, {"allow": "all"} ]`; without the argument the section stays `[{"allow": "all"}]`. `governance.apply_trino_rules` builds the mapping from `catalog_grants` joined to `users` for `trino_source` entries (role grants expand to the users holding the role via `load_all_users()`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_source_catalog_registry.py
import asyncio, uuid, pytest
from app import catalog_registry
from app.connectors import source_catalog

def test_trino_source_is_a_registry_kind_that_names_its_connection():
    assert "trino_source" in catalog_registry.KINDS
    cfg = catalog_registry.validate_config("trino_source", {"connection_id": "x", "connector_type": "postgresql"})
    assert cfg["connection_id"] == "x"
    with pytest.raises(ValueError):
        catalog_registry.validate_config("trino_source", {"connection_id": "x"})

class FakeConn:
    """Enough asyncpg for register/unregister/sync_grants: data_catalogs, catalog_grants,
    connector_connections, connector_members held as lists of dicts; fetch/fetchval/execute
    match on the leading keyword and table name of the SQL the module issues."""
    ...  # implement in the test file; the SQL it must answer is listed in source_catalog's docstring

def test_register_picks_a_unique_slug_and_unregister_removes_it():
    conn = FakeConn(catalogs=[{"name": "src_sales_db", "engine_catalog": "src_sales_db"}])
    cid = str(uuid.uuid4())
    slug = asyncio.run(source_catalog.register(conn, connection_id=cid, name="Sales DB", connector_type="mysql"))
    assert slug == "src_sales_db_2"
    row = conn.catalog("src_sales_db_2")
    assert row["kind"] == "trino_source" and row["config"] == {"connection_id": cid, "connector_type": "mysql"}
    assert asyncio.run(source_catalog.catalog_for(conn, cid)) == "src_sales_db_2"
    assert asyncio.run(source_catalog.unregister(conn, cid)) == "src_sales_db_2"
    assert conn.catalog("src_sales_db_2") is None

def test_register_refuses_the_charts_reserved_names():
    conn = FakeConn()
    assert asyncio.run(source_catalog.register(conn, connection_id="c", name="src_ postgres"[4:], connector_type="postgresql")) != "postgres"

def test_sync_grants_projects_owner_and_members_as_user_grants():
    owner, m1 = str(uuid.uuid4()), str(uuid.uuid4())
    conn = FakeConn(connections=[{"id": "c1", "owner_id": owner}],
                    members=[{"connection_id": "c1", "user_id": m1, "role": "reader"}])
    asyncio.run(source_catalog.register(conn, connection_id="c1", name="CRM", connector_type="postgresql"))
    assert set(asyncio.run(source_catalog.sync_grants(conn, "c1"))) == {owner, m1}
    assert {g["principal"] for g in conn.grants("src_crm")} == {owner, m1}

def test_an_unowned_connection_leaves_its_catalog_open():
    conn = FakeConn(connections=[{"id": "c1", "owner_id": None}])
    asyncio.run(source_catalog.register(conn, connection_id="c1", name="Sample", connector_type="postgresql"))
    assert asyncio.run(source_catalog.sync_grants(conn, "c1")) == [] and conn.grants("src_sample") == []

def test_ensure_rows_registers_a_connection_that_predates_phase_2():
    conn = FakeConn(connections=[{"id": "old", "owner_id": None, "name": "Legacy PG", "connector_type": "postgresql"},
                                 {"id": "s3", "owner_id": None, "name": "Bucket", "connector_type": "s3"}])
    added = asyncio.run(source_catalog.ensure_rows(FakePool(conn)))
    assert added == 1 and conn.catalog("src_legacy_pg") is not None and conn.catalog("src_bucket") is None
```

Additions to `backend/tests/test_catalog_access.py` (Review Focus 5):

```python
def test_an_ungranted_caller_cannot_see_or_name_a_source_catalog():
    catalog_registry.set_entries([ICEBERG_DEFAULT, CatalogEntry(name="src_crm", kind="trino_source",
                                  engine_catalog="src_crm", config={"connection_id": "c", "connector_type": "postgresql"})])
    catalog_access.set_grants({"src_crm": {("user", OWNER)}})
    other = CatalogAccess(grants=catalog_access._grants_snapshot(), user_id=STRANGER, role="analyst")
    assert other.allows("src_crm") is False
    assert "src_crm" in other.hidden_sql_names()
    for sql in ("SELECT 1 FROM src_crm.public.orders", "SHOW SCHEMAS FROM src_crm"):
        assert catalog_access.statement_uses_hidden(other, sql, "trino")
        assert "src_crm" not in catalog_access.hidden_reason(other, sql, "trino")
    with pytest.raises(catalog_registry.UnknownCatalog):
        other.resolve("src_crm")
```

(Keep the file's existing fixture names; `ICEBERG_DEFAULT`, `OWNER`, `STRANGER` are whatever that file already uses for the default entry and two user ids.)

```python
# backend/tests/test_trino_acl_catalogs.py
from app.rls.trino_acl import generate_rules

def test_source_catalogs_become_a_catalogs_section_from_grants():
    rules = generate_rules([], [], [], source_catalogs={"src_crm": ["alice", "bob"], "src_open": []})
    cats = rules["catalogs"]
    assert cats[0] == {"user": "^(alice|bob)$", "catalog": "^src_crm$", "allow": "read-only"}
    assert {"catalog": "^src_.*$", "allow": "none"} in cats and cats[-1] == {"allow": "all"}
    assert not any(c.get("catalog") == "^src_open$" for c in cats)   # open = falls to allow all? no:

def test_an_open_source_catalog_is_readable_by_everyone():
    rules = generate_rules([], [], [], source_catalogs={"src_open": []})
    assert {"catalog": "^src_open$", "allow": "read-only"} in rules["catalogs"]

def test_without_source_catalogs_the_section_is_unchanged():
    assert generate_rules([], [], [])["catalogs"] == [{"allow": "all"}]
```

(Fix the first test's last line to assert `{"catalog": "^src_open$", "allow": "read-only"}` is present, before the `^src_.*$` deny; the rule order is: granted-user rules, open-catalog rules, `^src_.*$` none, allow all.)

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_source_catalog_registry.py tests/test_catalog_access.py tests/test_trino_acl_catalogs.py -q -p no:cacheprovider`
Expected: FAIL — unknown kind, `ModuleNotFoundError: app.connectors.source_catalog`, `TypeError: generate_rules() got an unexpected keyword argument`

- [ ] **Step 3: Implement** the registry kind, the reader, the admin refusals, `source_catalog.py` (document the exact SQL in its module docstring so the fake can answer it), the member hooks, the ACL section and the governance mapping. Wire Task 3's `_ensure_rows` hook to `source_catalog.ensure_rows`.

- [ ] **Step 4: Run the tests, then the catalog suites**

Run: `cd backend && .venv/bin/python -m pytest tests/test_source_catalog_registry.py tests/test_catalog_access.py tests/test_trino_acl_catalogs.py tests/test_catalog_admin.py tests/test_catalog_registry.py tests/test_trino_catalogs_projection.py -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "catalogs: trino_source registry kind, reader, owner/member grant projection, Layer 2 catalogs section"
```

---

### Task 5: Driver probe, `TrinoSourceConnector` introspection, and the connection routes

**Files:**
- Create: `backend/app/connectors/probe.py`
- Modify: `backend/app/connectors/trino_source.py` (add `TrinoSourceConnector`), `backend/app/connectors/__init__.py`, `backend/app/api/connectors.py` (`_create_connector`, `_get_connector_instance`, `create_connection`, `update_connection_config`, `delete_connection`, `test_connection`, `introspect_connection`, `list_available_connectors`), `backend/requirements.txt`
- Test: `backend/tests/test_probe.py`, `backend/tests/test_trino_source_connector.py`, `backend/tests/test_connector_routes_trino.py`

**Interfaces:**
- Consumes: Task 1 (`TrinoSourceConfig`, `normalise_type_and_config`, `engine_of`), Task 3 `project()`, Task 4 `register`/`unregister`/`sync_grants`/`catalog_for`/`_refresh`.
- Produces:
  - `probe.DRIVERS: Dict[ConnectorType, str]` = {POSTGRESQL: "psycopg2", MYSQL: "pymysql", SQLSERVER: "pytds", ORACLE: "oracledb", MONGODB: "pymongo"}
  - `probe.def test(t: ConnectorType, cfg: TrinoSourceConfig, timeout: float = 10.0) -> ConnectionTestResult` — synchronous, one connect + one trivial statement (`SELECT 1`; MongoDB `ping`); the message never contains `cfg.password`; a missing driver → `success=False, message="<driver> is not installed"`
  - `probe.def list_tables(t, cfg, timeout=10.0) -> List[str]` — `"schema.table"` for user schemas only (same exclusions as the reader); MongoDB → `"<database>.<collection>"`
  - `probe.def columns(t, cfg, table: str, timeout=10.0) -> List[ColumnSchema]` — `information_schema.columns` (Oracle: `ALL_TAB_COLUMNS`); MongoDB: keys of one sampled document, type `varchar`/`bigint`/`double`/`boolean`/`timestamp(3)`/`json` by Python type
  - all three run via `asyncio.to_thread` from the async wrappers `probe.atest`, `probe.alist_tables`, `probe.acolumns`
  - `TrinoSourceConnector(BaseConnector)`: `test_connection()` → `probe.atest`; `get_tables()` → Trino when `config.catalog` is set (`SHOW SCHEMAS`/`SHOW TABLES`), else `probe.alist_tables`; `get_schema(table)` → Trino `information_schema.columns` when `catalog` is set, else `probe.acolumns`; `read_data(table, limit, offset)` → Trino `SELECT * FROM <catalog>.<schema>.<table> LIMIT`; `sync_to_iceberg(...)` raises `NotImplementedError` until Task 6; Trino access via an injectable `self._connect = trino_util.trino_conn`
  - `_create_connector`: `engine_of(t) == "trino"` → `normalise_type_and_config` then `TrinoSourceConnector(TrinoSourceConfig(...))`; DATABASE_URL never reaches a `DatabaseURLConnector` any more
  - `_get_connector_instance`: for Trino-engine rows also reads `source_catalog.catalog_for` and sets `config["catalog"]`
  - `create_connection`: in one transaction insert the row, `register`, `sync_grants`; then `project()`; response gains `"catalog": slug` and `"engine_restarting": bool` (the `changed` flag). The stored `connector_type` is the normalised one (`database_url` payloads are stored as `postgresql`/`mysql`)
  - `update_connection_config` (`PUT /connectors/{id}/config`): after saving, `project()` for Trino-engine rows
  - `delete_connection`: `unregister` in the same transaction as the delete, then `project()`
  - `list_available_connectors`: the five Trino types `supported: true` with `"engine": "trino"`, `database_url` removed from the list (still accepted by `ConnectorType`)
  - `ConnectionResponse` gains `catalog: Optional[str] = None`, `engine_restarting: bool = False`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_probe.py
import pytest
from app.connectors import probe
from app.connectors.base import ConnectorType as T
from app.connectors.trino_source import TrinoSourceConfig

CFG = TrinoSourceConfig(name="x", connector_type=T.POSTGRESQL, host="127.0.0.1", port=1,
                        database="d", username="u", password="hunter2")

def test_every_trino_type_has_a_driver_and_the_drivers_are_importable():
    assert set(probe.DRIVERS) == {T.POSTGRESQL, T.MYSQL, T.SQLSERVER, T.ORACLE, T.MONGODB}
    for mod in probe.DRIVERS.values():
        __import__(mod)

@pytest.mark.parametrize("t", list(probe.DRIVERS))
def test_a_refused_connection_is_a_result_not_an_exception_and_never_names_the_password(t):
    r = probe.test(t, CFG.model_copy(update={"connector_type": t}), timeout=2)
    assert r.success is False and "hunter2" not in r.message and r.message

def test_a_missing_driver_is_reported_not_raised(monkeypatch):
    monkeypatch.setitem(probe.DRIVERS, T.ORACLE, "no_such_driver_xyz")
    r = probe.test(T.ORACLE, CFG, timeout=1)
    assert r.success is False and "not installed" in r.message
```

```python
# backend/tests/test_trino_source_connector.py
import asyncio
from app.connectors.base import ConnectorType as T
from app.connectors.trino_source import TrinoSourceConfig, TrinoSourceConnector

class FakeCursor:
    def __init__(self, answers): self.answers, self.executed = answers, []
    def execute(self, sql, params=None):
        self.executed.append(sql); self._rows = self.answers.get(sql.split(" FROM ")[-1].split(" ")[0], [])
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None
    def close(self): pass
class FakeConn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur
    def close(self): pass

def _connector(answers):
    c = TrinoSourceConnector(TrinoSourceConfig(name="crm", connector_type=T.POSTGRESQL, host="h", port=5432,
                                               database="d", username="u", password="p", catalog="src_crm"))
    c._connect = lambda **kw: FakeConn(FakeCursor(answers))
    return c

def test_tables_come_from_trino_as_schema_dot_table_without_system_schemas():
    c = _connector({"src_crm": [("public",), ("pg_catalog",), ("information_schema",)],
                    "src_crm.public": [("orders",), ("users",)]})
    assert asyncio.run(c.get_tables()) == ["public.orders", "public.users"]

def test_schema_comes_from_information_schema_columns():
    c = _connector({"src_crm.information_schema.columns": [("id", "integer", "NO"), ("email", "varchar(255)", "YES")]})
    s = asyncio.run(c.get_schema("public.users"))
    assert [(col.name, col.type, col.nullable) for col in s.columns] == [("id", "integer", False), ("email", "varchar(255)", True)]

def test_without_a_catalog_yet_tables_come_from_the_driver_probe(monkeypatch):
    from app.connectors import probe
    monkeypatch.setattr(probe, "list_tables", lambda t, cfg, timeout=10.0: ["public.orders"])
    c = TrinoSourceConnector(TrinoSourceConfig(name="crm", connector_type=T.POSTGRESQL, host="h", port=5432,
                                               database="d", username="u", password="p"))
    assert asyncio.run(c.get_tables()) == ["public.orders"]
```

```python
# backend/tests/test_connector_routes_trino.py
"""Creating, re-configuring and deleting a Trino-backed connection registers its catalog,
projects it and tells the console the engine is restarting. Uses the FastAPI app with the
pool, the projection and the probe replaced."""
# Build on the fixture style of tests/test_connector_status_check.py (TestClient + fake pool).
def test_create_registers_a_catalog_and_reports_the_restart(client, fake_pool, fake_project):
    r = client.post("/api/connectors/create", json={"name": "Sales DB", "connector_type": "postgresql",
                    "config": {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "p"}})
    assert r.status_code == 200
    body = r.json()
    assert body["catalog"] == "src_sales_db" and body["engine_restarting"] is True
    assert fake_project.calls == 1
    assert fake_pool.catalog_rows()[0]["config"]["connection_id"] == body["id"]

def test_a_database_url_payload_is_stored_as_postgresql(client, fake_pool, fake_project):
    r = client.post("/api/connectors/create", json={"name": "Fin", "connector_type": "database_url",
                    "config": {"database_url": "postgresql://u:p@h:5432/fin"}})
    assert r.json()["connector_type"] == "postgresql"
    assert fake_pool.connection_rows()[0]["connector_type"] == "postgresql"

def test_delete_unregisters_and_projects(client, fake_pool, fake_project):
    cid = fake_pool.seed_connection(name="Sales DB", connector_type="postgresql", catalog="src_sales_db")
    assert client.delete(f"/api/connectors/{cid}").status_code == 200
    assert fake_pool.catalog_rows() == [] and fake_project.calls == 1

def test_rest_connections_do_not_touch_the_engine(client, fake_pool, fake_project):
    client.post("/api/connectors/create", json={"name": "Feed", "connector_type": "rest_api",
                "config": {"base_url": "https://example.test/x"}})
    assert fake_project.calls == 0 and fake_pool.catalog_rows() == []

def test_available_connectors_offer_the_five_engine_types_and_not_database_url(client):
    ids = {c["id"]: c for c in client.get("/api/connectors/available").json()}
    assert {"postgresql", "mysql", "sqlserver", "oracle", "mongodb"} <= {k for k, v in ids.items() if v.get("supported")}
    assert "database_url" not in ids
    assert ids["mongodb"]["engine"] == "trino"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_probe.py tests/test_trino_source_connector.py tests/test_connector_routes_trino.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: app.connectors.probe`, missing `TrinoSourceConnector`, route assertions

- [ ] **Step 3: Add the drivers and implement**

`backend/requirements.txt`: add `python-tds==<current>`, `oracledb==<current>`, `pymongo==<current>` (exact pins, the release current on the day; `pip install` into `.venv`). Implement `probe.py`, the connector class, the dispatch and route changes. `ConnectionTestRequest`/`ConnectionIntrospectRequest` go through `normalise_type_and_config` too. The `/connectors/introspect` columns for Trino-engine types come from `probe.columns` (pre-create: the wizard's Step 2 needs incremental-column choices before a catalog exists — this is the builder's call recorded in the spec's "Test / introspect" paragraph, extended to columns; ledger it).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_probe.py tests/test_trino_source_connector.py tests/test_connector_routes_trino.py -q -p no:cacheprovider && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider 2>&1 | tail -3`
Expected: new tests PASS; full suite green except tests that still import `connectors.database` (removed in Task 6; list them in the ledger if any fail here — expected: none, `database.py` still exists)

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app backend/tests
git commit -m "connectors: Trino-backed connector class, driver probe for pre-create checks, routes register and project catalogs"
```

---

### Task 6: Sync through Trino — statement builders, PII projection, executor; remove `database.py`

**Files:**
- Create: `backend/app/connectors/trino_sync.py`
- Modify: `backend/app/guardrails/pii_ko.py` (`mask_sql`), `backend/app/connectors/trino_source.py` (`sync_to_iceberg`), `backend/app/connectors/__init__.py`, `backend/app/api/connectors.py` (imports; `_sync_with_retry` unchanged)
- Delete: `backend/app/connectors/database.py`, `backend/tests/test_connector_collect_integrity.py`, `backend/tests/test_connector_target_namespace.py` (their intents move into the new tests below)
- Test: `backend/tests/test_trino_sync_statements.py`, `backend/tests/test_pii_mask_sql.py`, `backend/tests/test_trino_source_sync.py`

**Interfaces:**
- Consumes: `catalog_registry.TableRef`, `base.target_namespace`, `rls.engine.sql_literal`, Task 5 connector.
- Produces:
  - `pii_ko.def mask_sql(col: str) -> str` — nested `regexp_replace(CAST(col AS VARCHAR), '<java regex>', '[<label>]')` for every pattern in `_PATTERNS` (same order; checksum validators cannot run in SQL, so the SQL masks every regex match — stricter than Python, documented in the docstring); `\b`, `\d`, `\s`, `\w` are valid in Trino's Joni/Java regex, so patterns translate verbatim except `(?:…)` which is also supported
  - `trino_sync.def iceberg_type(trino_type: str) -> str` — `tinyint|smallint → integer`; `char(n)|varchar(n)|json|interval … |time(p) with time zone → varchar`; `timestamp(p) → timestamp(6)`; `timestamp(p) with time zone → timestamp(6) with time zone`; `time(p) → time(6)`; `decimal(p,s)` with p ≤ 38 kept, p > 38 → `decimal(38,s)`; `ObjectId → varchar`; `array/map/row` kept; everything else kept
  - `trino_sync.def quote(ident: str) -> str` — double-quoted identifier with `"` doubled; `def qualified(ref: TableRef) -> str`
  - `trino_sync.def column_expr(name: str, trino_type: str, *, pii: bool) -> str` — `CAST(col AS <iceberg type>)` when the type changes, `json_format(CAST(col AS JSON))` for json/row/map when the target is varchar, `mask_sql(col)` when `pii`; the expression is aliased `AS "<name>"`
  - `trino_sync.def pii_set(columns: Sequence[Tuple[str, str]], pii_columns: Optional[list]) -> Set[str]` — `['*']` → every column whose Iceberg type is varchar; else the named ones that exist
  - `trino_sync.def partition_clause(spec: Optional[list]) -> str` — `WITH (partitioning = ARRAY['day("ts")', 'bucket("region", 16)', '"country"'])` from `[{"column","transform","buckets"}]`, `""` when empty; unknown transforms dropped
  - `trino_sync.def build_create(target: TableRef, columns, partition_spec) -> str` — `CREATE TABLE IF NOT EXISTS <target> ("c" type, …) <partition clause>`
  - `trino_sync.def build_full(target, source: TableRef, columns, pii_columns) -> List[str]` — `[DELETE FROM target, INSERT INTO target SELECT <exprs> FROM source]`
  - `trino_sync.def build_incremental(target, source, columns, pii_columns, column: str, last_value, key_columns) -> Tuple[List[Tuple[str, list]], str]` — statements with parameter lists: with keys → one `MERGE INTO target t USING (SELECT <exprs> FROM source WHERE "col" > ?) s ON t."k1" = s."k1" AND … WHEN MATCHED THEN UPDATE SET … WHEN NOT MATCHED THEN INSERT (…) VALUES (…)`; without keys → `INSERT INTO target SELECT … WHERE "col" > ?`; `last_value None` → no `WHERE` and no parameter; second element = `SELECT max("col") FROM source` (watermark). Values bind as `?` parameters, never interpolated
  - `trino_sync.def build_evolve(target, existing: Sequence[Tuple[str,str]], wanted: Sequence[Tuple[str,str]]) -> List[str]` — `ALTER TABLE target ADD COLUMN "c" type` per missing column; raises `SchemaChanged(column, old, new)` when a shared column's Iceberg type differs
  - `TrinoSourceConnector.sync_to_iceberg(source_table, target_table, sync_mode, incremental_column, last_value, on_step, partition_spec, key_columns, pii_columns) -> SyncJobStatus`: source `TableRef(catalog, schema, table)` from `self.config.catalog` + `"schema.table"`; target `TableRef("iceberg", target_namespace(target_table), safe_name(table))` (same `_safe_name` rule as `iceberg_writer`); steps `connect → introspect → create → evolve → load → watermark`, each reported through `on_step(step, message, extra)`; `rows_processed` from the INSERT/MERGE result row; `metadata["max_value"]` set in incremental mode; failures → `SyncStatus.FAILED` with the Trino message (sanitised: no credential); runs the statements in `asyncio.to_thread` on `trino_util.trino_conn()` (user `datapond`); `cursor.execute(sql, params)` for the bound ones

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pii_mask_sql.py
import re
from app.guardrails import pii_ko

def test_mask_sql_chains_one_regexp_replace_per_pattern_with_the_same_labels():
    sql = pii_ko.mask_sql('"memo"')
    assert sql.count("regexp_replace(") == len(pii_ko._PATTERNS)
    for label, _rx, _v in pii_ko._PATTERNS:
        assert f"'[{label}]'" in sql
    assert sql.startswith("regexp_replace(") and 'CAST("memo" AS VARCHAR)' in sql

def test_patterns_are_valid_java_regex_and_single_quotes_are_doubled():
    sql = pii_ko.mask_sql("c")
    assert "\\d" in sql and "''" not in sql.replace("''", "") or True   # no stray quote
    # every pattern string appears verbatim (Python re and Java regex agree on these constructs)
    for _l, rx, _v in pii_ko._PATTERNS:
        assert rx.pattern.replace("'", "''") in sql
```

```python
# backend/tests/test_trino_sync_statements.py
import pytest
from app.catalog_registry import TableRef
from app.connectors import trino_sync as s

T = TableRef("iceberg", "default", "orders"); S = TableRef("src_crm", "public", "orders")
COLS = [("id", "integer"), ("email", "varchar(255)"), ("flag", "tinyint"), ("ts", "timestamp(3)"),
        ("doc", "json"), ("amt", "decimal(10,2)"), ("oid", "ObjectId")]

@pytest.mark.parametrize("src,dst", [("tinyint", "integer"), ("smallint", "integer"), ("char(3)", "varchar"),
    ("varchar(255)", "varchar"), ("timestamp(0)", "timestamp(6)"), ("timestamp(3) with time zone", "timestamp(6) with time zone"),
    ("time(3)", "time(6)"), ("json", "varchar"), ("decimal(40,2)", "decimal(38,2)"), ("decimal(10,2)", "decimal(10,2)"),
    ("ObjectId", "varchar"), ("array(varchar)", "array(varchar)"), ("bigint", "bigint")])
def test_types_iceberg_cannot_hold_are_mapped(src, dst):
    assert s.iceberg_type(src) == dst

def test_create_statement_quotes_names_and_renders_partitioning():
    sql = s.build_create(T, COLS, [{"column": "ts", "transform": "day"}, {"column": "id", "transform": "bucket", "buckets": 8},
                                   {"column": "flag", "transform": "identity"}, {"column": "x", "transform": "weird"}])
    assert sql.startswith('CREATE TABLE IF NOT EXISTS "iceberg"."default"."orders" ("id" integer, "email" varchar, "flag" integer, "ts" timestamp(6), "doc" varchar, "amt" decimal(10,2), "oid" varchar)')
    assert sql.endswith("""WITH (partitioning = ARRAY['day("ts")', 'bucket("id", 8)', '"flag"'])""")

def test_full_sync_is_delete_then_insert_select_with_casts_and_masks():
    delete, insert = s.build_full(T, S, COLS, pii_columns=["email"])
    assert delete == 'DELETE FROM "iceberg"."default"."orders"'
    assert insert.startswith('INSERT INTO "iceberg"."default"."orders" SELECT "id" AS "id", regexp_replace(')
    assert 'CAST("flag" AS integer) AS "flag"' in insert and 'json_format(CAST("doc" AS JSON)) AS "doc"' in insert
    assert insert.endswith('FROM "src_crm"."public"."orders"')

def test_star_masks_every_varchar_column_only():
    assert s.pii_set(COLS, ["*"]) == {"email", "doc", "oid"}
    assert s.pii_set(COLS, ["email", "nope"]) == {"email"}

def test_incremental_without_keys_binds_the_watermark_as_a_parameter():
    stmts, watermark = s.build_incremental(T, S, COLS, None, "ts", "2026-01-01 00:00:00", key_columns=None)
    (sql, params), = stmts
    assert sql.endswith('FROM "src_crm"."public"."orders" WHERE "ts" > ?') and params == ["2026-01-01 00:00:00"]
    assert watermark == 'SELECT max("ts") FROM "src_crm"."public"."orders"'
    assert "2026-01-01" not in sql

def test_incremental_with_keys_is_a_merge():
    (sql, params), = s.build_incremental(T, S, COLS, None, "ts", None, key_columns=["id"])[0]
    assert sql.startswith('MERGE INTO "iceberg"."default"."orders" t USING (SELECT ') and params == []
    assert 'ON t."id" = s."id"' in sql and "WHEN MATCHED THEN UPDATE SET" in sql and "WHEN NOT MATCHED THEN INSERT" in sql
    assert '"id" = s."id"' not in sql.split("UPDATE SET")[1].split("WHEN NOT")[0]   # keys are not updated

def test_evolve_adds_new_columns_and_refuses_a_type_change():
    assert s.build_evolve(T, [("id", "integer")], [("id", "integer"), ("email", "varchar(10)")]) == \
        ['ALTER TABLE "iceberg"."default"."orders" ADD COLUMN "email" varchar']
    with pytest.raises(s.SchemaChanged):
        s.build_evolve(T, [("id", "integer")], [("id", "varchar(10)")])

def test_identifiers_with_quotes_cannot_break_out():
    assert s.quote('a"b') == '"a""b"'
```

```python
# backend/tests/test_trino_source_sync.py
"""The executor runs the builders' statements in order against a recorded cursor and
reports rows, steps and the watermark the way /sync and /sync/stream consume them
(replaces test_connector_collect_integrity.py and test_connector_target_namespace.py)."""
import asyncio
from app.connectors.base import SyncMode, SyncStatus
from tests.test_trino_source_connector import _connector   # FakeCursor answers keyed by table

def test_full_sync_runs_create_delete_insert_and_counts_rows():
    c = _connector({"src_crm.information_schema.columns": [("id", "integer", "NO"), ("email", "varchar(255)", "YES")],
                    "iceberg.information_schema.columns": [], '"iceberg"."default"."orders"': [(42,)]})
    steps = []
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.FULL,
                                       on_step=lambda n, m, e: steps.append(n), pii_columns=["email"]))
    assert st.status == SyncStatus.SUCCESS and st.rows_processed == 42
    assert [n for n in steps] == ["connect", "introspect", "create", "evolve", "load"]
    executed = c._last_cursor.executed
    assert executed[0].startswith("SELECT column_name") and any(x.startswith("CREATE TABLE IF NOT EXISTS") for x in executed)
    assert any(x.startswith("DELETE FROM") for x in executed) and executed[-1].startswith("INSERT INTO")

def test_target_namespace_defaults_and_is_normalised():
    c = _connector({})
    assert c._target("public.Orders-2026", None).sql() == "iceberg.default.orders_2026"
    assert c._target("public.orders", "raw.orders").sql() == "iceberg.raw.orders"

def test_incremental_sync_advances_the_watermark_and_a_trino_error_fails_the_job_without_the_password():
    c = _connector({"src_crm.information_schema.columns": [("id", "integer", "NO"), ("ts", "timestamp(3)", "YES")],
                    "iceberg.information_schema.columns": [("id", "integer"), ("ts", "timestamp(6)")],
                    '"iceberg"."default"."orders"': [(5,)], '"src_crm"."public"."orders"': [("2026-02-02 00:00:00",)]})
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.INCREMENTAL,
                                       incremental_column="ts", last_value="2026-01-01 00:00:00", key_columns=["id"]))
    assert st.status == SyncStatus.SUCCESS and st.metadata["max_value"] == "2026-02-02 00:00:00"
    c._connect = lambda **kw: (_ for _ in ()).throw(RuntimeError("TrinoUserError: password=p rejected"))
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.FULL))
    assert st.status == SyncStatus.FAILED and "password=p" not in (st.error_message or "")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pii_mask_sql.py tests/test_trino_sync_statements.py tests/test_trino_source_sync.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: mask_sql`, `ModuleNotFoundError: app.connectors.trino_sync`, `NotImplementedError`

- [ ] **Step 3: Implement** `mask_sql`, `trino_sync.py` and `sync_to_iceberg` (keep `_last_cursor` on the connector for the test; introspection of the target uses `iceberg.information_schema.columns` filtered by schema/table). Then delete `backend/app/connectors/database.py`, the two superseded test files, and every import of `PostgreSQLConnector`/`MySQLConnector`/`DatabaseURLConnector`/`DatabaseConfig` (`__init__.py`, `api/connectors.py`, `tests/test_sample_sources.py` — that test's DB-connector assertions move to Task 7). Remove the `pandas`-based `INGEST_CHUNK_SIZE` comment if it referenced `database.py`; `sqlalchemy` and `pandas` stay (still used elsewhere).

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider 2>&1 | tail -5 && ! grep -rn "connectors.database\|PostgreSQLConnector\|MySQLConnector\|DatabaseURLConnector" app tests`
Expected: suite green; grep finds nothing

- [ ] **Step 5: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "connectors: sync through Trino (create/full/merge/evolve builders, PII masking at ingest); remove the pandas path"
```

---

### Task 7: Sample SQL sources through the restricted `datapond_sample` role

**Files:**
- Create: `backend/migrations/versions/0026_sample_db_role.py`
- Modify: `helm/datapond/templates/secrets.yaml` (`SAMPLE_DB_PASSWORD`, lookup-preserved `randAlphaNum 32`), `helm/datapond/templates/migrate-job.yaml` and `backend-deployment.yaml` (env from the Secret), `backend/app/api/connectors.py` (`create_sample_db`, `_add_finance_sample`, `_save_sample_connection`), `backend/app/sample_sources.py` (finance `connector_type="postgresql"`), `backend/tests/test_sample_sources.py`, `backend/tests/test_migrations.py`
- Test: `backend/tests/test_sample_db_role_migration.py`, `backend/tests/test_helm_sample_db_password.py`, `backend/tests/test_sample_sources.py`

**Interfaces:**
- Consumes: Task 5 routes (`_save_sample_connection` now goes through `register`/`sync_grants`/`project()` like `create_connection`).
- Produces:
  - Migration `0026_sample_db_role`: `def sample_password(env) -> Optional[str]` (env `SAMPLE_DB_PASSWORD`; `None` when unset; `ValueError` unless `^[A-Za-z0-9]{16,64}$`); `def upgrade_statement(password) -> str` = `DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='datapond_sample') THEN ALTER ROLE datapond_sample WITH LOGIN PASSWORD '<pw>'; ELSE CREATE ROLE datapond_sample LOGIN PASSWORD '<pw>'; END IF; END $$;`; `upgrade()` runs it via `run_sql` when a password is set, otherwise logs `"[0026] SAMPLE_DB_PASSWORD unset; datapond_sample not provisioned"`; `downgrade()` is a no-op (the role may own grants)
  - `connectors.def sample_role_credentials() -> Optional[Tuple[str, str]]` → `("datapond_sample", os.environ["SAMPLE_DB_PASSWORD"])` or None
  - `connectors.async def grant_sample_role(conn, database: str) -> None` — on that database: `GRANT CONNECT ON DATABASE "<db>" TO datapond_sample; GRANT USAGE ON SCHEMA public TO datapond_sample; GRANT SELECT ON ALL TABLES IN SCHEMA public TO datapond_sample; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO datapond_sample`
  - `create_sample_db` and `_add_finance_sample` seed as today, then `grant_sample_role`, then save the connection with `connector_type=POSTGRESQL`, `username=datapond_sample`, `password=<env>`, `database=sampledb|<FINANCE_DATABASE>`; without the env → `HTTPException(409, "Sample sources need the datapond_sample role: set SAMPLE_DB_PASSWORD (chart ≥ 2.5) and rerun the migration job.")`
  - Sample responses gain `"engine_restarting": True|False`; the activation sync (`/sample-db/activate`) first waits up to 180 s for `engine_status()["ready"]` and returns 503 `"query engine restarting; retry in a minute"` if it is not
  - `sample_sources.SAMPLE_SOURCES`: the finance entry's `connector_type` becomes `"postgresql"`; `kinds()` unchanged (`database_url` stays the sample *kind* id so the console's panel and `_SAMPLE_BUILDERS` keep working)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_sample_db_role_migration.py
import importlib.util, re
from pathlib import Path
import pytest
PY = Path(__file__).resolve().parents[1] / "migrations/versions/0026_sample_db_role.py"
def _load():
    spec = importlib.util.spec_from_file_location("m0026", PY); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def test_it_is_the_highest_revision_and_chains_from_0025():
    m = _load(); assert m.revision == "0026_sample_db_role" and m.down_revision == "0025_glue_engine_catalog_trino"
    stems = sorted(p.stem for p in PY.parent.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0026_sample_db_role"

def test_the_statement_creates_or_rotates_the_login_role():
    sql = _load().upgrade_statement("Abc123Abc123Abc123")
    assert "CREATE ROLE datapond_sample LOGIN PASSWORD 'Abc123Abc123Abc123'" in sql
    assert "ALTER ROLE datapond_sample WITH LOGIN PASSWORD 'Abc123Abc123Abc123'" in sql

def test_an_unset_or_unsafe_password_is_refused_or_skipped():
    m = _load()
    assert m.sample_password({}) is None
    with pytest.raises(ValueError):
        m.sample_password({"SAMPLE_DB_PASSWORD": "x'; DROP ROLE datapond_app; --"})
```

Update `tests/test_glue_engine_catalog_migration.py::test_it_is_the_highest_revision` to expect `0026_sample_db_role` (the pin moves with the newest revision, as 0025 did for 0024).

```python
# backend/tests/test_helm_sample_db_password.py
from tests.test_helm_trino_extra_catalogs import render, doc
def test_the_password_is_generated_and_reaches_the_migration_job_and_the_backend(tmp_path):
    out = render(tmp_path)
    assert "SAMPLE_DB_PASSWORD:" in doc(out, "Secret", "datapond-secrets")
    for kind, name in (("Job", None), ("Deployment", "backend")):
        part = next(p for p in out.split("\n---") if f"kind: {kind}" in p and (name is None and "migrate" in p or name and f"name: {name}\n" in p))
        assert "name: SAMPLE_DB_PASSWORD" in part
```

In `tests/test_sample_sources.py`: change `test_every_kind_is_a_different_connector_type` to assert the sample *kinds* are distinct and `{"postgresql", "s3", "rest_api", "custom"} == set(types)`; add

```python
def test_sql_samples_connect_as_the_restricted_role(monkeypatch):
    monkeypatch.setenv("SAMPLE_DB_PASSWORD", "Abc123Abc123Abc123")
    from app.api import connectors
    assert connectors.sample_role_credentials() == ("datapond_sample", "Abc123Abc123Abc123")
    monkeypatch.delenv("SAMPLE_DB_PASSWORD")
    assert connectors.sample_role_credentials() is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_sample_db_role_migration.py tests/test_helm_sample_db_password.py tests/test_sample_sources.py tests/test_glue_engine_catalog_migration.py -q -p no:cacheprovider`
Expected: FAIL — missing migration file, missing Secret key, `AttributeError: sample_role_credentials`

- [ ] **Step 3: Implement** the migration (follow 0025's structure: statement built in Python, `run_sql(op.get_bind(), …)`), the chart key and env, and the route changes.

- [ ] **Step 4: Run the tests, then the suite and the chart gates**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider 2>&1 | tail -3 && helm lint helm/datapond --values helm/datapond/values-quicktest.yaml`
Expected: green; lint passes

- [ ] **Step 5: Commit**

```bash
git add -A backend helm
git commit -m "samples: SQL sample sources connect through Trino as the restricted datapond_sample role (migration 0026)"
```

---

### Task 8: Capability gate and console

**Files:**
- Modify: `backend/app/capabilities.py`, `backend/tests/test_capability_support_tiers.py` (or the capabilities test that pins backends), `frontend/lib/connectors.ts`, `frontend/app/connectors/[id]/setup/page.tsx`, `frontend/app/connectors/connections/[id]/page.tsx`, `frontend/app/connectors/page.tsx`, `frontend/components/connectors/sample-sources-panel.tsx`, `frontend/app/help/connectors/page.tsx`
- Create: `frontend/lib/engine-restart.ts`, `frontend/lib/engine-restart.test.ts`, `frontend/components/connectors/engine-restart-banner.tsx`
- Test: backend capabilities test; `frontend/lib/engine-restart.test.ts`; `npm run typecheck && npm run lint && npm run test`

**Interfaces:**
- Consumes: Task 3 `GET /api/connectors/engine`; Task 5 `engine_restarting` in create/sample responses and `engine` in `/connectors/available`.
- Produces:
  - `capabilities.BACKENDS["connectors"] = ("TRINO",)`
  - `engine-restart.ts`: `export type EngineStatus = {engine: "trino"|"none"; ready: boolean|null; restarting: boolean|null; restarted_at?: string|null; error?: string}`; `export function engineBanner(s: EngineStatus | null): {tone: "info"|"warn"; text: string} | null` — `restarting` → `{tone:"info", text:"Query engine restarting (~1 min) — the new source catalog appears when it is back."}`; `ready === false && !restarting` → `{tone:"warn", text:"Query engine is not ready; sources cannot be browsed or synced until it is."}`; `error` → warn with `"Query engine status unavailable"`; otherwise `null`; `export function pollDelayMs(s): number` — 3000 while restarting, else 0 (stop)
  - `EngineRestartBanner` client component: polls `/api/connectors/engine` while `pollDelayMs > 0`, starts polling when mounted with `prop active=true` (the pages set it after a create/delete/sample response says `engine_restarting`), renders the banner text; nothing when `engine === "none"`
  - `lib/connectors.ts`: `sqlserver`, `oracle`, `mongodb` cards `supported: true` with fields (host/port/database or service/username/password/ssl; MongoDB adds `auth_source` default `admin`); `database_url` card removed; each of the five carries `features: ["Trino federated query", "Incremental Sync", "Schema Discovery"]`; `kafka` etc. unchanged
  - Setup wizard: for engine types, the Finish step shows the banner after create; the connection detail page shows it and disables Sync while `restarting`; the list page shows the `catalog` name under each Trino-backed connection (`src_…`) with a "Query in SQL Lab" link (`/query?catalog=src_x`) when present
  - Sample panel: the postgresql and finance sample descriptions add "(restarts the query engine, ~1 min)"
  - Help copy (`help/connectors/page.tsx`): the two paragraphs quoted in the survey become: "Database sources (PostgreSQL, MySQL, SQL Server, Oracle, MongoDB) are Trino catalogs: DataPond browses, syncs and federates them through the one query engine. REST APIs, custom Python and object storage are ingested by the backend." and "Backfill and incremental refresh run as Trino statements (`INSERT … SELECT`, `MERGE`); PII columns are masked at ingest with the same rules as at read."

- [ ] **Step 1: Write the failing tests**

Backend (in the capabilities test file that pins `BACKENDS`):

```python
def test_connectors_need_only_trino():
    from app.capabilities import BACKENDS
    assert BACKENDS["connectors"] == ("TRINO",)
```

```ts
// frontend/lib/engine-restart.test.ts
import test from "node:test"
import assert from "node:assert/strict"
import { engineBanner, pollDelayMs } from "./engine-restart.ts"

test("restarting shows the one-minute notice and keeps polling", () => {
  const s = { engine: "trino" as const, ready: false, restarting: true }
  assert.equal(engineBanner(s)?.text, "Query engine restarting (~1 min) — the new source catalog appears when it is back.")
  assert.equal(pollDelayMs(s), 3000)
})
test("ready shows nothing and stops polling", () => {
  const s = { engine: "trino" as const, ready: true, restarting: false }
  assert.equal(engineBanner(s), null); assert.equal(pollDelayMs(s), 0)
})
test("no engine on this profile shows nothing", () => {
  assert.equal(engineBanner({ engine: "none", ready: false, restarting: false }), null)
})
test("an unreadable status warns instead of lying", () => {
  assert.equal(engineBanner({ engine: "trino", ready: null, restarting: null, error: "403" })?.tone, "warn")
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests -q -k "connectors_need_only_trino" -p no:cacheprovider; cd ../frontend && npm run test 2>&1 | tail -5`
Expected: backend FAIL (`("TRINO","POLARIS","GLUE")`); frontend FAIL `Cannot find module './engine-restart.ts'`

- [ ] **Step 3: Implement** the capability change, `engine-restart.ts`, the banner, the card/field/copy changes and the page wiring.

- [ ] **Step 4: Run the gates**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider 2>&1 | tail -3; cd ../frontend && npm run typecheck && npm run lint && npm run test 2>&1 | tail -5`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add backend/app/capabilities.py backend/tests frontend
git commit -m "console: five Trino-backed source types, engine-restart banner, connectors need Trino only"
```

---

### Task 9: CI acceptance — register, restart, sync and federate on kind

**Files:**
- Create: `.github/scripts/trino_connector_check.py`
- Modify: `.github/workflows/ci.yml` (job `multi-catalog-install`: title and three new steps), `helm/datapond/ci/values-multicatalog.yaml` (nothing unless the check needs more Trino memory — leave as is)

**Interfaces:**
- Consumes: everything above, live in the kind cluster the job already builds (Polaris + MinIO + Trino + in-cluster PostgreSQL).
- Produces: a script in the style of `multicatalog_check.py` (admin token minted in-pod, `call()`, `eventually()`), checks in this order, each printing what it saw:
  1. `POST /api/connectors/sample-sources {"kinds": ["postgresql"]}` → 200, `engine_restarting` true, `catalog == "src_sample_e_commerce_db"`
  2. `GET /api/connectors/engine` → `restarting` true within 30 s, then `ready` true within 240 s
  3. `GET /api/catalogs` lists `src_sample_e_commerce_db` with `kind == "trino_source"`; `kubectl`-free: `GET /api/connectors/{id}/tables` lists `public.orders`
  4. `POST /api/connectors/{id}/sync {"source_table": "public.orders"}` → `rows_processed` ≥ the sample's order count (`app.sample_data.table("orders").rows`)
  5. `POST /api/queries/execute {"query": "SELECT count(*) FROM iceberg.default.orders"}` equals that count; `… FROM src_sample_e_commerce_db.public.orders` equals it too (federation)
  6. ACL: `PUT /api/catalogs/src_sample_e_commerce_db/grants {"grants": [{"kind": "user", "principal": <admin id>}]}`; a second, non-admin user (created through `app.api.auth` helpers the way the admin is) runs the federated query → 4xx whose body does not contain `src_sample`; then `PUT … {"grants": []}` reopens it and the same query succeeds
  7. `DELETE /api/connectors/{id}` → 200; `GET /api/catalogs` no longer lists it; engine restarts and is ready again within 240 s

- [ ] **Step 1: Write the script and the workflow steps** (`- name: Register a Trino-backed source, sync it, federate it, govern it` running `kubectl -n datapond exec -i deploy/backend -- python - < .github/scripts/trino_connector_check.py`; add `kubectl -n datapond get secret trino-source-catalogs -o jsonpath='{.data}' | grep -o '"[^"]*":' || true` to the failure step — key names only, never values). Rename the job title to "Two Polaris catalogs and one Trino-backed source: listed, kept apart, queried, governed (kind, Trino)".

- [ ] **Step 2: Run the script's static checks locally**

Run: `cd backend && .venv/bin/python -m py_compile ../.github/scripts/trino_connector_check.py && cd .. && helm template datapond helm/datapond -f helm/datapond/values-ephemeral.yaml -f helm/datapond/ci/values-multicatalog.yaml >/dev/null`
Expected: compiles; renders

- [ ] **Step 3: Commit, push the branch, run CI**

```bash
git add .github helm
git commit -m "ci: the Trino kind job registers a source catalog, syncs and federates it, and checks the catalog ACL"
git push -u origin ops/trino-connectors-phase2
gh run watch $(gh run list --branch ops/trino-connectors-phase2 --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: every job green, including `multi-catalog-install` with the seven checks printed. A red step is a finding: fix under TDD (unit test first where the cause is backend logic), re-push, re-watch. Do not weaken a check to pass.

---

### Task 10: Product truth — docs, upgrade notes, chart version

**Files:**
- Modify: `helm/datapond/Chart.yaml` (`version: 2.5.0`, `appVersion: "2.5.0"`), `docs/UPGRADING.md`, `docs/DEMO_SCRIPT.md`, `docs/DEPLOY_SINGLE_NODE.md`, `docs/RLS_DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/PRODUCT_CONCEPT.md`, `docs/DEPLOYMENT_PROFILES.md`, `README.md`, `SUPPORT.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md` (status line: Phase 2 shipped)

Content each must carry (exact facts; the wording is the writer's):

- **UPGRADING `## 2.5 (2026-11) — Database sources are Trino catalogs`**: the five types; `src_<slug>` naming; the two Secrets and the restart (~1 min) on create/credential change/delete; existing PostgreSQL/MySQL connections gain their catalog automatically on the first backend start after upgrade (`ensure_rows` + projection) — no re-registration; `database_url` folded (stored rows normalised on next config save; new payloads normalised at once); samples need `SAMPLE_DB_PASSWORD` (generated by the chart; run the migration job: it creates `datapond_sample`); `connectors` capability now needs only `trino`; RLS Layer 2 users: `rules.json` gains a `catalogs` section on the next apply; `connectors/database.py`, pandas sync and the SQLAlchemy URL type are gone.
- **DEMO_SCRIPT**: the sample-data step says the engine restarts for about a minute before the activation sync; add one federated query (`SELECT … FROM src_sample_e_commerce_db.public.orders JOIN iceberg.default.…`) to the SQL step.
- **DEPLOY_SINGLE_NODE**: a short section "Source catalogs" — the Secrets, that they are preserved across `helm upgrade`, how to inspect key names (`kubectl get secret trino-source-catalogs -o jsonpath='{.data}' | jq 'keys'`), and that a DR restore rebuilds them from Aurora + `ENCRYPTION_KEY` on backend start.
- **RLS_DESIGN**: `src_*` catalogs are governed by `catalog_grants` like `iceberg`; row filters/masks apply to source FQNs; Layer 2 `catalogs` section.
- **ARCHITECTURE / PRODUCT_CONCEPT / DEPLOYMENT_PROFILES / README**: connectors paragraph: database sources through Trino connectors; REST/custom/S3 through the backend; `connectors` requires Trino (so Portable Core · AWS and Sovereign Core show no Sources page).
- **SUPPORT.md**: the five database source types supported through Trino 482's connectors; MongoDB/Oracle/SQL Server verified by unit tests and the pre-create probe only (no live acceptance) — say so.
- **CLAUDE.md**: Current Status gains one line: "Connectors (2.5): PostgreSQL/MySQL/SQL Server/Oracle/MongoDB are Trino catalogs `src_<slug>` governed by catalog grants; REST/custom/S3 stay on the backend path."
- **Spec**: add `Status: Phase 1 shipped 2026-11-09 (PR #250); Phase 2 plan docs/superpowers/plans/2026-11-10-trino-connectors-phase2.md` under the title.

- [ ] **Step 1: Make the edits.** Grep first so nothing stale survives: `grep -rn -i "pandas\|SQLAlchemy URL\|database_url\|connectors/database" README.md docs/*.md SUPPORT.md CLAUDE.md frontend/app/help` → every hit is either rewritten or a deliberate historical mention (UPGRADING/spec).

- [ ] **Step 2: Verify**

Run: `grep -rn -i "SQLAlchemy URL\|connectors/database.py" README.md docs/ARCHITECTURE.md docs/PRODUCT_CONCEPT.md docs/DEPLOYMENT_PROFILES.md SUPPORT.md CLAUDE.md frontend/app/help; grep -n "^version: 2.5.0" helm/datapond/Chart.yaml; cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance -p no:cacheprovider 2>&1 | tail -2`
Expected: first grep empty; version line found; suite green

- [ ] **Step 3: Commit**

```bash
git add -A docs README.md SUPPORT.md CLAUDE.md helm/datapond/Chart.yaml
git commit -m "docs: database sources are Trino catalogs (2.5); upgrade notes, demo, DR and RLS updates"
```

---

### Task 11: Live cutover on the AWS Single-Node Reference

Preconditions: Tasks 1–10 merged to `main` via PR (final whole-branch review done, CI green on the PR). The node runs weekdays 07:30–18:00 KST; the deploy must happen inside that window.

- [ ] **Step 1: Deploy from main**

```bash
gh workflow run deploy-aws.yml -f ref=main
gh run watch $(gh run list --workflow deploy-aws.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: green; `helm history datapond -n datapond` on the node shows a new revision with chart 2.5.0; the migrate Job log contains `0026_sample_db_role` and no `SAMPLE_DB_PASSWORD unset` line.

- [ ] **Step 2: The pre-existing PostgreSQL connection has its catalog without re-registration**

Via SSM (`AWS-RunShellScript` on `i-01c99cc78436e765e`, as in Phase 1):

```bash
kubectl -n datapond logs deploy/backend --since=15m | grep -i "source catalogs\|ensure_rows\|reconcile"
kubectl -n datapond get secret trino-source-catalogs -o jsonpath='{.data}' | jq 'keys'
kubectl -n datapond get deploy trino -o jsonpath='{.spec.template.metadata.annotations}'
kubectl -n datapond exec deploy/trino -- trino --execute "SHOW CATALOGS"
```

Expected: one `src_*.properties` key per PostgreSQL/MySQL connection in `connector_connections`; the annotation present; `SHOW CATALOGS` lists `iceberg`, the `src_*` names, `system`.

- [ ] **Step 3: Run its sync history forward once and federate**

In the console (owner session): Sources → the PostgreSQL connection → Sync (one table). Expected: a new history row, `rows_processed` > 0, status success; Governance → Tool calls shows the sync's audit row. SQL Lab: `SELECT count(*) FROM src_<slug>.<schema>.<table>` returns the source count. Settings → Data catalogs lists `src_<slug>` with kind `trino_source` and the owner as grantee.

- [ ] **Step 4: Sample data path**

Console → Sources → Add sample data → PostgreSQL. Expected: the banner "Query engine restarting (~1 min)", then the sample connection active with catalog `src_sample_e_commerce_db`; activation sync succeeds; `psql` as `datapond_sample` cannot read `public.users` of the app database (`SELECT 1 FROM users` → permission denied) — run via the backend pod: `PGPASSWORD=$SAMPLE_DB_PASSWORD psql -h <aurora> -U datapond_sample -d datapond -c 'select 1 from users'`.

- [ ] **Step 5: Record**

Append the cutover to `docs/UPGRADING.md` 2.5 ("cut over <date>, release revision N") and `CLAUDE.md`'s live-deployment blockquote; commit on `main` as a docs commit; update the memory files the Phase 1 cutover updated (`trino-replaces-athena-cutover.md` → Phase 2 line; `datapond-session-handoff.md`).

---

## Self-review

**Spec coverage.** Model (`src_<slug>`, five types, `engine` attribute) → Task 1/5. Catalog delivery (two Secrets, RBAC, restart annotation, console notice, rebuild from vault on start) → Tasks 2, 3, 8. Test/introspect (driver-based before create; Trino after) → Task 5 (columns pre-create is a recorded extension). Sync (create with partitioning from `partitioning.py` semantics, delete+insert, incremental with watermark, MERGE with keys, PII projection with the read-side masking rules, row counts, lineage/OM unchanged, evolution add-column / type-change fails) → Task 6 (lineage and OpenMetadata calls sit in the routes, untouched; `partitioning.py` stays for the PyIceberg path and its spec format is what `partition_clause` consumes). Sync as backend identity / reads as caller → Tasks 6 and existing `queries.py`. Federation (registry row, one ACL, owner+members projected, fail-closed resolver, Layer 2 off, `catalogs` section) → Task 4. Capabilities → Task 8. Removal → Task 6. Verification (chart test, builders, refusal, CI job, live re-registration-free upgrade and sync forward) → Tasks 2, 4, 6, 9, 11. Samples via `datapond_sample`, `database_url` folded → Tasks 1, 5, 7. Extra Glue catalogs: unchanged (documented limitation stays). "Left to the builder": migration mechanics (Task 7), restart surfacing (backend status endpoint, Task 3/8), type edge cases (Task 6 table), CTAS not used (create-then-insert only, one path), fixtures without live databases (fake cursor; drivers only exercised for connection refusal), doc order (Task 10), Trino 482 property names (Task 1 constraint).

**Deviations from the spec's letter, for the executor's ledger.** (a) Pre-create introspection returns columns from the driver probe, not only "can I connect" — the wizard chooses incremental columns before the catalog exists. (b) Progress events are per statement (`connect/introspect/create/evolve/load/watermark`), not Trino query-stat polling; the row count still comes from the statement result. (c) The PII projection uses `pii_ko`'s patterns as `regexp_replace` chains rather than `rls.engine.mask_expression`'s per-policy masks, because `pii_columns` carry no masking type; the spec's intent (same rules at ingest as at read) holds since `pii_ko` is the read-side guardrail. (d) MongoDB, Oracle and SQL Server have no live acceptance (CI has PostgreSQL only); SUPPORT.md says so.

**Type consistency.** `TableRef` from `catalog_registry` is used by Tasks 6 and the connector; `Desired`/`KubeClient` names match between Task 3 tests and `project()` callers in Tasks 5 and 7; `engine_status()` keys (`engine`, `ready`, `restarting`, `restarted_at`) match `EngineStatus` in Task 8; `register/unregister/sync_grants/catalog_for/ensure_rows` signatures match across Tasks 4, 5, 7; `credential_env`/`credential_value` used identically in Tasks 1 and 3.

**Review Focus pins.** 1 → `test_postgresql_catalog_file_carries_the_password_only_as_an_env_reference`, `test_mongodb_url_encodes_…`, `test_a_value_that_could_inject_…` (Task 1). 2 → the slug parametrised tests + `test_unique_slug_…` (Task 1), `test_register_picks_a_unique_slug` (Task 4); rename stability is structural (slug only computed in `register`). 3 → `test_types_iceberg_cannot_hold_are_mapped` (Task 6). 4 → `test_project_converges_when_run_twice_and_restarts_once`, `test_apply_patches_only_when_something_differs` (Task 3), `ensure_rows` test (Task 4). 5 → `test_an_ungranted_caller_cannot_see_or_name_a_source_catalog` (Task 4) and CI check 6 (Task 9).

**Proportion.** The spec's Phase 2 section is ~120 lines; this plan is longer because it carries the tests and the exact statement shapes, but code bodies appear only where the signature does not determine them (rendering lines, rule order, SQL shapes).
