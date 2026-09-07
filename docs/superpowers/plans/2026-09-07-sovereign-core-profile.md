# Sovereign Core Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A supported, lean on-prem profile — `helm/datapond/values-sovereign-core.yaml` — that renders only the Portable Core plus in-cluster MinIO and a local model path, with all eight OSS add-ons off, and is pinned by the same tests and CI loops as the other profiles.

**Architecture:** The file is the on-prem twin of `values-foundation.yaml`: same core five (backend, frontend, postgres, litellm, valkey), same eleven explicit `enabled: false` blocks minus `minio` and `ollama` which turn on, `storage.endpoint: minio:9000`, `ai.provider: ollama`, `ai.egressPolicy: local-only`, and `ollama.embedModel: bge-m3` paired with `ai.embedDim: 1024`. Profile identity `sovereign-core / supported-starter`. Nothing in the chart templates changes; the existing `addonState` helper and the Ollama LiteLLM init job do the wiring.

**Tech Stack:** Helm 3, existing chart templates, `helm template` offline rendering in `backend/tests/test_helm_*.py`, GitHub Actions `helm-lint` job.

**Spec:** `docs/superpowers/specs/2026-09-07-positioning-gap-closure-design.md` §4

## Global Constraints

- The eight add-on keys (`airflow, spark, polaris, risingwave, openmetadata, jupyter, mlflow, trino`) must be stated **explicitly `false`** so the offline render is deterministic (`templates/_addons.tpl:94-110`: unset means "preserve if running").
- `backend/tests/test_helm_addon_defaults.py:494-502` asserts every `values-*.yaml` in the chart is listed in `PROFILE_EXPECTATIONS`; the new file must be added there.
- `backend/tests/test_helm_values_duplicate_keys.py`: no top-level key twice.
- CI `.github/workflows/ci.yml:438-445` renders a fixed list of profiles; add the new one. Lines 499 and 544-546 loop over profiles for weak-credential and image-tag checks; add it there too.
- `ollama.embedLitellmName` must equal `ai.embedModel` (both default `"embed"`), and the model's dimension must equal `ai.embedDim` (`bge-m3` = 1024).
- `SUPPORT.md`'s `<!-- unsupported-addons -->` block must not gain prose bullets (`tests/test_capability_support_tiers.py:11-25` parses it).
- Run Helm tests from `backend/`: `python3.12 -m pytest tests/test_helm_addon_defaults.py tests/test_helm_values_duplicate_keys.py -q` (needs `helm` on PATH).
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PQW9stoiSQnnohhnBCDEvL
  ```

---

### Task 1: The values file, pinned by the add-on render test

**Files:**
- Create: `helm/datapond/values-sovereign-core.yaml`
- Modify: `backend/tests/test_helm_addon_defaults.py:481-490` (`PROFILE_EXPECTATIONS`)
- Test: `backend/tests/test_helm_sovereign_core.py`

**Interfaces:**
- Produces: profile id `sovereign-core`, label `Sovereign Core`, maturity `supported-starter`.

- [ ] **Step 1: Write the failing tests**

Add the row to `PROFILE_EXPECTATIONS` in `test_helm_addon_defaults.py`:

```python
    "values-sovereign-core.yaml": frozenset(),
```

Then create:

```python
# backend/tests/test_helm_sovereign_core.py
"""values-sovereign-core.yaml renders the Portable Core plus MinIO and Ollama, nothing
else, and identifies itself as a supported starter. Offline render, no cluster."""
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm" / "datapond"
VALUES = CHART / "values-sovereign-core.yaml"


