# UI Capability-Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** When a heavy component (Trino, Polaris, Airflow, MLflow, RisingWave, OpenMetadata, Jupyter) is disabled via Helm (e.g. the lean `values-foundation` profile), the frontend HIDES that feature's nav item/page instead of showing runtime errors.

**Architecture:** Helm injects per-component `FEATURE_<X>` env into the backend from the existing `.Values.<c>.enabled` toggles. The backend exposes `GET /api/capabilities` returning a feature→bool map (computed from those env vars). The frontend fetches it once on load via a `useCapabilities()` hook/context and filters the nav; gated pages optionally show a "feature not enabled" notice.

**Tech Stack:** FastAPI (Python), Next.js/React (TypeScript), Helm.

## Global Constraints

- Additive & backward-compatible: default `FEATURE_*` = enabled (true) when the env is unset, so existing full deployments show every nav item exactly as today. Only a profile that sets a component `enabled:false` hides its feature.
- `helm` NOT installed locally → Helm render verified by CI `Helm chart lint`. Backend tested with pytest (CI Python 3.11; local runnable for env-only tests). Frontend verified by `tsc --noEmit` (CI) + inspection.
- The `/api/capabilities` endpoint must be dependency-free (no DB, no component calls) — pure env read — so it's instant and never fails.
- Feature→component mapping (authoritative):
  `catalog = trino OR polaris`, `query = trino`, `pipelines = airflow`, `transforms = airflow`, `streaming = risingwave`, `experiments = mlflow`, `notebooks = jupyter`, `lineage = openmetadata`. Core features (`dashboard`, `knowledge`, `ai`, `settings`, `governance`, `storage`, `connectors`) are always `true`.

---

## File Structure

**Modified (backend):** `backend/main.py` — add inline `GET /api/capabilities`. **Test:** `backend/tests/test_capabilities.py`.
**Modified (helm):** `helm/datapond/templates/backend-deployment.yaml` — `FEATURE_*` env from toggles.
**Modified (frontend):** the nav/sidebar component + a small `useCapabilities` hook/context (exact paths located in Task 3).

---

## Task 1: Backend `/api/capabilities` endpoint

**Files:** Modify `backend/main.py`; Test `backend/tests/test_capabilities.py`.

**Interfaces:** Produces `GET /api/capabilities` → JSON `{feature: bool}`. Pure function `compute_capabilities(env: Mapping) -> dict` (testable without FastAPI).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_capabilities.py`:
```python
from main import compute_capabilities

def _env(**kw):
    base = {f"FEATURE_{k}": v for k, v in kw.items()}
    return base

def test_all_enabled_by_default():
    caps = compute_capabilities({})  # nothing set → everything on (backward compat)
    assert caps["catalog"] is True
    assert caps["query"] is True
    assert caps["streaming"] is True
    assert caps["knowledge"] is True  # core

def test_lean_profile_hides_lakehouse():
    env = _env(TRINO="false", POLARIS="false", AIRFLOW="false", MLFLOW="false",
               RISINGWAVE="false", OPENMETADATA="false", JUPYTER="false")
    caps = compute_capabilities(env)
    assert caps["catalog"] is False      # trino OR polaris, both off
    assert caps["connectors"] is False   # ingestion → Iceberg via trino/polaris
    assert caps["query"] is False        # trino
    assert caps["dashboards"] is False   # trino-backed BI
    assert caps["pipelines"] is False    # airflow
    assert caps["streaming"] is False    # risingwave
    assert caps["experiments"] is False  # mlflow
    assert caps["notebooks"] is False    # jupyter
    assert caps["lineage"] is False      # openmetadata
    # core always on
    assert caps["knowledge"] is True
    assert caps["ai"] is True
    assert caps["settings"] is True
    assert caps["governance"] is True
    assert caps["storage"] is True

