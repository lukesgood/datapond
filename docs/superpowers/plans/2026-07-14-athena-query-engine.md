# Athena Query Engine Implementation Plan (B2 · Slice 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute user + AI SQL over Glue/Iceberg via Amazon Athena (pyathena), behind an engine abstraction, re-enabling the query + dashboards capabilities without changing on-prem/Trino profiles.

**Architecture:** A new `query_engine.py` defines an `Engine` protocol with `TrinoEngine` (wraps today's code) and `AthenaEngine` (pyathena DBAPI). `queries.py`/`ai_sql.py`/`rls/engine.py` delegate dialect + execution + error-mapping to the active engine, selected by `QUERY_ENGINE` (derived in Helm from `catalog.backend`). Dashboards ride `/queries/execute` unchanged.

**Tech Stack:** Python 3.11, FastAPI, pyathena (Athena DBAPI), boto3, sqlglot 26.33.0, AWS Athena + Glue + S3, pytest. Spec: `docs/superpowers/specs/2026-07-14-athena-query-engine-design.md`.

## Global Constraints

- **pyathena** DBAPI for Athena (preserves `execute/fetchall/description`); add to `requirements.txt`, verify it resolves against the boto3/botocore already installed.
- `QUERY_ENGINE` env (`athena`|`trino`, default `trino`) selects the engine; on-prem/Trino profiles unchanged.
- Engine selection derived in Helm from `catalog.backend` (glue → athena), mirroring Slice 1's `FEATURE_GLUE`. `capabilities.query`/`dashboards` = `trino or athena`; `FEATURE_ATHENA` default FALSE.
- RLS `enforce(dialect=...)` defaults `"trino"`; Athena passes `"athena"`. Trino ACL file (Layer 2) not generated on Athena.
- Athena needs `ATHENA_OUTPUT_LOCATION` (S3 staging), `ATHENA_WORKGROUP` (default `primary`), `ATHENA_DATABASE` (default Glue database). Athena IAM: StartQueryExecution/GetQueryExecution/GetQueryResults/StopQueryExecution/GetWorkGroup.
- Tests are pure-unit (repo style); pyathena/boto3 mocked. Real Athena execution is **live-validated only** (mirrors Slice 1).
- Run tests: `cd backend && python -m pytest tests/test_query_engine.py tests/test_capabilities.py tests/test_rls_engine.py -v`.

---

## File Structure

- `backend/app/api/query_engine.py` (create) — `Engine` protocol, `TrinoEngine`, `AthenaEngine`, `get_engine()`.
- `backend/app/api/queries.py` (modify) — `execute_query` delegates to the engine.
- `backend/app/rls/engine.py` (modify) — `enforce(dialect=...)`; env-overridable default catalog.
- `backend/app/api/ai_sql.py` (modify) — engine-aware prompt; schema context via Slice-1 CatalogReader.
- `backend/app/capabilities.py` (modify) — `athena` → query/dashboards.
- `helm/datapond/templates/backend-deployment.yaml`, `values.yaml`, `values-prod-single.yaml` (modify) — FEATURE_ATHENA/QUERY_ENGINE/ATHENA_* env.
- `terraform/iam.tf` (modify) — Athena IAM.
- `backend/requirements.txt` (modify) — pyathena.
- Tests: `backend/tests/test_query_engine.py` (create), `test_capabilities.py` (extend), `test_rls_engine.py` (extend).

---

## Task 1: Engine abstraction (query_engine.py)

**Files:**
- Create: `backend/app/api/query_engine.py`
- Test: `backend/tests/test_query_engine.py` (create)

**Interfaces:**
- Produces: `get_engine() -> Engine`; `Engine` with `execute(sql, user) -> (rows, columns)`, `map_error(exc) -> (status, detail, http_code)`, attrs `default_catalog`, `default_schema`, `rls_dialect`, `ai_dialect_prompt`, `ai_table_prefix`. Classes `TrinoEngine`, `AthenaEngine`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_query_engine.py`:

```python
def test_get_engine_selection(monkeypatch):
    import app.api.query_engine as qe
    monkeypatch.setenv("QUERY_ENGINE", "athena")
    assert qe.get_engine().__class__.__name__ == "AthenaEngine"
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    assert qe.get_engine().__class__.__name__ == "TrinoEngine"
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    assert qe.get_engine().__class__.__name__ == "TrinoEngine"  # default


def test_engine_props():
    import app.api.query_engine as qe
    t, a = qe.TrinoEngine(), qe.AthenaEngine()
    assert t.rls_dialect == "trino" and a.rls_dialect == "athena"
    assert t.default_catalog == "iceberg" and a.default_catalog == "AwsDataCatalog"
    assert "Trino" in t.ai_dialect_prompt and "Athena" in a.ai_dialect_prompt
    assert t.ai_table_prefix == "iceberg" and a.ai_table_prefix == "AwsDataCatalog"


def test_trino_map_error():
    import app.api.query_engine as qe
    t = qe.TrinoEngine()
    st, detail, code = t.map_error(Exception('...message="Table x not found", query_id=1 TABLE_NOT_FOUND'))
    assert code == 400 and "Table not found" in detail
    st2, d2, c2 = t.map_error(Exception("query exceeded timeout"))
    assert st2 == "timeout" and c2 == 504


def test_athena_map_error():
    import app.api.query_engine as qe
    a = qe.AthenaEngine()
    st, detail, code = a.map_error(Exception("SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved"))
    assert code == 400 and ("Syntax" in detail or "column" in detail.lower())
    st2, d2, c2 = a.map_error(Exception("TABLE_NOT_FOUND: Table awsdatacatalog.db.t does not exist"))
    assert c2 in (400, 404) and "not found" in d2.lower()
    st3, d3, c3 = a.map_error(Exception("AccessDeniedException: not authorized"))
    assert c3 == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_query_engine.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — create `backend/app/api/query_engine.py`:

```python
"""Query-engine abstraction. Selected by QUERY_ENGINE (athena|trino, default trino).
Isolates dialect, execution, and error-mapping so queries.py / ai_sql.py / rls stay
engine-agnostic. TrinoEngine wraps the existing self-hosted path; AthenaEngine uses
pyathena (serverless, AWS-native)."""
import os
import re


def _clean_trino_msg(msg: str) -> str:
    if 'message="' in msg:
        try:
            return msg.split('message="')[1].split('"')[0]
        except Exception:
            return msg
    return msg


class TrinoEngine:
    default_catalog = "iceberg"
    default_schema = "default"
    rls_dialect = "trino"
    ai_dialect_prompt = "The query engine is Trino. Tables are Apache Iceberg format."
    ai_table_prefix = "iceberg"

    def execute(self, sql, user):
        from app.api.queries import get_trino_connection
        conn = get_trino_connection(user)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.close(); conn.close()
        return rows, cols

    def map_error(self, exc):
        msg = str(exc)
        clean = _clean_trino_msg(msg)
        low = msg.lower()
        if "SYNTAX_ERROR" in msg or "syntax error" in low:
            return "error", f"Syntax error: {clean}", 400
        if "TABLE_NOT_FOUND" in msg or ("table" in low and "not found" in low):
            return "error", f"Table not found: {clean}", 400
        if "SCHEMA_NOT_FOUND" in msg or ("schema" in low and "not found" in low):
            return "error", f"Schema not found: {clean}", 400
        if "CATALOG_NOT_FOUND" in msg:
            return "error", f"Catalog not found: {clean}", 400
        if "PERMISSION_DENIED" in msg:
            return "error", f"Permission denied: {clean}", 403
        if "timeout" in low:
            return "timeout", "Query timed out (30s limit). Try adding a LIMIT clause.", 504
        if "connect" in low or "connection" in low:
            return "error", "Cannot connect to query engine. Check if Trino is running.", 400
        return "error", clean if clean != msg else f"Query failed: {clean}", 400


class AthenaEngine:
    default_catalog = "AwsDataCatalog"
    rls_dialect = "athena"
    ai_dialect_prompt = ("The query engine is Amazon Athena (Trino/Presto SQL, engine v3). "
                         "Tables are Apache Iceberg registered in AWS Glue.")
    ai_table_prefix = "AwsDataCatalog"

    @property
    def default_schema(self):
        return os.getenv("ATHENA_DATABASE", "default")

    def execute(self, sql, user):
        from pyathena import connect
        conn = connect(
            s3_staging_dir=os.getenv("ATHENA_OUTPUT_LOCATION", ""),
            region_name=os.getenv("S3_REGION", "us-east-1"),
            work_group=os.getenv("ATHENA_WORKGROUP", "primary"),
            schema_name=os.getenv("ATHENA_DATABASE", "default"),
            catalog_name="AwsDataCatalog",
        )
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.close(); conn.close()
        return rows, cols

    def map_error(self, exc):
        msg = str(exc)
        low = msg.lower()
        if "accessdenied" in low or "not authorized" in low:
            return "error", f"Access denied: {msg[:300]}", 403
        if "syntax_error" in low or "cannot be resolved" in low or "mismatched input" in low:
            return "error", f"Syntax error: {msg[:300]}", 400
        if "table_not_found" in low or ("does not exist" in low and "table" in low):
            return "error", f"Table not found: {msg[:300]}", 404
        if "schema_not_found" in low or "database does not exist" in low:
            return "error", f"Schema not found: {msg[:300]}", 400
        if "timeout" in low or "timed out" in low:
            return "timeout", "Query timed out. Try adding a LIMIT clause or narrowing the scan.", 504
        if "outputlocation" in low or "s3" in low and "staging" in low:
            return "error", "Athena result location not configured (ATHENA_OUTPUT_LOCATION).", 400
        return "error", f"Query failed: {msg[:300]}", 400


def get_engine():
    backend = os.getenv("QUERY_ENGINE", "trino").strip().lower()
    return AthenaEngine() if backend == "athena" else TrinoEngine()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_query_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Verify pyathena import under the pin** (CI/py3.11): `python -c "import pyathena; print(pyathena.__version__)"` after adding the dep in Task 5. Record. If pyathena isn't installed yet, this step moves to Task 5's verification.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/query_engine.py backend/tests/test_query_engine.py
git commit -m "feat(query): Engine abstraction (Trino + Athena via pyathena)"
```

---

## Task 2: queries.py delegates to the engine

**Files:**
- Modify: `backend/app/api/queries.py` (`execute_query` 148-297)
- Test: `backend/tests/test_query_engine.py` (extend)

**Interfaces:**
- Consumes: `get_engine()` (Task 1), `enforce(..., dialect=...)` (Task 3).
- Produces: `execute_query` runs via the active engine; QueryHistory `catalog`/`schema` from engine defaults.

- [ ] **Step 1: Write the failing test** (execute_query uses the engine) — extend `test_query_engine.py`:

```python
def test_execute_query_uses_engine(monkeypatch):
    import asyncio, app.api.queries as q

    class _Eng:
        default_catalog = "AwsDataCatalog"; default_schema = "db"; rls_dialect = "athena"
        def execute(self, sql, user): return [[1, "a"]], ["id", "name"]
        def map_error(self, exc): return ("error", "x", 400)
    monkeypatch.setattr(q, "get_engine", lambda: _Eng())
    monkeypatch.setattr(q, "RLS_ENABLED", False)

    class _Req: query = "select 1"; save_history = False
    res = asyncio.get_event_loop().run_until_complete(q.execute_query(_Req(), db=None, user=None))
    assert res.columns == ["id", "name"] and res.rows == [[1, "a"]] and res.row_count == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_query_engine.py::test_execute_query_uses_engine -v`
Expected: FAIL (still uses `get_trino_connection`/Trino taxonomy directly).

- [ ] **Step 3: Implement.** In `queries.py`, add `from app.api.query_engine import get_engine` at the top. Replace the RLS + execution + error section (lines 172-270) so it uses the engine:

- RLS block: pass the engine's dialect —
```python
    engine = get_engine()
    trino_user = TRINO_USER
    if RLS_ENABLED and _RLS_IMPORTS_OK:
        if not user:
            raise HTTPException(status_code=401, detail="RLS 활성화됨 — 인증이 필요합니다")
        try:
            ctx = await rls_loader.load_user_context(user)
            policies = await rls_loader.load_policies()
            masks = await rls_loader.load_masks()
            result = enforce(effective_query, ctx, policies, masks, dialect=engine.rls_dialect)
            effective_query = result.sql
            trino_user = ctx.username or TRINO_USER
        except RlsDenied as d:
            await rls_loader.audit_denial(ctx, request.query, d.message, d.table)
            raise HTTPException(status_code=403, detail=f"RLS 차단: {d.message}")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[rls] enforcement error, blocking: {e}")
            raise HTTPException(status_code=403, detail="RLS 적용 중 오류로 쿼리가 차단되었습니다")
```

- `_run_blocking` → engine:
```python
    def _run_blocking():
        return engine.execute(safe_query, trino_user)
```

- Error handling block (replace the whole Trino taxonomy 220-270) with:
```python
    except Exception as e:
        error_msg = str(e)
        status, error_detail, http_code = engine.map_error(e)
        if request.save_history:
            try:
                history = QueryHistory(
                    user_id=MOCK_USER_ID, query_text=request.query,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    rows_returned=0, status=status, error_message=error_msg,
                    catalog=engine.default_catalog, schema=engine.default_schema)
                db.add(history); db.commit()
            except Exception as db_err:
                print(f"Failed to save query history: {db_err}")
        raise HTTPException(status_code=http_code, detail=error_detail)
```

- Success-path history: change `catalog=TRINO_CATALOG, schema=TRINO_SCHEMA` (283-284) to `catalog=engine.default_catalog, schema=engine.default_schema`.

(`get_trino_connection`, `TRINO_*` constants, and `add_limit_to_query` stay — `TrinoEngine.execute` uses `get_trino_connection`; `add_limit_to_query` is engine-neutral.)

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && python -m pytest tests/test_query_engine.py -v && python -c "import app.api.queries"`
Expected: PASS + clean import.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/queries.py backend/tests/test_query_engine.py
git commit -m "feat(query): execute_query delegates to the active engine"
```

---

## Task 3: RLS dialect parameter

**Files:**
- Modify: `backend/app/rls/engine.py` (`enforce` 207-214; sqlglot calls 228, ~288, ~327; `DEFAULT_CATALOG` 101)
- Test: `backend/tests/test_rls_engine.py` (extend)

**Interfaces:**
- Consumes: called by queries.py Task 2 with `dialect=engine.rls_dialect`.
- Produces: `enforce(sql, user, policies, masks=(), *, sensitive_block=False, dialect="trino")`.

- [ ] **Step 1: Write the failing test** — extend `test_rls_engine.py` (match the existing test's UserContext/policy construction; here is a self-contained shape):

```python
def test_enforce_accepts_athena_dialect():
    from app.rls.engine import enforce
    import inspect
    assert "dialect" in inspect.signature(enforce).parameters
    # A no-policy enforce is a pass-through and must not raise under athena dialect.
    from app.rls.models import UserContext
    ctx = UserContext(username="u", roles=[], attributes={}, is_admin=False)
    res = enforce("SELECT 1", ctx, [], [], dialect="athena")
    assert "1" in res.sql
```

(If `UserContext`'s constructor differs, mirror the existing `test_rls_engine.py` construction — this test only needs a no-policy pass-through under `dialect="athena"`.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_rls_engine.py::test_enforce_accepts_athena_dialect -v`
Expected: FAIL (`enforce` has no `dialect` kwarg).

- [ ] **Step 3: Implement.** Change the `enforce` signature (207-214):

```python
def enforce(
    sql: str,
    user: UserContext,
    policies: Sequence[RlsPolicy],
    masks: Sequence[MaskPolicy] = (),
    *,
    sensitive_block: bool = False,
    dialect: str = "trino",
) -> EnforceResult:
```

Thread `dialect` into every sqlglot call: `sqlglot.parse(sql, read=dialect)` (228), the emit `.sql(dialect=dialect)` (~288-289), and `sqlglot.parse_one(select_sql, read=dialect)` (~327). Make the default catalog env-overridable so Athena can re-point it (line 101):

```python
DEFAULT_CATALOG = os.getenv("RLS_DEFAULT_CATALOG", os.getenv("TRINO_CATALOG", "iceberg"))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && python -m pytest tests/test_rls_engine.py -v`
Expected: PASS (existing Trino tests still green — default dialect is `"trino"`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/rls/engine.py backend/tests/test_rls_engine.py
git commit -m "feat(rls): enforce() takes a dialect param (trino|athena)"
```

---

## Task 4: AI-SQL engine-aware (prompt + schema context)

**Files:**
- Modify: `backend/app/api/ai_sql.py` (`_build_messages` 143-159; `_fetch_schema_context` 65-98)
- Test: `backend/tests/test_query_engine.py` (extend) or a new `tests/test_ai_sql_dialect.py`

**Interfaces:**
- Consumes: `get_engine()` (Task 1), `catalog_backend.get_catalog_reader()` (Slice 1).
- Produces: prompts referencing the active engine's dialect + table prefix; schema context sourced from the CatalogReader.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_ai_sql_dialect.py`:

```python
def test_build_messages_uses_engine_dialect(monkeypatch):
    import app.api.ai_sql as ai
    import app.api.query_engine as qe
    monkeypatch.setenv("QUERY_ENGINE", "athena")
    system, _ = ai._build_messages("ctx", "count rows", None)
    assert "Athena" in system and "AwsDataCatalog" in system
    assert "The query engine is Trino." not in system
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ai_sql_dialect.py -v`
Expected: FAIL (prompt hardcodes "Trino"/"iceberg").

- [ ] **Step 3: Implement.** In `ai_sql.py`, make `_build_messages` engine-aware:

```python
def _build_messages(schema_ctx: str, question: str, context: Optional[str]) -> tuple[str, list]:
    from app.api.query_engine import get_engine
    eng = get_engine()
    system = f"""You are an expert SQL assistant for DataPond, an AI Data Foundation.
{eng.ai_dialect_prompt}

{schema_ctx}

Rules:
- Always use fully-qualified table names: {eng.ai_table_prefix}.<schema>.<table>
- Presto/Trino SQL dialect: double-quote identifiers, no backticks
- Return ONLY valid JSON with exactly two keys: "sql" and "explanation"
- "sql": runnable SQL (no markdown, no code fences)
- "explanation": one sentence describing what the query does
- Include ORDER BY for aggregations; default LIMIT 1000"""
    user_text = f"Context: {context}\n\nQuestion: {question}" if context else question
    return system, [{"role": "user", "content": user_text}]
```

Rewrite `_fetch_schema_context` to use the Slice-1 CatalogReader (removing the Trino `information_schema` coupling):

```python
def _fetch_schema_context() -> str:
    """List tables + columns from the active catalog backend (Glue or Polaris)."""
    try:
        from app.api.query_engine import get_engine
        from app.api.catalog_backend import get_catalog_reader
        eng = get_engine()
        reader = get_catalog_reader()
        lines = [f"Available tables (catalog: {eng.ai_table_prefix}):"]
        for ns in reader.list_namespaces():
            for tbl in reader.list_tables(ns):
                try:
                    cols = reader.get_columns(ns, tbl)
                except Exception:
                    cols = []
                col_str = ", ".join(f"{c['name']} ({c['type']})" for c in cols[:20])
                lines.append(f"  {eng.ai_table_prefix}.{ns}.{tbl}: {col_str}")
                if len(lines) > 50:
                    return "\n".join(lines)
        if len(lines) == 1:
            return "No tables found in the catalog."
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[ai_sql] schema fetch failed: {e}")
        return "Schema unavailable — use <catalog>.<schema>.<table> notation."
```

(The `trino_conn`/`TRINO_CATALOG` imports in ai_sql.py may become unused — remove them only if nothing else references them; the fallback template filter at line ~364 that checks `startswith("iceberg.")` should switch to `get_engine().ai_table_prefix` — verify and update.)

- [ ] **Step 4: Run tests + import check**

Run: `cd backend && python -m pytest tests/test_ai_sql_dialect.py -v && python -c "import app.api.ai_sql"`
Expected: PASS + clean import.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_sql.py backend/tests/test_ai_sql_dialect.py
git commit -m "feat(ai-sql): engine-aware prompt + schema context via CatalogReader"
```

---

## Task 5: Capability gating + Helm + IAM + pyathena dep

**Files:**
- Modify: `backend/app/capabilities.py`; `backend/tests/test_capabilities.py`
- Modify: `helm/datapond/templates/backend-deployment.yaml`, `values.yaml`, `values-prod-single.yaml`
- Modify: `terraform/iam.tf`; `backend/requirements.txt`

**Interfaces:** none new (config/infra + capability flag).

- [ ] **Step 1: Write the failing test** — extend `test_capabilities.py`:

```python
def test_athena_enables_query_and_dashboards():
    from app.capabilities import compute_capabilities
    caps = compute_capabilities({"FEATURE_TRINO": "false", "FEATURE_POLARIS": "false",
                                 "FEATURE_GLUE": "true", "FEATURE_ATHENA": "true"})
    assert caps["query"] is True and caps["dashboards"] is True
    assert caps["catalog"] is True


def test_athena_off_keeps_query_off():
    from app.capabilities import compute_capabilities
    caps = compute_capabilities({"FEATURE_TRINO": "false", "FEATURE_POLARIS": "false",
                                 "FEATURE_GLUE": "true"})
    assert caps["query"] is False and caps["catalog"] is True   # slice 1 only
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_capabilities.py -k athena -v`
Expected: FAIL (query gates on trino only).

- [ ] **Step 3: Implement capabilities.** In `compute_capabilities`:

```python
    glue = _feat(env, "GLUE", default=False)
    athena = _feat(env, "ATHENA", default=False)
    lake = trino or polaris or glue
    ...
    "query": trino or athena,
    "dashboards": trino or athena,
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Helm env.** In `backend-deployment.yaml`, after `FEATURE_GLUE`, add (derive both from `catalog.backend`, same nil-safe pattern):

```yaml
        - name: FEATURE_ATHENA
          value: "{{ if eq ((.Values.catalog | default dict).backend | default "polaris") "glue" }}true{{ else }}false{{ end }}"
        - name: QUERY_ENGINE
          value: "{{ if eq ((.Values.catalog | default dict).backend | default "polaris") "glue" }}athena{{ else }}trino{{ end }}"
        - name: ATHENA_OUTPUT_LOCATION
          value: {{ (.Values.catalog | default dict).athenaOutputLocation | default "" | quote }}
        - name: ATHENA_WORKGROUP
          value: {{ (.Values.catalog | default dict).athenaWorkgroup | default "primary" | quote }}
        - name: ATHENA_DATABASE
          value: {{ (.Values.catalog | default dict).athenaDatabase | default "default" | quote }}
        - name: RLS_DEFAULT_CATALOG
          value: "{{ if eq ((.Values.catalog | default dict).backend | default "polaris") "glue" }}AwsDataCatalog{{ else }}iceberg{{ end }}"
```

In `values.yaml` under `catalog:`, add: `athenaOutputLocation: ""`, `athenaWorkgroup: "primary"`, `athenaDatabase: "default"`. In `values-prod-single.yaml` under `catalog:`, add:

```yaml
  athenaOutputLocation: "s3://datapond-iceberg/athena-results/"
  athenaWorkgroup: "primary"
  athenaDatabase: "default"
```

- [ ] **Step 6: Athena IAM.** In `terraform/iam.tf`, add a statement to `data.aws_iam_policy_document.app`:

```hcl
  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution",
      "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup",
    ]
    resources = ["*"] # workgroup-scoped; tighten to the primary workgroup ARN in a follow-up
  }
```

(S3 results staging under the data bucket is already covered by the existing `S3Data` statement; Glue read by Slice 1's `GlueDataCatalog`.)

- [ ] **Step 7: Add pyathena.** In `backend/requirements.txt`, add `pyathena` (a line, e.g. `pyathena==3.9.0` — pick a version compatible with the installed boto3/botocore). Verify import in CI/py3.11.

- [ ] **Step 8: Verify infra renders.** Run:
`helm template datapond helm/datapond -f helm/datapond/values-prod-single.yaml --set catalog.backend=glue --set externalDatabase.host=x --set backend.image.repository=x --set frontend.image.repository=x --set ingress.domain=x 2>/dev/null | grep -E "FEATURE_ATHENA|QUERY_ENGINE|ATHENA_OUTPUT_LOCATION"`
Expected: `FEATURE_ATHENA="true"`, `QUERY_ENGINE="athena"`, `ATHENA_OUTPUT_LOCATION="s3://datapond-iceberg/athena-results/"`.
And `cd terraform && terraform validate` (in CI) → valid.

- [ ] **Step 9: Commit**

```bash
git add backend/app/capabilities.py backend/tests/test_capabilities.py \
        helm/datapond/templates/backend-deployment.yaml helm/datapond/values.yaml \
        helm/datapond/values-prod-single.yaml terraform/iam.tf backend/requirements.txt
git commit -m "feat(query): FEATURE_ATHENA gating + Athena IAM/Helm/pyathena dep"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (engine abstraction) → Task 1. ✓
- Component 2 (queries.py delegates) → Task 2. ✓
- Component 3 (AI-SQL engine-aware + schema via CatalogReader) → Task 4. ✓
- Component 4 (RLS dialect) → Task 3. ✓
- Component 5 (capability gating) → Task 5 steps 1-4. ✓
- Component 6 (IAM + config + pyathena) → Task 5 steps 5-7. ✓
- Testing section → Tasks 1-5. ✓
- Non-goal "query stays off without Athena" → Task 5 `test_athena_off_keeps_query_off`. ✓
- Trino ACL (Layer 2) not on Athena → out of the request path; `enforce` default dialect keeps Trino behavior; the trino_acl deploy hook guard is a follow-up noted in the spec (no request-path impact) — acceptable for this slice.

**Type consistency:** `get_engine()` returns objects with `execute(sql,user)->(rows,cols)`, `map_error(exc)->(status,detail,code)`, `default_catalog/default_schema/rls_dialect/ai_dialect_prompt/ai_table_prefix` — used identically in queries.py (Task 2) and ai_sql.py (Task 4). `enforce(..., dialect=...)` keyword matches Task 2's call. `QUERY_ENGINE`/`FEATURE_ATHENA`/`ATHENA_*` env names identical across query_engine.py, capabilities, and Helm.

**Placeholder scan:** no TBD/TODO. Verification steps (Task 1 step 5, Task 5 steps 7-8) are concrete commands. Two "verify/update if unused" notes (ai_sql trino imports, the line-364 template filter) point at existing-code conformance to check during implementation, with the exact replacement given.
