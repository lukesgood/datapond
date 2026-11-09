# Trino replaces Athena on the AWS Single-Node Reference — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The AWS reference runs Trino in-cluster over the existing Glue catalog, `QUERY_ENGINE` is Trino everywhere, and the Athena engine path (code, chart keys, IAM, alarm, docs) is gone.

**Architecture:** The chart renders a Glue-typed Iceberg catalog for Trino when `catalog.backend=glue`, turns Trino on in `values-prod-single.yaml`, and stops deriving an Athena engine from the catalog backend. The backend keeps its single `TrinoEngine`; the stored catalog name `AwsDataCatalog` survives as a registry **alias** (only `engine_catalog` changes, via one data migration), and the RLS policy matcher canonicalises through the registry so stored policies still match. The live cutover is one manual `helm upgrade` that re-supplies the profile values (the CD script reuses stored values, which still say `trino.enabled: false`).

**Tech Stack:** Helm 3 chart (`helm/datapond`), FastAPI backend (Python 3.12, pytest, sqlglot 26.33, trino 0.328), Alembic SQL migrations, Next.js frontend (`node --test`), Terraform 1.15, Trino 482 (`trinodb/trino:482`).

**Spec:** `docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md` (Phase 1 sections).

## Global Constraints

- Merge only at CI 0 fail / 0 pending. Chart tests run `helm template` through `subprocess` (see `backend/tests/test_helm_trino_extra_catalogs.py` for the harness shape).
- Backend tests run from `backend/.venv`: `.venv/bin/python -m pytest tests -q --ignore=tests/acceptance`.
- Trino catalog name on every profile stays `iceberg`. `RLS_DEFAULT_CATALOG=iceberg`, `RLS_DEFAULT_SCHEMA=default`.
- Nothing stored is rewritten except `data_catalogs.engine_catalog` on the one glue row. `query_history`, `tool_call_log`, `chat_action_invocations`, `auth_audit_log`, `ai_chunks` are untouched.
- Trino sizing stays at the chart defaults (requests 1 CPU/2 Gi, limits 2 CPU/4 Gi, `-Xmx2G`).
- Secrets never appear in rendered ConfigMaps or logs (no change to how Polaris/Postgres secrets are referenced).
- Athena-removal commits come **after** the chart/alias commits in the branch so a revert of the removal alone is clean.
- Historical documents are records and are not edited: `docs/MARKET_REVIEW_2026-10.md`, `docs/POSITIONING_REVIEW.md`, `docs/PRODUCTIZATION_READINESS_ASSESSMENT.md`, `docs/UTILIZATION_PERSONA_ASSESSMENT.md`, `docs/OPERATIONS_PAUSE.md`, `docs/ONTOLOGY_GRAPHRAG_REVIEW.md`, `docs/DESIGN_PARTNER_QUESTIONS.md`, `docs/DATA_RESIDENCY_BACKLOG.md`, `docs/CONCEPT_RECONFIRMATION.md`, `docs/superpowers/**`, `docs/archive/**`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A row-filter or mask policy stored with `catalog_name = AwsDataCatalog` must still apply to `SELECT * FROM iceberg.default.orders` and to bare `orders` after the engine calls the catalog `iceberg` (test in Task 3).
2. A metric version stored with `catalog = AwsDataCatalog` must compile to `iceberg.<schema>.<table>` (test in Task 3).
3. A fresh install on the glue backend must seed the registry default as `iceberg`, never `AwsDataCatalog` (test in Task 2).
4. `values-prod-single.yaml` rendered with a stale `--set trino.enabled=false` (what the live release's stored values say) must fail to render rather than produce a backend with no engine (test in Task 1).
5. Backend start while Trino is still warming up (every 07:30 KST boot) must not fail or block: medallion init is best-effort with a 10 s timeout, and a Query Lab call maps a connection failure to the 400 "Cannot connect to query engine" (tests in Task 2).

---

### Task 1: Chart — Glue-typed Iceberg catalog, Trino on the AWS reference, Athena keys gone

**Files:**
- Modify: `helm/datapond/templates/trino-deployment.yaml:184-212` (the `iceberg.properties` block)
- Modify: `helm/datapond/templates/networkpolicy.yaml:62-66` (IMDS allow-list podSelector)
- Modify: `helm/datapond/templates/backend-deployment.yaml:417-428, 448-453` (engine env derivation, `ATHENA_*` env)
- Modify: `helm/datapond/values-prod-single.yaml:47-57, 145-146`
- Modify: `helm/datapond/values.yaml:109-116` (catalog `athena*` keys)
- Modify: `helm/datapond/values-foundation.yaml:6` (comment only)
- Create: `helm/datapond/templates/_engine.tpl`
- Test: `backend/tests/test_helm_trino_glue_catalog.py` (new); `backend/tests/test_helm_sovereign_core.py:76`; `backend/tests/test_helm_addon_defaults.py:484`

**Interfaces:**
- Produces: rendered backend env `QUERY_ENGINE=trino`, `RLS_DEFAULT_CATALOG=iceberg`, `RLS_DEFAULT_SCHEMA=default` on every profile; no `FEATURE_ATHENA`, `ATHENA_OUTPUT_LOCATION`, `ATHENA_WORKGROUP`, `ATHENA_DATABASE` env anywhere; Trino `iceberg.properties` with `iceberg.catalog.type=glue` when `catalog.backend=glue`; helper `datapond.engineGuard` that fails rendering when `catalog.backend=glue` and Trino is not on.

- [ ] **Step 1: Write the failing chart tests**

`backend/tests/test_helm_trino_glue_catalog.py`, using the `render`/`doc` helpers copied from `test_helm_trino_extra_catalogs.py` but defaulting to `values="values-prod-single.yaml"` and **no** `--set trino.enabled=true`:

```python
def test_prod_single_renders_trino_with_a_glue_catalog(tmp_path):
    out = render(tmp_path)
    cm = doc(out, "ConfigMap", "trino-catalog")
    assert "iceberg.catalog.type=glue" in cm
    assert "hive.metastore.glue.region=us-east-1" in cm
    assert "hive.metastore.glue.default-warehouse-dir=s3://datapond-iceberg/warehouse" in cm
    assert "fs.native-s3.enabled=true" in cm
    assert "rest-catalog" not in cm and "jdbc-catalog" not in cm
    doc(out, "Deployment", "trino")  # Trino is on without any --set

def test_backend_engine_env_is_trino_on_every_profile(tmp_path):
    for values in ("values-prod-single.yaml", "values-onprem.yaml", "values-foundation.yaml"):
        out = render(tmp_path, values=values)
        be = doc(out, "Deployment", "backend")
        assert re.search(r"name: QUERY_ENGINE\n\s+value: \"trino\"", be)
        assert re.search(r"name: RLS_DEFAULT_CATALOG\n\s+value: \"iceberg\"", be)
        assert re.search(r"name: RLS_DEFAULT_SCHEMA\n\s+value: \"default\"", be)
        assert "ATHENA" not in out

def test_trino_may_reach_imds_on_the_aws_reference(tmp_path):
    np = doc(render(tmp_path), "NetworkPolicy", "datapond-allow-metadata-for-aws-callers")
    assert re.search(r"values: \[backend, litellm, trino\]", np)

def test_glue_backend_without_trino_refuses_to_render(tmp_path):
    err = render(tmp_path, extra_yaml="trino:\n  enabled: false\n", ok=False)
    assert "needs Trino" in err

def test_rendered_chart_has_no_athena_values(tmp_path):
    for values in ("values-prod-single.yaml", "values.yaml"):
        text = (CHART / values).read_text()
        assert "athena" not in text.lower()
```

Also edit `test_helm_sovereign_core.py:76` to drop `"FEATURE_ATHENA"` from the tuple, and in `test_helm_addon_defaults.py:484` change `"values-prod-single.yaml": frozenset()` to `frozenset({"trino"})` (update the comment block at lines 459-470 to say prod-single states trino true).

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_helm_trino_glue_catalog.py -q`
Expected: 5 failures (no Trino Deployment on prod-single; `ATHENA` present; `iceberg.catalog.type=glue` absent; render does not fail; `athena` present in values).

- [ ] **Step 3: Render the Glue catalog in `trino-deployment.yaml`**

In the `iceberg.properties` block, add a first branch before the Polaris one:

```
{{- if eq ((.Values.catalog | default dict).backend | default "polaris") "glue" }}
    iceberg.catalog.type=glue
    hive.metastore.glue.region={{ .Values.storage.region | default "us-east-1" }}
    hive.metastore.glue.default-warehouse-dir={{ (.Values.catalog | default dict).glueWarehouse }}
{{- else if (include "datapond.addonOn" (dict "root" $ "component" "polaris")) }}
```

(keep the existing `fs.native-s3.enabled`/`s3.region` lines that follow the branch). Confirm the three property names against the Trino 482 Iceberg connector page (`iceberg.catalog.type`, `hive.metastore.glue.region`, `hive.metastore.glue.default-warehouse-dir`) before committing; if 482 names them differently, use 482's names and update the test strings.

- [ ] **Step 4: Add the engine guard and the Trino IMDS allow**

Create `helm/datapond/templates/_engine.tpl`:

```
{{/* The AWS reference (catalog.backend=glue) has no serverless engine any more: SQL,
     catalog preview and dashboards run on the in-cluster Trino. A release whose stored
     values still say trino.enabled=false (every release installed before 2.4) would
     render a backend with no engine, so refuse instead of rendering it. */}}
{{- define "datapond.engineGuard" -}}
{{- if and (eq ((.Values.catalog | default dict).backend | default "polaris") "glue") (not (include "datapond.addonOn" (dict "root" $ "component" "trino"))) -}}
{{- fail "catalog.backend=glue needs Trino: set trino.enabled=true (the AWS reference runs Trino in-cluster since 2.4; Athena was removed)" -}}
{{- end -}}
{{- end -}}
```

Call `{{- include "datapond.engineGuard" . }}` at the top of `backend-deployment.yaml`. In `networkpolicy.yaml:66` add Trino to the allow-list: `values: [{{ .Values.backend.name }}, {{ (.Values.litellm).name | default "litellm" }}, {{ (.Values.trino).name | default "trino" }}]`. Update the comment above it (`networkpolicy.yaml:26-29`): the backend, LiteLLM and Trino reach AWS through the instance profile; Trino holds the whole node role, a documented limitation of single-node K3s.

- [ ] **Step 5: Collapse the engine env in `backend-deployment.yaml` and drop `ATHENA_*`**

Replace lines 417-428 so that `QUERY_ENGINE` is the literal `"trino"`, `RLS_DEFAULT_CATALOG` is `"iceberg"`, `RLS_DEFAULT_SCHEMA` is `"default"`, and the `FEATURE_ATHENA` env and its comment are deleted. Delete lines 448-453 (`ATHENA_OUTPUT_LOCATION`, `ATHENA_WORKGROUP`, `ATHENA_DATABASE`). Keep `FEATURE_GLUE`, `ICEBERG_CATALOG_BACKEND`, `GLUE_WAREHOUSE`.

- [ ] **Step 6: Values**

`values-prod-single.yaml`: comment at 47 becomes `# --- Catalog/query: AWS Glue catalog, Trino engine in-cluster. ---`; delete `athenaOutputLocation`, `athenaWorkgroup`, `athenaDatabase` and their comment; line 145 comment becomes `# --- Heavy analytics: not on the node. Trino is the query engine (small, in-cluster). ---`; `trino: { enabled: true }`. `values.yaml:109-116`: delete the four Athena lines. `values-foundation.yaml:6`: drop "Athena, " from the list. Header comments at `values-prod-single.yaml:4,20`: "Glue/Athena" → "Glue + Trino".

- [ ] **Step 7: Run the chart tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_helm_*.py -q`
Expected: all pass (including the two edited files). Also: `helm lint helm/datapond -f helm/datapond/values-prod-single.yaml` exits 0.

- [ ] **Step 8: Commit**

```bash
git add helm/datapond backend/tests/test_helm_trino_glue_catalog.py backend/tests/test_helm_sovereign_core.py backend/tests/test_helm_addon_defaults.py
git commit -m "helm: Trino over the Glue catalog on the AWS reference; engine env is Trino everywhere"
```

---

### Task 2: Backend — one engine; registry default is `iceberg` on glue too

**Files:**
- Modify: `backend/app/api/query_engine.py` (delete `AthenaEngine`, simplify `get_engine`, docstrings)
- Modify: `backend/app/api/ai_vectors.py:884-920` (`_read_iceberg_docs`)
- Modify: `backend/app/capabilities.py:36-40, 75-88, 121`
- Modify: `backend/app/service_registry.py:101-102`
- Modify: `backend/app/catalog_registry.py:211-219`
- Modify: `backend/app/api/catalog.py:116`, `backend/app/api/governance.py:444, 518`, `backend/app/api/queries.py:449`, `backend/app/api/table_resolver.py:6-7`, `backend/app/medallion_init.py:4`, `backend/app/metrics.py:5`, `backend/app/semantic/compile.py:48`, `backend/app/chat/analysis/query.py:143, 181`, `backend/app/chat/analysis/governance.py:257`, `backend/app/api/plan_review.py:1` (comments/docstrings only)
- Modify: `backend/requirements.txt:29` (remove `pyathena==3.9.0`)
- Test: `backend/tests/test_query_engine.py`, `test_capabilities.py`, `test_catalog_registry.py`, `test_service_registry.py`, `test_catalog_naming.py`, `test_ai_sql_dialect.py`, `test_ai_sql_catalogs.py`, `test_component_guard.py`, `test_governance_pii.py`, `test_rls_engine.py`, `test_table_resolver.py`, `test_semantic_compile.py`, `test_semantic_validate.py`, `test_semantic_service.py`, `test_semantic_routes.py`, `test_semantic_discovery.py`, `test_medallion_init.py`

**Interfaces:**
- Produces: `get_engine() -> TrinoEngine` always (env `QUERY_ENGINE` no longer read); `compute_capabilities(env)["query_engine"]` is `"trino"` or `"none"`, `["query_catalog"]` is `"iceberg"` or `""`; `env_default_entry()` names the glue default `TRINO_CATALOG or "iceberg"`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Rewrite the Athena tests as Trino-only tests (they fail first)**

`test_query_engine.py`: delete `test_athena_map_error`; `test_get_engine_selection` becomes

```python
def test_get_engine_is_always_trino(monkeypatch):
    monkeypatch.setenv("QUERY_ENGINE", "athena")   # a stale env value is ignored
    assert qe.get_engine().__class__.__name__ == "TrinoEngine"
    assert not hasattr(qe, "AthenaEngine")
```

`test_engine_props` asserts only the Trino properties. Fakes at lines 59 and 82 use `default_catalog = "iceberg"; rls_dialect = "trino"`. Add:

```python
def test_trino_connection_failure_maps_to_400_not_500():
    status, msg, code = qe.TrinoEngine().map_error(ConnectionRefusedError("connection refused"))
    assert (status, code) == ("error", 400) and "Trino is running" in msg
```

`test_capabilities.py:96-105`: replace both Athena tests with

```python
def test_glue_with_trino_enables_query_and_dashboards():
    caps = compute_capabilities(_env(TRINO="true", POLARIS="false", GLUE="true"))
    assert caps["query"] and caps["dashboards"]
    assert caps["query_engine"] == "trino" and caps["query_catalog"] == "iceberg"

def test_glue_without_trino_keeps_query_off():
    caps = compute_capabilities(_env(TRINO="false", POLARIS="false", GLUE="true"))
    assert caps["catalog"] and not caps["query"]
    assert caps["query_engine"] == "none" and caps["query_catalog"] == ""
```

and at lines 120-138 drop `QUERY_ENGINE`/`FEATURE_ATHENA` from the env fixture and assert `"trino"`.

`test_catalog_registry.py:31-40` becomes

```python
def test_glue_deployments_default_to_the_trino_catalog_name(monkeypatch):
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    e = env_default_entry()
    assert (e.name, e.engine_catalog, e.kind) == ("iceberg", "iceberg", "glue")
```

and lines 170/182 set `TRINO_CATALOG` instead of `QUERY_ENGINE=athena` where they need a non-default name. `test_catalog_naming.py:18`, `test_ai_sql_dialect.py:3-5` (assert `"Trino" in system and "iceberg" in system`), `test_ai_sql_catalogs.py:49` likewise. `test_service_registry.py:14,50-57`: remove `"Amazon Athena"` from the expected set and the `FEATURE_ATHENA` env. `test_component_guard.py:34`: drop the `delenv`. `test_governance_pii.py:4`: docstring. `test_medallion_init.py`: add, if absent,

```python
def test_init_is_best_effort_when_trino_is_unreachable(monkeypatch, caplog):
    monkeypatch.setenv("FEATURE_TRINO", "true")
    monkeypatch.setenv("TRINO_SERVICE_HOST", "127.0.0.1"); monkeypatch.setenv("TRINO_SERVICE_PORT", "9")
    assert init_medallion_namespaces(logging.getLogger("t")) is True   # attempted, did not raise
```

Dialect strings: in `test_rls_engine.py`, `test_table_resolver.py`, `test_semantic_compile.py`, `test_semantic_validate.py`, `test_semantic_service.py:76`, `test_semantic_routes.py:208,449`, `test_semantic_discovery.py:125` replace `"athena"` with `"trino"`; delete `test_enforce_athena_dialect_wraps_table` and `test_enforce_mask_survives_athena_dialect`; the `parametrize("dialect", ["trino", "athena"])` at `test_rls_engine.py:267` becomes `["trino"]`. `engine_catalog="AwsDataCatalog"` fixtures in `test_semantic_compile.py:22,175` stay (any name is valid there).

- [ ] **Step 2: Run the touched tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_query_engine.py tests/test_capabilities.py tests/test_catalog_registry.py tests/test_service_registry.py tests/test_catalog_naming.py tests/test_ai_sql_dialect.py tests/test_ai_sql_catalogs.py -q`
Expected: failures on `AthenaEngine` still present, `query_engine == "athena"`, registry default `AwsDataCatalog`, "Amazon Athena" still listed.

- [ ] **Step 3: Remove `AthenaEngine` from `query_engine.py`**

Delete the class and the `os` import if unused; `def get_engine() -> TrinoEngine: return TrinoEngine()`; module docstring: "One engine: Trino (in-cluster on every profile, including the AWS reference over the Glue catalog)". Drop "Trino and Athena (engine v3)" wording.

- [ ] **Step 4: `_read_iceberg_docs` uses only the Trino path**

Remove the `AthenaEngine` import and the `isinstance` branch; keep the `trino_util.trino_conn(timeout=60)` path and the `prefix` computation (`eng.ai_table_prefix` for the default entry, `safe_identifier(entry.engine_catalog)` otherwise). Docstring: drop the Athena sentences.

- [ ] **Step 5: Capabilities, service registry, registry default**

`capabilities.py`: `"query": ("TRINO",)`, `"dashboards": ("TRINO",)`; delete the `athena` variable; `query_engine = "trino" if trino else "none"`; `query_catalog = "iceberg" if trino else ""`; comment at 121 `# "trino" | "none"`. `service_registry.py`: delete the two Athena lines. `catalog_registry.env_default_entry()`: remove the engine derivation; `name = (os.getenv("TRINO_CATALOG") or "iceberg").strip() or "iceberg"` for both backends; update the comment. Fix the comment-only sites listed in Files (say "Glue catalog + Trino engine"; `chat/analysis/governance.py:257` now says Helm sets `RLS_DEFAULT_CATALOG=iceberg`). Remove `pyathena` from `requirements.txt`.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance`
Expected: all pass. Then: `grep -rn -i "athena\|AwsDataCatalog" backend/app | grep -v __pycache__` prints nothing except `backend/app/migrations/versions/0025_*` (added in Task 3; empty at this point).

- [ ] **Step 7: Commit**

```bash
git add backend/app backend/requirements.txt backend/tests
git commit -m "backend: one query engine (Trino); drop the Athena engine, capability and env"
```

---

### Task 3: `AwsDataCatalog` as an alias — data migration + canonical policy matching

**Files:**
- Create: `backend/migrations/versions/0025_glue_engine_catalog_trino.py`
- Modify: `backend/app/rls/engine.py:235-236` (`_policy_key`)
- Test: `backend/tests/test_rls_engine.py`, `backend/tests/test_catalog_registry.py`, `backend/tests/test_semantic_service.py`

**Interfaces:**
- Consumes: `catalog_registry.resolve(name) -> CatalogEntry` (raises `UnknownCatalog`), `catalog_registry.set_entries(...)` for tests.
- Produces: `_policy_key(p) -> str` returns `<engine_catalog>.<schema>.<table>` lowercased, resolving `p.catalog` through the registry, falling back to the raw value when unknown.

- [ ] **Step 1: Write the failing tests**

`test_rls_engine.py`:

```python
def test_policy_stored_under_the_registry_alias_matches_the_engine_name(monkeypatch):
    from app import catalog_registry as reg
    reg.set_entries([reg.CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True)])
    try:
        pol = orders_region_policy(); pol.catalog = "AwsDataCatalog"
        for sql in ("SELECT * FROM iceberg.default.orders", "SELECT * FROM orders"):
            out = enforce(sql, analyst(), [pol], dialect="trino")
            assert "region" in out.sql.lower() and out.applied_policy_ids
    finally:
        reg.reset()
