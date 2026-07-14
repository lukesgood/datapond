# Glue-Native Ingestion + Catalog Implementation Plan (B2 · Slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DataPond's foundation profile land connector data into AWS Glue-registered Iceberg-on-S3 tables and browse/preview them in the Catalog UI, using pyiceberg's `GlueCatalog` — no Athena, no self-hosted Trino/Polaris.

**Architecture:** An env flag `ICEBERG_CATALOG_BACKEND` (`glue`|`polaris`) selects the pyiceberg catalog built by `iceberg_catalog.get_catalog()`. A new `CatalogReader` abstraction (`GlueCatalogReader` reusing that singleton; `PolarisCatalogReader` wrapping existing behavior) backs the catalog-read endpoints. `FEATURE_GLUE` re-enables the `connectors`/`catalog` capabilities; `query` stays off (Athena is Slice 2).

**Tech Stack:** Python 3.11, FastAPI, pyiceberg[pyarrow]==0.11.1 (`GlueCatalog`), boto3==1.34.0, AWS Glue Data Catalog + S3, pytest, Terraform, Helm. Spec: `docs/superpowers/specs/2026-07-14-glue-native-ingestion-catalog-design.md`.

## Global Constraints

- No new dependency: `pyiceberg[pyarrow]==0.11.1` already ships `pyiceberg.catalog.glue.GlueCatalog`; `boto3==1.34.0` present. Verify the import works under the pin before writing logic.
- `ICEBERG_CATALOG_BACKEND` defaults to `polaris` — on-prem/full profiles must be byte-for-byte unchanged.
- One pyiceberg catalog singleton (`iceberg_catalog.get_catalog()`) serves write + read; `GlueCatalogReader` reuses it, never builds its own.
- Query stays gated: `capabilities.query`/`dashboards` remain `trino` only. Do NOT enable Athena here.
- Tests are pure-unit in the repo style (`backend/tests/test_*.py`, `monkeypatch`, in-file fakes; no live AWS/DB). CI py3.11 is authoritative (local lacks the deps chain).
- Run tests: `cd backend && python -m pytest tests/test_capabilities.py tests/test_catalog_backend.py tests/test_iceberg_catalog_backend.py -v`.
- AWS credentials for Glue + S3 come from the node instance profile (default chain) — never static keys on AWS (mirror `_s3_fileio_props`).

---

## File Structure

- `backend/app/capabilities.py` (modify) — add `FEATURE_GLUE` → `connectors`/`catalog`.
- `backend/app/connectors/iceberg_catalog.py` (modify) — `get_catalog()` env-selected; add `_build_glue_catalog()` / `_build_polaris_catalog()`.
- `backend/app/api/catalog_backend.py` (create) — `CatalogReader` protocol, `GlueCatalogReader`, `PolarisCatalogReader`, `get_catalog_reader()`.
- `backend/app/api/catalog.py` (modify) — route `get_table_details`/`preview_table`/listing through `get_catalog_reader()`.
- `backend/app/api/queries.py` (modify) — route `/catalog/schemas` tree + `/catalog/columns` through `get_catalog_reader()`.
- `helm/datapond/templates/backend-deployment.yaml` (modify) — `FEATURE_GLUE`, `ICEBERG_CATALOG_BACKEND`, `GLUE_WAREHOUSE` env.
- `helm/datapond/values.yaml`, `helm/datapond/values-prod-single.yaml` (modify) — catalog backend config.
- `terraform/iam.tf` (modify) — Glue permissions on the node app-role policy.
- Tests: `backend/tests/test_capabilities.py` (extend), `backend/tests/test_iceberg_catalog_backend.py` (create), `backend/tests/test_catalog_backend.py` (create).

---

## Task 1: Capability gating (FEATURE_GLUE)

**Files:**
- Modify: `backend/app/capabilities.py:19-38`
- Modify: `helm/datapond/templates/backend-deployment.yaml` (FEATURE_* env block)
- Test: `backend/tests/test_capabilities.py`

**Interfaces:**
- Produces: `compute_capabilities(env)` returns `connectors`/`catalog` true when `FEATURE_GLUE` is truthy (or TRINO/POLARIS); `query`/`dashboards` unchanged (`trino` only).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_capabilities.py`:

```python
def test_glue_enables_connectors_and_catalog_but_not_query():
    from app.capabilities import compute_capabilities
    env = {"FEATURE_TRINO": "false", "FEATURE_POLARIS": "false", "FEATURE_GLUE": "true"}
    caps = compute_capabilities(env)
    assert caps["connectors"] is True
    assert caps["catalog"] is True
    assert caps["query"] is False        # Athena is a later slice
    assert caps["dashboards"] is False