def _render():
    r = subprocess.run(["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
                        "--values", str(VALUES)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _names(manifest, kind):
    return set(re.findall(rf"\nkind: {kind}\nmetadata:\n\s*name: (\S+)\n", manifest))


def test_profile_identity():
    v = yaml.safe_load(VALUES.read_text())
    p = v["product"]["profile"]
    assert p["id"] == "sovereign-core"
    assert p["label"] == "Sovereign Core"
    assert p["maturity"] == "supported-starter"


def test_every_addon_is_explicitly_false():
    v = yaml.safe_load(VALUES.read_text())
    for k in ("airflow", "spark", "polaris", "risingwave", "openmetadata", "jupyter",
              "mlflow", "trino", "vllm"):
        assert v[k]["enabled"] is False, k


def test_local_paths_are_on_and_consistent():
    v = yaml.safe_load(VALUES.read_text())
    assert v["minio"]["enabled"] is True
    assert v["ollama"]["enabled"] is True
    assert v["storage"]["endpoint"] == "minio:9000"
    assert v["ai"]["provider"] == "ollama"
    assert v["ai"]["egressPolicy"] == "local-only"
    assert v["ai"]["embedDim"] == 1024
    assert v["ollama"]["embedModel"] == "bge-m3"
    assert v["ollama"].get("embedLitellmName", "embed") == v["ai"].get("embedModel", "embed")
    assert "catalog" not in v, "a catalog backend would turn Sources/Catalog back on"


def test_render_has_core_minio_ollama_and_no_addons():
    m = _render()
    deployments = _names(m, "Deployment")
    statefulsets = _names(m, "StatefulSet")
    assert {"backend", "frontend", "litellm"} <= deployments
    assert "minio" in deployments | statefulsets
    assert "ollama" in deployments | statefulsets
    for absent in ("trino", "polaris", "airflow-webserver", "risingwave-frontend",
                   "openmetadata-server", "jupyterlab", "mlflow", "spark-master"):
        assert absent not in deployments | statefulsets, absent


def test_render_hides_data_navigation():
    m = _render()
    for flag in ("FEATURE_TRINO", "FEATURE_POLARIS", "FEATURE_GLUE", "FEATURE_ATHENA"):
        assert re.search(rf"name: {flag}\n\s+value: \"false\"", m), flag
    assert re.search(r"name: FEATURE_OLLAMA\n\s+value: \"true\"", m)
    assert re.search(r"name: AI_EGRESS_POLICY\n\s+value: \"local-only\"", m)
```

If `yaml` (PyYAML) is not importable in the test env, read the file with `helm show values --values` instead, or add `pyyaml` to the test requirements — check how `test_helm_addon_defaults.py:84-98` reads values and reuse that approach.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3.12 -m pytest tests/test_helm_sovereign_core.py tests/test_helm_addon_defaults.py -q`
Expected: FAIL — `FileNotFoundError` on the values file; `test_every_profile_in_the_chart_is_in_the_table` fails until the file exists.

- [ ] **Step 3: Write the values file**

```yaml
# helm/datapond/values-sovereign-core.yaml
# Sovereign Core — the on-prem twin of values-foundation.yaml.
#
# Portable Core (backend, frontend, PostgreSQL/pgvector, LiteLLM, Valkey) plus in-cluster
# MinIO for objects and Ollama for a local embedding + chat model. No catalog, no query
# engine, no OSS add-on: Sources/Catalog/Analytics stay hidden, and nothing leaves the
# cluster (ai.egressPolicy: local-only). Everything here is inside the supported scope
# named in SUPPORT.md; values-onprem.yaml remains the extended community stack.
#
# Install:
#   helm upgrade --install datapond helm/datapond -n datapond --create-namespace \
#     -f helm/datapond/values-sovereign-core.yaml
#
# Embedding dimension: ai.embedDim MUST equal the embedding model's output. bge-m3 is
# 1024-d and matches ai_chunks vector(1024). Choosing a different model later is a new
# deployment or a full re-embed, never a version bump.

product:
  profile:
    id: sovereign-core
    label: Sovereign Core
    description: Self-hosted Portable Core with local model and storage, no data add-ons.
    maturity: supported-starter
    topology: self-hosted-kubernetes

global:
  externalScheme: https

# ── Object storage: in-cluster MinIO, addressed through the S3 API ───────────────
storage:
  provider: s3
  endpoint: "minio:9000"
  region: "us-east-1"
  bucket: datapond

minio:
  enabled: true
  auth:
    rootUser: datapond
    rootPassword: ""       # empty ⇒ Helm generates and preserves (templates/secrets.yaml)
  persistence:
    enabled: true
    size: 100Gi

# ── Model path: local Ollama registered into LiteLLM by the post-install job ────
ai:
  provider: ollama
  llmEndpoint: ""
  llmModel: "default"
  egressPolicy: "local-only"
  embedModel: "embed"
  embedDim: 1024

litellm:
  enabled: true
  config:
    model_list: []         # seeded by templates/litellm-ollama-init-job.yaml

ollama:
  enabled: true
  defaultModel: "qwen2.5-coder:7b"
  litellmModelName: "default"
  embedModel: "bge-m3"     # 1024-d — must match ai.embedDim
  embedLitellmName: "embed"
  resources:
    requests: { cpu: 500m, memory: 4Gi }
    limits: { cpu: 4000m, memory: 8Gi }
  persistence:
    enabled: true
    size: 20Gi

vllm:
  enabled: false

# ── Core ─────────────────────────────────────────────────────────────────────────
backend:
  enabled: true
frontend:
  enabled: true
valkey:
  enabled: true
postgres:
  enabled: true
  resources:
    requests: { cpu: 500m, memory: 1Gi }
    limits: { cpu: 1000m, memory: 2Gi }
  persistence:
    enabled: true
    size: 50Gi
  auth:
    database: datapond
    username: datapond
    password: ""           # empty ⇒ Helm generates and preserves

# ── Governance: RLS engine on, so table policies apply if tables are ever added ──
governance:
  rls:
    enabled: true
    defaultDeny: false

# ── Every add-on explicitly off (unset would mean "preserve if already running") ─
trino:
  enabled: false
spark:
  enabled: false
polaris:
  enabled: false
airflow:
  enabled: false
mlflow:
  enabled: false
risingwave:
  enabled: false
openmetadata:
  enabled: false
jupyter:
  enabled: false

networkPolicy:
  enabled: true
```

Before finalising, diff the key names against `values-foundation.yaml` and `values-onprem.yaml` (`ollama.*`, `minio.*`, `postgres.*`, `storage.*`) so every key here exists in base `values.yaml`; drop any key that does not.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python3.12 -m pytest tests/test_helm_sovereign_core.py tests/test_helm_addon_defaults.py tests/test_helm_values_duplicate_keys.py tests/test_helm_storage_class_rendering.py -q`
Expected: PASS. If `test_a_rendered_addon_keeps_its_dependencies` or the storage-class test flags MinIO/Ollama specifics (storage class key, ingress path), fix the values to match what `values-onprem.yaml` sets for the same component.

- [ ] **Step 5: Commit**

```bash
git add helm/datapond/values-sovereign-core.yaml backend/tests/test_helm_sovereign_core.py backend/tests/test_helm_addon_defaults.py
git commit -m "feat(helm): values-sovereign-core — supported on-prem Portable Core with MinIO and Ollama"
```

---

### Task 2: CI renders and checks the new profile

**Files:**
- Modify: `.github/workflows/ci.yml:438-445` (render loop), `:499` (weak-credential loop), `:544-546` (image-tag loop), and the `check()` FEATURE-vs-workload calls at `:457-476`

- [ ] **Step 1: Add the profile to the render loop**

At `:440`, change the `for v in ...` list to append `values-sovereign-core`:

```bash
for v in values-quicktest values-onprem values-aws values-dev values-prod values-foundation values-prod-single values-sovereign-core; do
```

- [ ] **Step 2: Add FEATURE checks**

Next to the existing `check values-foundation.yaml trino FEATURE_TRINO` style lines (`:457-476`), add:

```bash
check values-sovereign-core.yaml trino FEATURE_TRINO
check values-sovereign-core.yaml polaris FEATURE_POLARIS
check values-sovereign-core.yaml ollama FEATURE_OLLAMA
```

(`check` compares the rendered FEATURE flag with whether the workload rendered; the helper is defined in the same job.)

- [ ] **Step 3: Add to the credential and image-tag loops**

At `:499` append `sovereign-core` to the profile list (`"" prod onprem foundation sovereign-core`); at `:544-546` likewise (`"" prod onprem quicktest foundation aws sovereign-core`). Match the exact token format the loops expect (with or without the `values-` prefix, as the neighbours are written).

- [ ] **Step 4: Validate the workflow locally where possible**

Run: `helm template datapond helm/datapond --values helm/datapond/values-sovereign-core.yaml >/dev/null && echo ok`
Expected: `ok`. Run `helm lint helm/datapond --values helm/datapond/values-sovereign-core.yaml` and expect no ERROR lines.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(helm): render, lint and flag-check values-sovereign-core"
```

---

### Task 3: Documents — profile matrix, profile guide, README, SUPPORT

**Files:**
- Create: `docs/SOVEREIGN_CORE_PROFILE.md`
- Modify: `docs/DEPLOYMENT_PROFILES.md:7-14,18-26`, `docs/README.md` (docs table), `README.md` (profiles table), `SUPPORT.md:35-43`, `CLAUDE.md` (profile table), `docs/POSITIONING_FIT_AUDIT.md` §7.1 축 D

- [ ] **Step 1: Profile guide**

Write `docs/SOVEREIGN_CORE_PROFILE.md` with the same headings as `docs/FOUNDATION_PROFILE.md`:

```markdown
# Sovereign Core

> File: `helm/datapond/values-sovereign-core.yaml`. The on-prem twin of the Portable Core · AWS starter.

## What runs

| Component | Role |
|---|---|
| Backend | Knowledge/RAG, authentication, governance, storage and AI APIs |
| Frontend | Capability-aware operator UI |
| PostgreSQL + pgvector | Application state, collections, chunks, vectors |
| LiteLLM | Logical model gateway to the local model |
| Valkey | Cache/session support |
| MinIO | S3-API object storage, in-cluster |
| Ollama | Local embedding (`bge-m3`, 1024-d) and chat (`qwen2.5-coder:7b`) models |

## What does not run

trino, spark, polaris, airflow, mlflow, risingwave, openmetadata, jupyter, vllm — all stated `false`.
No catalog backend, so Sources / Catalog / Analytics stay hidden. Nothing leaves the cluster:
`ai.egressPolicy: local-only`.

## Core workflow

Create a collection → ingest text or MinIO objects → search and cited answers → issue a
service-account key → call `/api/ai/rag` from your agent → review Governance.

## Prerequisites

Kubernetes + Helm; a node with at least 16 GB RAM and 8 vCPU for Ollama's defaults; a
storage class for three PVCs (postgres 50Gi, minio 100Gi, ollama 20Gi). GPU optional.

## Install

    helm upgrade --install datapond helm/datapond -n datapond --create-namespace \
      -f helm/datapond/values-sovereign-core.yaml

First start pulls the two Ollama models; the LiteLLM init job registers them as `embed`
and `default`.

## Model configuration

`ai.embedDim` must equal the embedding model's dimension. `bge-m3` is 1024-d. To use
another model, set `ollama.embedModel` and `ai.embedDim` **before the first ingest**;
changing the dimension later requires recreating `ai_chunks` and re-embedding.
To use an external OpenAI-compatible server instead of Ollama, set `ollama.enabled: false`,
`ai.llmEndpoint`, and a hand-written `litellm.config.model_list` with `embed`, `default`,
`chat` entries.

## Security boundary

Same as the AWS starter: application-level collection ACL, SQL-rewrite RLS when tables
exist, PII masking, append-only audit. Add-ons are absent rather than disabled-but-present.

## When to choose another profile

You need Iceberg tables, Trino/Polaris, or any OSS add-on: `values-onprem.yaml`
(community, extended). You are on AWS: `values-foundation.yaml` or `values-prod-single.yaml`.
```

- [ ] **Step 2: Matrix rows and tables**

- `docs/DEPLOYMENT_PROFILES.md`: add a "choose when" row `| Sovereign Core | You need the smallest self-hosted governed RAG starter with no data egress | You need Catalog/SQL or any OSS add-on |` and a matrix row `| values-sovereign-core.yaml | Sovereign Core | in-cluster PostgreSQL/pgvector | MinIO + Ollama | none | disabled | supported starter |`. Add a `## Sovereign Core` section after the foundation section pointing at the new guide.
- `README.md` profiles table: add `| values-sovereign-core.yaml | **Sovereign Core** | On-prem twin of the AWS starter: core five + in-cluster MinIO + Ollama; no catalog/query, no add-ons, no egress |` and mention it in the Quick start as the on-prem alternative.
- `docs/README.md`: add `[SOVEREIGN_CORE_PROFILE.md](SOVEREIGN_CORE_PROFILE.md) | values-sovereign-core.yaml Sovereign Core 상세` to the 먼저 읽을 문서 table, and in the Capability 상태 table change the `S3/Bedrock adapter` row's Portable Core cell to `✅ AWS starter · MinIO/Ollama in Sovereign Core`.
- `CLAUDE.md` profile table: add the row.
- `docs/PRODUCT_CONCEPT.md` 배포 프로필: list three files, not two.

- [ ] **Step 3: SUPPORT.md scope sentence**

Change the supported-scope paragraph (`SUPPORT.md:35-43`) to:

```markdown
The **Portable Core** path — ingest, embed, retrieve, rerank, cited answers, plus
access control, PII handling, audit and spend — on the two starters that run it:
the **AWS Single-Node Reference** / `values-foundation.yaml`, and the self-hosted
**Sovereign Core** (`values-sovereign-core.yaml`: in-cluster MinIO and Ollama).
```

Do not touch the `<!-- unsupported-addons -->` block.

- [ ] **Step 4: Flip the audit rows**

In `docs/POSITIONING_FIT_AUDIT.md` §7.1 축 D: "lean 온프렘 코어 프로필" → ○ (`helm/datapond/values-sovereign-core.yaml`), "온프렘 코어의 지원 티어" → ○ (`SUPPORT.md`, maturity `supported-starter`).

- [ ] **Step 5: Verify and commit**

Run: `cd backend && python3.12 -m pytest tests/test_capability_support_tiers.py tests/test_helm_sovereign_core.py -q`
Expected: PASS (the support-tier test still finds exactly eight add-ons between the markers).

```bash
git add docs/SOVEREIGN_CORE_PROFILE.md docs/DEPLOYMENT_PROFILES.md docs/README.md README.md SUPPORT.md CLAUDE.md docs/PRODUCT_CONCEPT.md docs/POSITIONING_FIT_AUDIT.md
git commit -m "docs(profiles): Sovereign Core is the supported on-prem starter"
```