def test_catalog_on_if_only_polaris():
    caps = compute_capabilities(_env(TRINO="false", POLARIS="true"))
    assert caps["catalog"] is True
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd backend && python3 -m pytest tests/test_capabilities.py -v`
Expected: FAIL (`compute_capabilities` not defined / ImportError).

- [ ] **Step 3: Implement in `backend/main.py`**
Add near the other inline endpoints (e.g. beside `/api/services`):
```python
def _feat(env, name: str, default: bool = True) -> bool:
    v = env.get(f"FEATURE_{name}")
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def compute_capabilities(env) -> dict:
    """Feature→enabled map from FEATURE_<COMPONENT> env (default enabled).
    Pure/dependency-free so /api/capabilities is instant and never fails."""
    trino = _feat(env, "TRINO")
    polaris = _feat(env, "POLARIS")
    lake = trino or polaris
    return {
        # core — always available
        "knowledge": True, "ai": True, "settings": True, "governance": True,
        "storage": True, "services": True, "system": True, "dashboard": True,
        "docs": True, "help": True,
        # component-gated
        "connectors": lake,       # Ingestion → Iceberg via Trino/Polaris
        "catalog": lake,
        "query": trino,
        "dashboards": trino,      # BI mini-charts run Trino queries
        "pipelines": _feat(env, "AIRFLOW"),   # Transforms
        "streaming": _feat(env, "RISINGWAVE"),
        "experiments": _feat(env, "MLFLOW"),
        "notebooks": _feat(env, "JUPYTER"),
        "lineage": _feat(env, "OPENMETADATA"),  # governance sub-tab (nav stays core)
    }


@app.get("/api/capabilities")
async def get_capabilities():
    import os as _os
    return compute_capabilities(_os.environ)
```
(If `app` is defined later than a convenient spot for the helpers, put the two pure functions near the top and the route beside the other `@app.get` inline routes.)

- [ ] **Step 4: Run tests to verify pass** — `cd backend && python3 -m pytest tests/test_capabilities.py -v` → all pass.

- [ ] **Step 5: Commit**
```bash
git add backend/main.py backend/tests/test_capabilities.py
git commit -m "feat(api): /api/capabilities — feature flags from FEATURE_* env (default on)"
```

---

## Task 2: Helm — inject `FEATURE_*` env into backend

**Files:** Modify `helm/datapond/templates/backend-deployment.yaml`.

**Interfaces:** Consumes `.Values.<trino|polaris|airflow|mlflow|risingwave|openmetadata|jupyter>.enabled`; produces `FEATURE_*` env the Task-1 endpoint reads.

- [ ] **Step 1: Add env block**
In the backend container `env:` list, add (using each component's `.enabled`, defaulting true so unset = on):
```yaml
        # Feature flags for UI capability-gating (frontend hides pages whose
        # backend component is disabled). Default true.
        - name: FEATURE_TRINO
          value: "{{ .Values.trino.enabled | default true }}"
        - name: FEATURE_POLARIS
          value: "{{ .Values.polaris.enabled | default true }}"
        - name: FEATURE_AIRFLOW
          value: "{{ .Values.airflow.enabled | default true }}"
        - name: FEATURE_MLFLOW
          value: "{{ .Values.mlflow.enabled | default true }}"
        - name: FEATURE_RISINGWAVE
          value: "{{ .Values.risingwave.enabled | default true }}"
        - name: FEATURE_OPENMETADATA
          value: "{{ .Values.openmetadata.enabled | default true }}"
        - name: FEATURE_JUPYTER
          value: "{{ .Values.jupyter.enabled | default true }}"
```

- [ ] **Step 2: Verify (inspection — helm unavailable)** — YAML valid, all seven flags present, quoted values (Go bool → string). Confirm `.Values.<c>.enabled` keys exist (they do — verified in the chart).

- [ ] **Step 3: Commit**
```bash
git add helm/datapond/templates/backend-deployment.yaml
git commit -m "feat(helm): inject FEATURE_* flags into backend from component toggles"
```

---

## Task 3: Frontend — `useCapabilities` + nav gating

**Files (exact):**
- Create: `frontend/lib/capabilities.ts` — fetch helper + `Capabilities` type + a `CapabilitiesProvider`/`useCapabilities` (React context).
- Modify: `frontend/components/conditional-layout.tsx` — wrap `AppSidebar` (+ children) in `CapabilitiesProvider`.
- Modify: `frontend/components/app-sidebar.tsx` — add a `capability` key per nav item; filter `mainSections[].items` and `bottomItems` by `useCapabilities()`.

**Interfaces:** Consumes `GET /api/capabilities`. Nav shows an item if it has no `capability` key OR `caps[item.capability] !== false` (fail-open: missing map / fetch error → shown → backward-compat with full deployments).

- [ ] **Step 1: Create `frontend/lib/capabilities.ts`**
```tsx
"use client"
import { createContext, useContext, useEffect, useState } from "react"