def test_all_lake_backends_off():
    from app.capabilities import compute_capabilities
    env = {"FEATURE_TRINO": "false", "FEATURE_POLARIS": "false", "FEATURE_GLUE": "false"}
    caps = compute_capabilities(env)
    assert caps["connectors"] is False and caps["catalog"] is False and caps["query"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_capabilities.py -k glue -v`
Expected: FAIL (glue currently not read; connectors false).

- [ ] **Step 3: Implement** — in `compute_capabilities`, change the `lake` computation:

```python
    trino = _feat(env, "TRINO")
    polaris = _feat(env, "POLARIS")
    glue = _feat(env, "GLUE")
    lake = trino or polaris or glue
```

(The `"connectors": lake` / `"catalog": lake` lines already reference `lake`; update the `connectors` comment to `# Ingestion → Iceberg via Trino/Polaris or Glue`. Leave `"query": trino` and `"dashboards": trino` unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Wire Helm env.** In `helm/datapond/templates/backend-deployment.yaml`, in the `FEATURE_*` env block (next to `FEATURE_TRINO`), add:

```yaml
        - name: FEATURE_GLUE
          value: {{ .Values.features.glue | default false | quote }}
```

In `helm/datapond/values.yaml` under `features:` (create the key if the pattern uses `.Values.features.*`; otherwise mirror how `FEATURE_TRINO` sources its value and add `glue: false`). Default false so only foundation/AWS opts in.

- [ ] **Step 6: Verify Helm renders**

Run: `helm template datapond helm/datapond -f helm/datapond/values-prod-single.yaml --set externalDatabase.host=x --set backend.image.repository=x --set frontend.image.repository=x --set ingress.domain=x 2>/dev/null | grep -A1 FEATURE_GLUE`
Expected: shows `FEATURE_GLUE` with a quoted value.

- [ ] **Step 7: Commit**

```bash
git add backend/app/capabilities.py backend/tests/test_capabilities.py helm/datapond/templates/backend-deployment.yaml helm/datapond/values.yaml
git commit -m "feat(catalog): FEATURE_GLUE enables connectors+catalog capabilities"
```

---

## Task 2: Glue write catalog (get_catalog backend selection)

**Files:**
- Modify: `backend/app/connectors/iceberg_catalog.py` (function `get_catalog` lines 17-40)
- Test: `backend/tests/test_iceberg_catalog_backend.py` (create)

**Interfaces:**
- Produces: `get_catalog()` returns a `GlueCatalog` when `ICEBERG_CATALOG_BACKEND=glue`, else the existing `RestCatalog`. Helpers `_build_glue_catalog()`, `_build_polaris_catalog()`. `reset_catalog()` (test helper) clears the singleton.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_iceberg_catalog_backend.py`:

```python
import sys, types


def _install_fake_pyiceberg(monkeypatch):
    """Fake pyiceberg.catalog.glue.GlueCatalog + pyiceberg.catalog.rest.RestCatalog
    so we can assert which backend get_catalog() builds without real AWS/Polaris."""
    made = {}
    glue_mod = types.ModuleType("pyiceberg.catalog.glue")
    rest_mod = types.ModuleType("pyiceberg.catalog.rest")
    class GlueCatalog:
        def __init__(self, name, **props): made["kind"] = "glue"; made["props"] = props
    class RestCatalog:
        def __init__(self, name, **props): made["kind"] = "rest"; made["props"] = props
    glue_mod.GlueCatalog = GlueCatalog
    rest_mod.RestCatalog = RestCatalog
    monkeypatch.setitem(sys.modules, "pyiceberg.catalog.glue", glue_mod)
    monkeypatch.setitem(sys.modules, "pyiceberg.catalog.rest", rest_mod)
    return made


def test_get_catalog_builds_glue_when_backend_glue(monkeypatch):
    made = _install_fake_pyiceberg(monkeypatch)
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    monkeypatch.setenv("GLUE_WAREHOUSE", "s3://datapond-iceberg/warehouse")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    import app.connectors.iceberg_catalog as ic
    ic.reset_catalog()
    ic.get_catalog()
    assert made["kind"] == "glue"
    assert made["props"]["warehouse"] == "s3://datapond-iceberg/warehouse"
    assert made["props"]["glue.region"] == "us-east-1"


def test_get_catalog_defaults_to_polaris(monkeypatch):
    made = _install_fake_pyiceberg(monkeypatch)
    monkeypatch.delenv("ICEBERG_CATALOG_BACKEND", raising=False)
    import app.connectors.iceberg_catalog as ic
    ic.reset_catalog()
    ic.get_catalog()
    assert made["kind"] == "rest"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_iceberg_catalog_backend.py -v`
Expected: FAIL (no `reset_catalog`; `get_catalog` ignores backend).

- [ ] **Step 3: Implement** — replace `get_catalog` (17-40) with:

```python
def get_catalog():
    """pyiceberg catalog singleton. Backend selected by ICEBERG_CATALOG_BACKEND
    (glue = AWS Glue Data Catalog; polaris = self-hosted REST, default)."""
    global _catalog
    if _catalog is None:
        with _lock:
            if _catalog is None:
                backend = os.getenv("ICEBERG_CATALOG_BACKEND", "polaris").strip().lower()
                _catalog = _build_glue_catalog() if backend == "glue" else _build_polaris_catalog()
    return _catalog


def reset_catalog():
    """Test/reload helper: drop the cached catalog singleton."""
    global _catalog
    _catalog = None


def _build_glue_catalog():
    from pyiceberg.catalog.glue import GlueCatalog
    props = {
        "warehouse": os.getenv("GLUE_WAREHOUSE", ""),
        "glue.region": os.getenv("S3_REGION", "us-east-1"),
        **_s3_fileio_props(),
    }
    return GlueCatalog(name="datapond", **props)


def _build_polaris_catalog():
    from pyiceberg.catalog.rest import RestCatalog
    client_id = os.getenv("POLARIS_CLIENT_ID", "polaris-client")
    client_secret = component_secret("POLARIS_CLIENT_SECRET", "changeme-polaris-secret", component="polaris")
    return RestCatalog(
        name="datapond",
        **{
            "uri":        os.getenv("POLARIS_URI", "http://polaris:8181/api/catalog"),
            "warehouse":  os.getenv("POLARIS_WAREHOUSE", "iceberg"),
            "credential": f"{client_id}:{client_secret}",
            "scope":      "PRINCIPAL_ROLE:ALL",
            **_s3_fileio_props(),
        },
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_iceberg_catalog_backend.py -v`
Expected: PASS.

- [ ] **Step 5: Verify the real import works under the pin** (one-time env check):

Run: `cd backend && python -c "from pyiceberg.catalog.glue import GlueCatalog; print('GlueCatalog import OK')"` (in CI/py3.11 with deps). If it fails, the pin needs `pyiceberg[glue]` added to `requirements.txt` — but boto3 is already present, so `GlueCatalog` should import. Record the result.

- [ ] **Step 6: Commit**

```bash
git add backend/app/connectors/iceberg_catalog.py backend/tests/test_iceberg_catalog_backend.py
git commit -m "feat(catalog): pyiceberg GlueCatalog backend in get_catalog()"
```

---

## Task 3: CatalogReader abstraction (GlueCatalogReader + PolarisCatalogReader)

**Files:**
- Create: `backend/app/api/catalog_backend.py`
- Test: `backend/tests/test_catalog_backend.py` (create)

**Interfaces:**
- Consumes: `iceberg_catalog.get_catalog()` (Task 2).
- Produces:
  - `get_catalog_reader() -> CatalogReader` (env-selected).
  - `CatalogReader` methods: `list_namespaces() -> list[str]`, `list_tables(ns) -> list[str]`, `get_columns(ns, table) -> list[dict{name,type,nullable}]`, `get_location(ns, table) -> str|None`, `row_count(ns, table) -> int|None`, `preview(ns, table, limit) -> dict{columns:list[str], rows:list[list]}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_catalog_backend.py`:

```python
import types


class _Field:
    def __init__(self, name, ftype, required): self.name = name; self.field_type = ftype; self.required = required


class _Schema:
    def __init__(self, fields): self.fields = fields


class _Snapshot:
    def __init__(self, summary): self.summary = summary


class _Arrow:
    def __init__(self, cols, rows): self.column_names = cols; self._rows = rows
    def to_pylist(self): return [dict(zip(self.column_names, r)) for r in self._rows]


class _Scan:
    def __init__(self, arrow): self._a = arrow
    def limit(self, n): return self
    def to_arrow(self): return self._a


class _Table:
    def __init__(self):
        self._schema = _Schema([_Field("id", "long", True), _Field("note", "string", False)])
        self.metadata = types.SimpleNamespace(location="s3://b/warehouse/db/t")
        self._snap = _Snapshot({"total-records": "42"})
        self._arrow = _Arrow(["id", "note"], [[1, "a"], [2, None]])
    def schema(self): return self._schema
    def current_snapshot(self): return self._snap
    def scan(self, **_): return _Scan(self._arrow)


class _FakeCatalog:
    def list_namespaces(self, *a): return [("sales",), ("ops",)]
    def list_tables(self, ns): return [(ns, "orders")]
    def load_table(self, ident): return _Table()


def test_reader_selection(monkeypatch):
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    import importlib, app.api.catalog_backend as cb
    importlib.reload(cb)
    assert cb.get_catalog_reader().__class__.__name__ == "GlueCatalogReader"
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "polaris")
    importlib.reload(cb)
    assert cb.get_catalog_reader().__class__.__name__ == "PolarisCatalogReader"


def test_glue_reader_methods(monkeypatch):
    import importlib, app.api.catalog_backend as cb
    importlib.reload(cb)
    monkeypatch.setattr(cb, "get_catalog", lambda: _FakeCatalog())
    r = cb.GlueCatalogReader()
    assert set(r.list_namespaces()) == {"sales", "ops"}
    assert r.list_tables("sales") == ["orders"]
    cols = r.get_columns("sales", "orders")
    assert cols[0] == {"name": "id", "type": "long", "nullable": False}
    assert cols[1]["nullable"] is True
    assert r.get_location("sales", "orders") == "s3://b/warehouse/db/t"
    assert r.row_count("sales", "orders") == 42
    prev = r.preview("sales", "orders", 100)
    assert prev["columns"] == ["id", "note"]
    assert prev["rows"] == [[1, "a"], [2, None]]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_catalog_backend.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — create `backend/app/api/catalog_backend.py`:

```python
"""Catalog-read backend abstraction. Selected by ICEBERG_CATALOG_BACKEND
(glue = AWS Glue via the shared pyiceberg catalog; polaris = existing
Polaris HTTP + Trino). Keeps catalog.py / queries.py engine-agnostic."""
import os
import logging

logger = logging.getLogger(__name__)


def get_catalog():  # thin indirection so tests can monkeypatch the import site
    from app.connectors.iceberg_catalog import get_catalog as _gc
    return _gc()


class GlueCatalogReader:
    """Reads catalog metadata straight from the shared pyiceberg GlueCatalog —
    list/load_table/schema/scan/snapshot. No Trino, no separate boto3 client."""

    def list_namespaces(self):
        return [".".join(ns) for ns in get_catalog().list_namespaces()]

    def list_tables(self, namespace):
        return [t[-1] for t in get_catalog().list_tables(namespace)]

    def _load(self, namespace, table):
        return get_catalog().load_table(f"{namespace}.{table}")

    def get_columns(self, namespace, table):
        return [
            {"name": f.name, "type": str(f.field_type), "nullable": not f.required}
            for f in self._load(namespace, table).schema().fields
        ]

    def get_location(self, namespace, table):
        try:
            return self._load(namespace, table).metadata.location
        except Exception:
            return None

    def row_count(self, namespace, table):
        snap = self._load(namespace, table).current_snapshot()
        if snap and getattr(snap, "summary", None) and "total-records" in snap.summary:
            return int(snap.summary["total-records"])
        return None

    def preview(self, namespace, table, limit):
        arrow = self._load(namespace, table).scan().limit(min(limit, 500)).to_arrow()
        cols = list(arrow.column_names)
        rows = [[d.get(c) for c in cols] for d in arrow.to_pylist()]
        return {"columns": cols, "rows": rows}


class PolarisCatalogReader:
    """Existing Polaris HTTP listing + Trino detail reads, wrapped behind the
    CatalogReader interface so the endpoints stay backend-agnostic."""

    def list_namespaces(self):
        from app.api.polaris_client import list_catalogs, list_namespaces
        out = []
        for pcat in list_catalogs():
            try:
                out.extend(list_namespaces(pcat["name"]))
            except Exception:
                continue
        return out

    def list_tables(self, namespace):
        from app.api.polaris_client import list_catalogs, list_tables
        out = []
        for pcat in list_catalogs():
            try:
                out.extend(list_tables(pcat["name"], namespace))
            except Exception:
                continue
        return out

    def get_columns(self, namespace, table, catalog="iceberg"):
        from app.api.trino_util import trino_conn
        cur = trino_conn(catalog=catalog, timeout=15).cursor()
        cur.execute(
            f"SELECT column_name, data_type, is_nullable FROM {catalog}.information_schema.columns "
            f"WHERE table_schema='{namespace}' AND table_name='{table}' ORDER BY ordinal_position")
        return [{"name": r[0], "type": r[1], "nullable": (r[2].upper() == "YES")} for r in cur.fetchall()]

    def get_location(self, namespace, table, catalog="iceberg"):
        import re
        from app.api.trino_util import trino_conn
        try:
            cur = trino_conn(catalog=catalog, timeout=15).cursor()
            cur.execute(f"SHOW CREATE TABLE {catalog}.{namespace}.{table}")
            ddl = cur.fetchone()[0]
            m = re.search(r"location\s*=\s*'([^']+)'", ddl, re.IGNORECASE)
            return m.group(1) if m else None
        except Exception:
            return None

    def row_count(self, namespace, table, catalog="iceberg"):
        from app.api.trino_util import trino_conn
        try:
            cur = trino_conn(catalog=catalog, timeout=15).cursor()
            cur.execute(f"SELECT COUNT(*) FROM {catalog}.{namespace}.{table}")
            return cur.fetchone()[0]
        except Exception:
            return None

    def preview(self, namespace, table, limit, catalog="iceberg"):
        from app.api.trino_util import trino_conn
        cur = trino_conn(catalog=catalog, timeout=15).cursor()
        cur.execute(f"SELECT * FROM {catalog}.{namespace}.{table} LIMIT {min(limit, 500)}")
        rows_raw = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return {"columns": cols, "rows": [list(r) for r in rows_raw]}


def get_catalog_reader():
    backend = os.getenv("ICEBERG_CATALOG_BACKEND", "polaris").strip().lower()
    return GlueCatalogReader() if backend == "glue" else PolarisCatalogReader()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_catalog_backend.py -v`
Expected: PASS.

- [ ] **Step 5: Verify pyiceberg scan-limit API under the pin.** In CI/py3.11, confirm `Table.scan().limit(n).to_arrow()` exists in pyiceberg 0.11.1 (`python -c "import pyiceberg, inspect; from pyiceberg.table import DataScan; print(hasattr(DataScan,'limit'))"`). If `.limit()` is absent in 0.11.1, change `preview` to `scan().to_arrow().slice(0, min(limit,500))` and note the full-read caveat. Record which path is used.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/catalog_backend.py backend/tests/test_catalog_backend.py
git commit -m "feat(catalog): CatalogReader abstraction (Glue + Polaris backends)"
```

---

## Task 4: Route catalog endpoints through CatalogReader

**Files:**
- Modify: `backend/app/api/catalog.py` (`get_table_details` 123-180, `preview_table` 183-235, `list_all_namespaces` 74-93, `list_all_tables` 96-120)
- Modify: `backend/app/api/queries.py` (`get_catalog_schemas` 345+, `get_table_columns` 481+)
- Test: `backend/tests/test_catalog_backend.py` (extend)

**Interfaces:**
- Consumes: `get_catalog_reader()` (Task 3).
- Produces: the catalog HTTP endpoints return the same JSON shape as before, sourced from the selected backend.

- [ ] **Step 1: Write the failing test** (endpoint uses the reader) — extend `test_catalog_backend.py`:

```python
def test_get_table_details_uses_reader(monkeypatch):
    import asyncio, app.api.catalog as cat

    class _R:
        def get_columns(self, ns, t): return [{"name": "id", "type": "long", "nullable": False}]
        def get_location(self, ns, t): return "s3://b/t"
        def row_count(self, ns, t): return 7
    monkeypatch.setattr(cat, "get_catalog_reader", lambda: _R())
    res = asyncio.get_event_loop().run_until_complete(cat.get_table_details("sales", "orders"))
    assert res.columns[0].name == "id" and res.location == "s3://b/t" and res.row_count == 7
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_catalog_backend.py::test_get_table_details_uses_reader -v`
Expected: FAIL (`catalog.get_catalog_reader` not imported; still hits Trino).

- [ ] **Step 3: Implement — `catalog.py`.** Add import near the top (after line 16):

```python
from app.api.catalog_backend import get_catalog_reader
```

Replace `get_table_details` body (126-180) with:

```python
    try:
        reader = get_catalog_reader()
        columns = [TableColumn(**c) for c in reader.get_columns(namespace, table)]
        if not columns:
            raise HTTPException(status_code=404, detail=f"Table {namespace}.{table} not found")
        location = reader.get_location(namespace, table)
        row_count = reader.row_count(namespace, table)
        return TableDetails(
            name=table, namespace=namespace, table_type="iceberg",
            location=location, columns=columns,
            properties={"location": location} if location else {},
            row_count=row_count, last_updated=datetime.utcnow().isoformat() + "Z",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"catalog table detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

Replace the row-sampling block in `preview_table` (189-193) with:

```python
        preview = get_catalog_reader().preview(namespace, table, limit)
        cols = preview["columns"]
        rows = [dict(zip(cols, row)) for row in preview["rows"]]
```

(Keep the existing NaN-scrub + column-statistics code below it unchanged — it consumes `rows`/`cols`.)

For `list_all_namespaces` / `list_all_tables`, replace the `polaris_client` loops with the reader (namespaces have no catalog dimension in the Glue backend; keep `catalog="iceberg"` label):

```python
# list_all_namespaces body:
    try:
        names = get_catalog_reader().list_namespaces()
        return NamespacesResponse(namespaces=[NamespaceInfo(name=n) for n in names])
    except Exception as e:
        logger.error(f"catalog namespaces error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

```python
# list_all_tables body:
    try:
        reader = get_catalog_reader()
        tables = []
        for ns in reader.list_namespaces():
            for tbl in reader.list_tables(ns):
                tables.append(TableInfo(name=tbl, namespace=ns))
        return TablesResponse(tables=tables)
    except Exception as e:
        logger.error(f"catalog tables error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Implement — `queries.py` catalog tree.** In `get_catalog_schemas` (345+), replace the Polaris/Trino tree-build with the reader. Keep the Valkey cache wrapper. Replace the body from `from app.api.polaris_client import ...` (372) through the catalog-loop with:

```python
    try:
        from app.api.catalog_backend import get_catalog_reader
        reader = get_catalog_reader()
        schemas_list = []
        for ns in reader.list_namespaces():
            tables_list = []
            for tbl in reader.list_tables(ns):
                entry = {"name": tbl, "columns": []}
                if columns:
                    try:
                        entry["columns"] = reader.get_columns(ns, tbl)
                    except Exception:
                        entry["columns"] = []
                tables_list.append(entry)
            schemas_list.append({"name": ns, "tables": tables_list})
        result = CatalogTree(catalogs=[{"name": "iceberg", "schemas": schemas_list}])
```

(Preserve the surrounding cache-set logic and the shape `CatalogTree(catalogs=[{name, schemas:[{name, tables:[{name, columns}]}]}])` — match whatever keys the frontend reads; verify against the current serialized shape before editing.)

Replace `get_table_columns` (481+) body with:

```python
    try:
        cols = get_catalog_reader().get_columns(schema, table)
        return {"columns": cols}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

(Import `get_catalog_reader` at the top of `queries.py`; keep the `_COL_IDENT` identifier validation before calling the reader.)

- [ ] **Step 5: Run tests + import check**

Run: `cd backend && python -m pytest tests/test_catalog_backend.py -v && python -c "import app.api.catalog, app.api.queries"`
Expected: PASS + clean import.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/catalog.py backend/app/api/queries.py backend/tests/test_catalog_backend.py
git commit -m "feat(catalog): route catalog endpoints through CatalogReader"
```

---

## Task 5: Terraform Glue IAM + Helm catalog config

**Files:**
- Modify: `terraform/iam.tf` (node app-role policy)
- Modify: `helm/datapond/templates/backend-deployment.yaml` (ICEBERG_CATALOG_BACKEND, GLUE_WAREHOUSE env)
- Modify: `helm/datapond/values.yaml`, `helm/datapond/values-prod-single.yaml`

**Interfaces:** none (infra/config).

- [ ] **Step 1: Add Glue IAM.** In `terraform/iam.tf`, add a statement to the app-role policy document granting Glue catalog access (S3 already granted):

```hcl
  statement {
    sid    = "GlueDataCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase", "glue:GetDatabases", "glue:CreateDatabase",
      "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
      "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition",
      "glue:BatchCreatePartition", "glue:CreatePartition", "glue:UpdatePartition", "glue:DeletePartition",
    ]
    resources = ["*"]   # Glue ARNs are catalog/db/table-scoped; tighten to datapond* dbs in a follow-up
  }
```

(Match the existing `iam.tf` structure — if it uses inline `jsonencode` policy rather than `data.aws_iam_policy_document`, add the equivalent JSON statement block instead. Read the file first.)

- [ ] **Step 2: Verify terraform**

Run: `cd terraform && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Add Helm env.** In `backend-deployment.yaml` env, add:

```yaml
        - name: ICEBERG_CATALOG_BACKEND
          value: {{ .Values.catalog.backend | default "polaris" | quote }}
        - name: GLUE_WAREHOUSE
          value: {{ .Values.catalog.glueWarehouse | default "" | quote }}
```

In `values.yaml`, add a `catalog:` block:

```yaml
catalog:
  backend: polaris          # glue | polaris
  glueWarehouse: ""         # s3://<bucket>/warehouse when backend=glue
```

In `values-prod-single.yaml`, set the foundation profile to Glue:

```yaml
features:
  glue: true
catalog:
  backend: glue
  glueWarehouse: "s3://datapond-iceberg/warehouse"
```

- [ ] **Step 4: Verify Helm render**

Run: `helm template datapond helm/datapond -f helm/datapond/values-prod-single.yaml --set externalDatabase.host=x --set backend.image.repository=x --set frontend.image.repository=x --set ingress.domain=x 2>/dev/null | grep -E "ICEBERG_CATALOG_BACKEND|GLUE_WAREHOUSE|FEATURE_GLUE"`
Expected: `ICEBERG_CATALOG_BACKEND` = `"glue"`, `GLUE_WAREHOUSE` = `"s3://datapond-iceberg/warehouse"`, `FEATURE_GLUE` = `"true"`.

- [ ] **Step 5: Commit**

```bash
git add terraform/iam.tf helm/datapond/templates/backend-deployment.yaml helm/datapond/values.yaml helm/datapond/values-prod-single.yaml
git commit -m "feat(catalog): Glue IAM + foundation profile catalog.backend=glue"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (write catalog backend) → Task 2. ✓
- Component 2 (CatalogReader abstraction) → Task 3. ✓
- Component 3 (preview + stats via pyiceberg) → Task 3 (`GlueCatalogReader.preview`) + Task 4 (preview_table keeps stats). ✓
- Component 4 (capability gating) → Task 1. ✓
- Component 5 (IAM) → Task 5 step 1. ✓
- Component 6 (Helm/config) → Task 1 (FEATURE_GLUE) + Task 5 (backend/warehouse). ✓
- Testing section → tests in Tasks 1-4. ✓
- Non-goal "query stays off" → Task 1 leaves `query`/`dashboards` = `trino`. ✓

**Type consistency:** `get_catalog_reader()` returns objects with the same method names used in Task 4 (`get_columns`→list[dict], `get_location`→str|None, `row_count`→int|None, `preview`→{columns,rows}). `TableColumn(**c)` matches the dict keys `{name,type,nullable}` the reader emits. `iceberg_catalog.get_catalog()`/`reset_catalog()` names match Task 2 and the Task 3 monkeypatch site (`catalog_backend.get_catalog`). `ICEBERG_CATALOG_BACKEND` string used identically in Tasks 2/3/5.

**Placeholder scan:** no TBD/TODO. Two explicit CI-verification steps (Task 2 step 5, Task 3 step 5) flag pyiceberg-API points to confirm under the 0.11.1 pin and give the fallback — these are real engineering checks with concrete commands, not placeholders. Two "read the file first / match existing structure" notes (Task 1 values wiring, Task 5 iam.tf shape) point at existing-pattern conformance where the exact surrounding syntax must be matched.