```

(adapt `orders_region_policy()`/`analyst()` to the file's existing fixtures; the policy fixture's catalog must be settable — construct a copy if it is frozen). `test_catalog_registry.py`:

```python
def test_alias_resolves_to_the_engine_name():
    set_entries([CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True)])
    try:
        assert resolve("AwsDataCatalog").engine_catalog == "iceberg"
        assert resolve("iceberg").name == "AwsDataCatalog"
        assert default_entry().engine_catalog == "iceberg"
    finally:
        reset()
```

`test_semantic_service.py`: a metric version with `catalog="AwsDataCatalog"` under the same registry entries compiles to SQL containing `iceberg.` and not `AwsDataCatalog.` (follow the file's existing compile fixture).

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rls_engine.py tests/test_catalog_registry.py tests/test_semantic_service.py -q -k "alias or registry_alias"`
Expected: the RLS test fails (policy key `awsdatacatalog.default.orders` ≠ `iceberg.default.orders`); the other two pass already (resolve/compile go through the registry) — keep them as regression pins.

- [ ] **Step 3: Canonicalise `_policy_key`**

```python
def _policy_key(p) -> str:
    cat = str(p.catalog or "")
    try:
        from app.catalog_registry import resolve
        cat = resolve(cat).engine_catalog if cat else cat
    except Exception:
        pass
    return f"{cat}.{p.schema}.{p.table}".lower()
```