export type Capabilities = Record<string, boolean>

const CapsContext = createContext<Capabilities>({})

export function CapabilitiesProvider({ children }: { children: React.ReactNode }) {
  // Start all-true (fail-open): nothing hidden until we learn otherwise.
  const [caps, setCaps] = useState<Capabilities>({})
  useEffect(() => {
    fetch("/api/capabilities")
      .then((r) => (r.ok ? r.json() : {}))
      .then((c) => setCaps(c || {}))
      .catch(() => setCaps({}))  // fail-open: keep {} → every item shown
  }, [])
  return <CapsContext.Provider value={caps}>{children}</CapsContext.Provider>
}

// Returns true unless the capability is explicitly false (fail-open).
export function useCapability(key?: string): boolean {
  const caps = useContext(CapsContext)
  if (!key) return true
  return caps[key] !== false
}

export function useCapabilities(): Capabilities {
  return useContext(CapsContext)
}
```

- [ ] **Step 2: Wrap in `conditional-layout.tsx`**
Import `CapabilitiesProvider` and wrap the shell branch:
```tsx
return (
  <CapabilitiesProvider>
    <SidebarProvider>
      <AppSidebar />
      {/* ...children... */}
    </SidebarProvider>
  </CapabilitiesProvider>
)
```
(Leave the `noShell` / `/login` branch unchanged.)

- [ ] **Step 3: Tag + filter nav items in `app-sidebar.tsx`**
Add a `capability` field to the component-gated items in `mainSections` (leave core items without the field):
- Ingestion `/connectors` → `capability: "connectors"`
- Streaming `/streaming` → `capability: "streaming"`
- Transforms `/pipelines` → `capability: "pipelines"`
- Catalog `/catalog` → `capability: "catalog"`
- Query Lab `/query` → `capability: "query"`
- Notebooks `/notebooks` → `capability: "notebooks"`
- Experiments `/experiments` → `capability: "experiments"`
- Dashboards `/dashboards` → `capability: "dashboards"`
- (Knowledge, Services, System, Storage, Governance, Settings, Documentation, Guides → NO capability key = always shown)

Then in the render loop (lines ~112-139), skip items whose capability is false. Since the sidebar is a client component, call the hook at the top and filter:
```tsx
const caps = useCapabilities()
// ...
{section.items
  .filter((item) => item.capability === undefined || caps[item.capability] !== false)
  .map((item) => ( /* existing item render */ ))}
```
Apply the same `.filter(...)` to `bottomItems` if any item gets a capability key (none do here). If a whole section ends up empty after filtering, skip rendering that section's header.

- [ ] **Step 4: (Optional) page guard** — skip; nav-hide is sufficient for this task. Directly-navigated hidden pages still render with their existing graceful error handling.

- [ ] **Step 5: Verify**
```bash
cd frontend && npx tsc --noEmit
```
Expected: passes. Inspect: with `caps = {}` (fetch failed / full deploy) every item shows (fail-open); with lakehouse caps false, only core items render.

- [ ] **Step 6: Commit**
```bash
git add frontend/lib/capabilities.ts frontend/components/conditional-layout.tsx frontend/components/app-sidebar.tsx
git commit -m "feat(ui): capability-gated nav — hide pages whose backend component is disabled"
```

---

## Task 4: CI verify + PR

- [ ] **Step 1: Push branch + open PR** so CI runs: backend pytest (capabilities tests), frontend tsc, Helm render (all profiles incl. values-foundation with FEATURE_* = false).
- [ ] **Step 2: Fix any CI failure; do not complete until all green.**

---

## Self-Review

**Spec coverage:** capabilities endpoint (T1) + Helm flag injection (T2) + frontend nav gating (T3) + CI (T4). Backward-compat via default-true throughout (unset env, missing cap, fetch error all → feature shown). Feature→component mapping consistent between T1 (backend compute) and T3 (nav item keys).

**Placeholder note:** none — T3 now names exact files (`frontend/lib/capabilities.ts`, `conditional-layout.tsx`, `app-sidebar.tsx`) and the per-item capability keys; the gating logic and fail-open rule are fully specified.

**Consistency:** `FEATURE_<COMPONENT>` names identical between T1 `_feat` reads and T2 Helm env. Feature keys (`catalog/query/pipelines/streaming/experiments/notebooks/lineage/...`) identical between T1 output and T3 nav-item `capability` keys.