- [ ] **Step 4: Write the migration**

`0025_glue_engine_catalog_trino.py` (no `.sql`; it needs env): `revision = "0025_glue_engine_catalog_trino"`, `down_revision = "0024_ai_budget_caps"`. `upgrade()` executes, with `name = os.getenv("TRINO_CATALOG", "iceberg").strip() or "iceberg"`:

```sql
UPDATE public.data_catalogs SET engine_catalog = :name
 WHERE kind = 'glue' AND engine_catalog = 'AwsDataCatalog'
```

via `op.get_bind().execute(sa.text(...), {"name": name})`. `downgrade()` reverses with the same WHERE on `engine_catalog = :name`. Module docstring: the registry name stays `AwsDataCatalog` on purpose (stored metrics, joins, chunk sources and policies carry it; `resolve()` accepts either name).

- [ ] **Step 5: Run the suite and the migration test harness**

Run: `cd backend && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance`
Expected: pass. If `tests/test_helm_migration_ordering.py` or a migrations test enumerates revisions, it must see 0025 chained after 0024.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rls/engine.py backend/migrations/versions/0025_glue_engine_catalog_trino.py backend/tests
git commit -m "catalog: AwsDataCatalog stays a registry alias; glue default's engine name becomes iceberg (0025)"
```

---

### Task 4: Frontend — no Athena branch or copy

**Files:**
- Modify: `frontend/app/query/page.tsx:141-147, 415`
- Modify: `frontend/lib/product-profile.ts:19`
- Modify: `frontend/app/services/page.tsx:120`
- Modify: `frontend/app/knowledge/page.tsx:664`, `frontend/app/governance/page.tsx:313` (comments)
- Modify: `frontend/app/help/catalog/page.tsx:270, 328`, `frontend/app/help/sql-lab/page.tsx:260`, `frontend/components/settings/data-catalogs.tsx:329`, `frontend/components/docs/docs-index.tsx:73, 95`, `frontend/app/docs/[slug]/page.tsx:64, 76, 89, 96, 182, 253`, `frontend/lib/chart-recommend.ts:394` (copy)
- Test: `frontend/lib/*.test.ts` (existing `node --test`), `npm run lint`, `npx tsc --noEmit`

**Interfaces:**
- Consumes: `caps.query_engine ∈ {"trino","none"}`, `caps.catalog_backend`, `caps.query_catalog` from Task 2.

- [ ] **Step 1: If `frontend/lib/product-profile.test.ts` exists, add the failing assertion; otherwise create it**

```ts
test("glue catalog without an athena engine still reads as the AWS reference", () => {
  const p = getProductProfile({ _loaded: true, catalog_backend: "glue", query_engine: "trino" } as any)
  assert.equal(p.id, "aws-managed")
})
```

- [ ] **Step 2: Run** `cd frontend && npm test` — Expected: the new test passes already if `catalog_backend` alone decides; keep it as the pin. (It fails only if Step 3 is done wrong.)

- [ ] **Step 3: Edit**

`product-profile.ts:19`: `const hasAwsAnalytics = caps.catalog_backend === "glue"`. `query/page.tsx`: `const engineName = "Trino"`, `const svcName = "trino"`, delete the Athena sentences in the two comments (141-147, 415). `services/page.tsx:120`: delete the `"Amazon Athena"` entry. Copy edits: "Glue/Athena" → "Glue + Trino"; "Athena or Trino" → "Trino"; `help/sql-lab:260` → "DataPond uses Trino SQL (ANSI SQL compatible) for OLAP queries on every profile."; `data-catalogs.tsx:329` → "The name the query engine knows it by (Trino catalog)."; `docs/[slug]/page.tsx:89` keeps "Athena" in the *not automatically created* list (it is a statement about what is not provisioned); `chart-recommend.ts:394` → "Trino returns decimals as strings …" only if that is true for the trino client, else delete the comment.

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test`
Expected: lint 0 errors, tsc clean, all tests pass. `grep -rn -i athena frontend/app frontend/components frontend/lib` prints only `docs/[slug]/page.tsx:89`.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "frontend: the query engine is Trino on every profile; drop the Athena branch and copy"
```

---

### Task 5: Terraform — no Athena permissions, alarm or dashboard widgets

**Files:**
- Modify: `terraform/iam.tf:79-86` (delete the `AthenaQuery` statement)
- Modify: `terraform/cloudwatch.tf:3, 18-22, 51, 80-108, 110-128` (variable, local, two dashboard widgets, alarm)
- Modify: `terraform/ec2.tf:93`, `terraform/variables.tf:11` (comments)
- Test: `terraform validate`, `terraform plan`

- [ ] **Step 1: Edit** — remove the `AthenaQuery` statement; delete `variable "athena_daily_scan_alarm_tb"`, `local.athena_scan_th`, the "Athena queries" and "Athena scan cost" dashboard widgets, and `aws_cloudwatch_metric_alarm.athena_daily_scan`. Header comment line 3: drop "and surfaces Athena spend as". Comments: `ec2.tf:93` "S3, Bedrock and Glue"; `variables.tf:11` drop `catalog.athenaOutputLocation`.

- [ ] **Step 2: Validate and plan (read-only)**

Run: `terraform -chdir=terraform init -input=false >/dev/null && terraform -chdir=terraform validate && terraform -chdir=terraform plan -var-file=live.tfvars -var db_master_password=unused -lock=false -input=false`
Expected: validate OK; plan shows exactly `aws_iam_role_policy.node` (or the policy resource that carries `GlueDataCatalog`) **update in-place**, `aws_cloudwatch_dashboard.datapond` update in-place, `aws_cloudwatch_metric_alarm.athena_daily_scan[0]` destroy. If `aws_instance.node` or `aws_route53_record.*` appear in the plan, STOP: do not apply, report.

- [ ] **Step 3: Commit (apply happens in Task 7, Step 6)**

```bash
git add terraform
git commit -m "terraform: drop Athena IAM, scan alarm and dashboard widgets"
```

---

### Task 6: Docs — Glue catalog, Trino engine

**Files:**
- Modify: `CLAUDE.md:24, 49, 52, 84, 94` and the "Live AWS deployment" blockquote; `README.md:18, 70, 82, 154`; `docs/README.md`; `docs/ARCHITECTURE.md`; `docs/DEPLOYMENT_PROFILES.md`; `docs/DEPLOY_SINGLE_NODE.md:7, 329, 351` (+ a new §"Cutover from Athena (2.4)" pointing to UPGRADING); `docs/PORTABILITY.md`; `docs/PRODUCT_CONCEPT.md`; `docs/FOUNDATION_PROFILE.md`; `docs/RLS_DESIGN.md`; `docs/AWS_MVP_RUNBOOK.md`; `docs/DEMO_SCRIPT.md`; `docs/UPGRADING.md`; `docs/DISASTER_RECOVERY.md` (§D step 3: the Trino pod is part of the rebuild; first install needs `trino.enabled=true` from the profile)
- Test: `grep`

- [ ] **Step 1: Edit by rule** — every "Glue/Athena", "Glue + Athena", "Athena/Glue" in the live docs becomes "Glue catalog + Trino" (or "Glue + Trino"); every "Athena or Trino" becomes "Trino"; the two `helm` commands in `DEPLOY_SINGLE_NODE.md` and the one in `CLAUDE.md` lose the `--set-string catalog.athenaOutputLocation=…` line. `CLAUDE.md` Key positioning line 24: "S3, Aurora, Glue, and Bedrock where the selected profile actually enables them; Trino runs in-cluster on every profile". `UPGRADING.md`: a "2.4 — Athena removed" entry with: `catalog.athena*` values ignored and removed; `QUERY_ENGINE` is always Trino; the AWS reference must set `trino.enabled=true` (the chart refuses to render otherwise); the release's stored values must be re-supplied once (`helm get values` → strip `trino`/`catalog.athena*` → `helm upgrade --reset-values -f values-prod-single.yaml -f <overrides>`); migration 0025 changes only `data_catalogs.engine_catalog`; `AwsDataCatalog` keeps working as a name. `RLS_DESIGN.md`: `_policy_key` canonicalises through the registry; `RLS_DEFAULT_CATALOG=iceberg` everywhere. `DISASTER_RECOVERY.md` RTO row: "+ Trino pod".

- [ ] **Step 2: Verify**

Run: `grep -rn -i athena README.md CLAUDE.md docs/*.md | grep -v -E "MARKET_REVIEW|POSITIONING_REVIEW|PRODUCTIZATION_READINESS|UTILIZATION_PERSONA|OPERATIONS_PAUSE|ONTOLOGY_GRAPHRAG|DESIGN_PARTNER|DATA_RESIDENCY|CONCEPT_RECONFIRMATION"`
Expected: only `UPGRADING.md` (the removal note), `DEPLOYMENT_PROFILES.md`/`FOUNDATION_PROFILE.md` lines that list Athena among services *not* provisioned, and `DEPLOY_SINGLE_NODE.md`'s cutover section.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md docs
git commit -m "docs: the AWS reference is Glue catalog + in-cluster Trino; Athena removed (2.4)"
```

---

### Task 7: Live cutover, merge, Terraform apply

Operator steps on the live stack (account 588738574974, us-east-1, node `i-01c99cc78436e765e`, release `datapond` in ns `datapond`). Run them in this order; each has a check.

**Files:** none in the repo beyond what Tasks 1–6 committed. Scratch files go in the session scratchpad and are deleted after.

- [ ] **Step 1: Open the PR and get CI green** — branch `ops/trino-replaces-athena`, PR titled "Trino replaces Athena on the AWS reference (Phase 1)". Expected: CI 10/10 green (Trivy, chart renders for all profiles, backend, frontend, kind). Do not merge yet.

- [ ] **Step 2: Build and push the branch images from `main`'s workflow**

Run: `gh workflow run deploy-aws.yml --ref main -f ref=ops/trino-replaces-athena` and watch it. Expected: build-push succeeds; the roll step upgrades the release with the branch chart but **Trino does not start** (stored values say `trino.enabled=false`) — and because of the Task 1 guard, `helm upgrade` in `deploy-node-helm.sh` **fails on render** with "catalog.backend=glue needs Trino". That failure is expected here and is the reason for Step 3; the previous release revision stays live. Note the pushed tag `<TAG>` from the job log.

- [ ] **Step 3: One-time manual upgrade re-supplying the profile values (via SSM, as root on the node)**

```bash
helm -n datapond get values datapond -o yaml > /tmp/live.yaml
python3 - <<'PY'
import yaml; v=yaml.safe_load(open('/tmp/live.yaml'))
v.pop('trino', None)
for k in ('athenaOutputLocation','athenaWorkgroup','athenaDatabase'): v.get('catalog',{}).pop(k, None)
yaml.safe_dump(v, open('/tmp/overrides.yaml','w'))
PY
aws s3 ls s3://datapond-iceberg/deploy/            # the newest .tgz is the bundle Step 2 staged
aws s3 cp s3://datapond-iceberg/deploy/<newest>.tgz /tmp/chart.tgz && tar xzf /tmp/chart.tgz -C /tmp
helm -n datapond upgrade datapond /tmp/helm/datapond --reset-values \
  -f /tmp/helm/datapond/values-prod-single.yaml -f /tmp/overrides.yaml \
  --set-string backend.image.tag=<TAG> --set-string frontend.image.tag=<TAG> --wait --timeout 420s
rm -f /tmp/live.yaml /tmp/overrides.yaml
```

Expected: `trino` Deployment Ready within ~90 s; backend rolled; `helm get values` now contains `trino: {enabled: true}` and no `athena` key (so `deploy-node-helm.sh`'s `--reset-then-reuse-values` keeps Trino on from here). `/tmp/live.yaml` and `/tmp/overrides.yaml` contain the stored `postgres.auth.password`; they are root-only on the node and the `rm` above is not optional.

- [ ] **Step 4: Verify on the node and over HTTPS**

- `kubectl -n datapond get pods` — trino 1/1, backend 2/2; `kubectl top nodes` memory < 60 %.
- `kubectl -n datapond logs deploy/backend | grep -E "Medallion|0025"` — migration 0025 applied; medallion init created `iceberg.raw/refined/serving` (new Glue databases `raw`, `refined`, `serving` — expected side effect; `aws glue get-databases`).
- Backend DB: `SELECT name, engine_catalog FROM data_catalogs` → `AwsDataCatalog | iceberg`.
- `GET /api/capabilities` (admin token): `query=true`, `dashboards=true`, `query_engine=trino`, `query_catalog=iceberg`.
- `POST /api/queries/execute` with `SELECT count(*) FROM default.<a Glue table>` → 200 rows; with `SELECT 1 FROM AwsDataCatalog.default.<table> LIMIT 1` → 200 (alias accepted by the resolver).
- Catalog page preview for one Glue table → rows. One metric via `POST /api/mcp` `metric_query` (any existing metric) → result.
- Knowledge: run one catalog-bridge refresh for a table-sourced collection → chunk count unchanged (replace semantics by `source_group`).
- `/api/governance/rls/coverage` loads; PII report loads (Glue metadata path unchanged).
- Services page lists Trino, no "Amazon Athena".

If any check fails: `helm -n datapond rollback datapond <previous revision>` and report; do not merge.

- [ ] **Step 5: Merge and deploy from main**

Merge the PR (squash or merge per repo habit; the commit order inside the branch is already chart → alias → removal). Run `gh workflow run deploy-aws.yml --ref main -f ref=main`; Expected: success end-to-end (`deploy-node-helm.sh` now renders because stored values carry `trino.enabled=true`). Re-run the three HTTP checks from Step 4.

- [ ] **Step 6: Terraform apply (IAM/alarm removal)**

Run: `terraform -chdir=terraform apply -var-file=live.tfvars -var db_master_password=<from the state backup, never echoed> -input=false` after re-reading the plan: exactly the three changes from Task 5 Step 2. Expected: apply complete, 0 added / 2 changed / 1 destroyed. `aws athena list-query-executions --work-group primary` stays at the old count afterwards (nothing calls Athena any more).

- [ ] **Step 7: Record**

Update `CLAUDE.md`'s "Live AWS deployment" blockquote (date, "Trino in-cluster over Glue; Athena removed 2026-11-xx") in a follow-up commit on main if Task 6 wrote it before the actual cutover date; update the session memory handoff.
