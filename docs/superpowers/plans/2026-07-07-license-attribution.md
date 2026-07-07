# LICENSE & Third-Party Attribution (P0-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the repo its licensing foundation — Apache-2.0 LICENSE + NOTICE + curated THIRD_PARTY_NOTICES, the `/ee` commercial-edition scaffold, doc alignment, and a CI tripwire that fails on newly-introduced copyleft dependencies.

**Spec:** `docs/superpowers/specs/2026-07-07-license-attribution-design.md`

**Architecture:** Pure files + CI — no runtime code changes anywhere. Attribution is hand-curated from the audited inventory in the spec (§2); the CI gate checks DIRECT dependency manifests only (requirements.txt names via `pip-licenses --packages`, `license-checker --production`) against a denylist regex with a committed allowlist file.

**Tech Stack:** Apache-2.0 text, Markdown, GitHub Actions, pip-licenses, license-checker (npx).

## Global Constraints

- Community core = **Apache-2.0**; everything outside `/ee` is Apache-2.0; `/ee` is a commercial-license stub only (no code moves into it).
- Copyright line everywhere: `Copyright 2026 DataPond contributors` (entity name is an intentionally deferred value — never invent a company name).
- Root `LICENSE` is the VERBATIM canonical Apache-2.0 text — no additions, no header edits.
- CI denylist regex (exact): `GPL|AGPL|SSPL|Elastic|BSL|Commons Clause|UNKNOWN` (case-insensitive). Allowlist entries: `psycopg2-binary`, `ldap3` (LGPL-3.0, pip), `elkjs` (EPL-2.0, npm). UNKNOWN fails closed.
- Gate covers shipped direct deps only: `backend/requirements.txt` and `frontend/package.json` `dependencies` — NOT requirements-dev.txt, NOT devDependencies, NOT container images (deferred to post-P0-4).
- No runtime behavior changes; backend/frontend test suites must be untouched and unaffected.
- helm/CI conventions: CI is the authoritative gate; work on a feature branch `feat/license-attribution-p0-2`; squash-merge PR at the end.

---

### Task 1: Root licensing files (LICENSE, NOTICE, THIRD_PARTY_NOTICES.md)

**Files:**
- Create: `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` (repo root)

**Interfaces:**
- Produces: the three root files that Task 2 (`/ee` carve-out wording), Task 3 (README/doc pointers), and Task 4 (allowlist rationale) reference by exact name.

- [ ] **Step 1: Fetch the canonical Apache-2.0 text**

```bash
cd /Users/luke/datapond
curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE
# Verify integrity: canonical text is ~11k chars and starts with the license title
head -2 LICENSE   # expect: "                                 Apache License" / "                           Version 2.0, January 2004"
wc -c LICENSE     # expect: 11358
```

If curl fails (no egress), copy the text verbatim from any Apache-2.0 project already known to the environment — but verify the `wc -c` = 11358.

- [ ] **Step 2: Create `NOTICE`**

```
DataPond — AWS-Native Data Foundation for AI Apps
Copyright 2026 DataPond contributors

This product is licensed under the Apache License, Version 2.0 (see LICENSE),
with the exception of code under the /ee directory, which is source-available
under the DataPond Commercial License (see ee/LICENSE).

This product includes and deploys third-party open source software.
See THIRD_PARTY_NOTICES.md for the full inventory and license texts.
```

- [ ] **Step 3: Create `THIRD_PARTY_NOTICES.md`** with exactly this content:

````markdown
# Third-Party Notices

DataPond's own code is licensed under Apache-2.0 (see [LICENSE](LICENSE)), except
`/ee` (see [ee/LICENSE](ee/LICENSE)). This file inventories the third-party software
DataPond depends on or deploys, grouped by how it is bundled. Inventory audited
2026-07-07 against `helm/datapond/values.yaml`, `backend/requirements.txt`, and
`frontend/package.json`.

## ⚠️ Copyleft & source-available components

The following deployed components carry non-permissive licenses. DataPond does NOT
link against, modify, or redistribute them — they are unmodified upstream container
images pulled at deploy time and operated by the deploying customer (aggregation,
not derivation). Their licenses govern those components, not DataPond's code.

| Component | License | Where it applies |
|---|---|---|
| MinIO (`minio/minio`, `minio/mc`) | **AGPL-3.0** | onprem / dev / quicktest profiles only — base, foundation, and aws profiles use native Amazon S3 and pull no MinIO image |
| Elasticsearch 8.x (via OpenMetadata) | **Elastic License 2.0 / SSPL** (source-available, not OSI open source) | Profiles with OpenMetadata enabled; disabled in the foundation profile. Set `openmetadata.enabled: false` if ELv2 is a procurement blocker |
| BusyBox (init containers) | GPL-2.0 | Unmodified standalone utility image (mere aggregation) |

**Procurement note for regulated environments:** the AWS-native profiles
(`values-foundation.yaml`, `values-aws.yaml`) deploy neither MinIO nor Elasticsearch.

## 1. Deployed container images

| Image | Project | License |
|---|---|---|
| `pgvector/pgvector:pg16`, `postgres:16-alpine` | PostgreSQL + pgvector | PostgreSQL License |
| `valkey/valkey:7.2.5` | Valkey | BSD-3-Clause |
| `trinodb/trino` | Trino | Apache-2.0 |
| `apache/spark:3.5.8-python3` | Apache Spark | Apache-2.0 |
| `apache/airflow:2.8.1` | Apache Airflow | Apache-2.0 |
| `ghcr.io/mlflow/mlflow:v2.10.0` | MLflow | Apache-2.0 |
| `apache/polaris:1.4.0`, `apache/polaris-admin-tool` | Apache Polaris | Apache-2.0 |
| `risingwavelabs/risingwave:v1.7.0` | RisingWave (core) | Apache-2.0 |
| `openmetadata/server:1.3.1` | OpenMetadata | Apache-2.0 |
| `ghcr.io/berriai/litellm` | LiteLLM | MIT |
| `ollama/ollama` | Ollama | MIT |
| `vllm/vllm-openai` | vLLM | Apache-2.0 |
| `jupyter/scipy-notebook` (base of `datapond/jupyter`) | Jupyter Docker Stacks | BSD-3-Clause (bundles a broad BSD/PSF/Apache scientific-Python stack) |
| `curlimages/curl:8.10.1` | curl | curl license (MIT/X-style) |
| `minio/minio`, `minio/mc` | MinIO | AGPL-3.0 (see callout above) |
| `docker.elastic.co/elasticsearch/elasticsearch:8.10.2` | Elasticsearch | ELv2 / SSPL (see callout above) |
| `busybox:1.36` | BusyBox | GPL-2.0 (see callout above) |

The `datapond/jupyter` image additionally installs: duckdb (MIT), pyiceberg (Apache-2.0),
boto3 (Apache-2.0), pandas (BSD-3-Clause), matplotlib (Matplotlib License, BSD-style),
seaborn (BSD-3-Clause), plotly (MIT), scikit-learn (BSD-3-Clause), xgboost (Apache-2.0),
lightgbm (MIT).

## 2. Backend Python dependencies (`backend/requirements.txt`)

| Package | License |
|---|---|
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| httpx | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| **psycopg2-binary** | **LGPL-3.0 (with exceptions)** — weak copyleft; used as an unmodified dynamically-imported library; attribution here satisfies its terms for this usage |
| sqlalchemy | MIT |
| redis (redis-py) | MIT |
| kubernetes | Apache-2.0 |
| trino (client) | Apache-2.0 |
| sqlglot | MIT |
| mlflow-skinny | Apache-2.0 |
| asyncpg | Apache-2.0 |
| pymysql | MIT |
| boto3 | Apache-2.0 |
| pandas | BSD-3-Clause |
| pyiceberg[pyarrow] | Apache-2.0 |
| pyarrow | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause (dual) |
| jinja2 | BSD-3-Clause |
| python-jose | MIT |
| bcrypt | Apache-2.0 |
| anthropic | MIT |
| **ldap3** | **LGPL-3.0** — weak copyleft; unmodified library usage; attribution here satisfies its terms for this usage |

## 3. Frontend npm dependencies (`frontend/package.json`, production)

All MIT unless noted: @base-ui/react, @monaco-editor/react, @types/dagre, clsx, dagre,
date-fns, next, react, react-dom, reactflow, recharts, shadcn, tailwind-merge,
tw-animate-css. Exceptions:

| Package | License |
|---|---|
| class-variance-authority | Apache-2.0 |
| lucide-react | ISC (Lucide License) |
| **elkjs** | **EPL-2.0** — weak copyleft; consumed as an unmodified npm package; source available upstream at https://github.com/kieler/elkjs |

## 4. Vendored source

`frontend/components/ui/*.tsx` are shadcn/ui components, copied into the repo by design
(shadcn's distribution model is copy-not-install). shadcn/ui is MIT-licensed:

```
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

No other third-party source is vendored in this repository.

---
Image tags reflect `helm/datapond/values.yaml` at audit time; several use moving tags
(`latest`) until image pinning (P0-4) lands, so exact bundled versions may drift.
````

- [ ] **Step 4: Verify and commit**

```bash
wc -c LICENSE            # 11358
ls LICENSE NOTICE THIRD_PARTY_NOTICES.md
git checkout -b feat/license-attribution-p0-2   # if not already on it
git add LICENSE NOTICE THIRD_PARTY_NOTICES.md
git commit -m "docs(license): Apache-2.0 LICENSE + NOTICE + curated third-party notices (P0-2)"
```

---

### Task 2: `/ee` commercial-edition scaffold

**Files:**
- Create: `ee/README.md`, `ee/LICENSE`

**Interfaces:**
- Consumes: `NOTICE`'s `/ee` carve-out wording (Task 1).
- Produces: the `ee/` convention that Task 3's README section references.

- [ ] **Step 1: Create `ee/README.md`**

```markdown
# DataPond Enterprise (`/ee`)

Everything in this repository OUTSIDE this directory is licensed under Apache-2.0
(see the root [LICENSE](../LICENSE)). Code under `/ee` is source-available under the
DataPond Commercial License (see [LICENSE](LICENSE) in this directory) and requires a
valid DataPond Enterprise subscription to use in production.

## Edition boundary

- **Community (Apache-2.0, everything outside `/ee`)**: the full AI data foundation —
  ingestion, vector/RAG, lakehouse integration, LDAP authentication, row-level security,
  AI cost governance, and all current features.
- **Enterprise (`/ee`, commercial)**: future additions — SSO (SAML/OIDC), multi-tenancy,
  AWS Marketplace billing integration, SLA-backed support.

This directory currently contains no code; its first planned tenant is the SSO
(SAML/OIDC) implementation (roadmap item P0-3).
```

- [ ] **Step 2: Create `ee/LICENSE`**

```
DataPond Commercial License (placeholder)

⚠️ PLACEHOLDER — this text requires review by legal counsel before any
Enterprise release. It establishes intent only.

Copyright 2026 DataPond contributors

Software in this directory ("Enterprise Software") is source-available: you may
view and modify it, but you may use it in production only with a valid DataPond
Enterprise subscription agreement. You may not redistribute the Enterprise
Software, offer it as a service to third parties, or circumvent license checks.

The Apache License 2.0 at the repository root does NOT apply to this directory.
```

- [ ] **Step 3: Commit**

```bash
git add ee/
git commit -m "docs(license): /ee commercial-edition scaffold (edition boundary convention)"
```

---

### Task 3: Docs alignment (README, PRODUCT_CONCEPT, FOUNDATION_PROFILE)

**Files:**
- Modify: `README.md` (append a License section at the end)
- Modify: `docs/PRODUCT_CONCEPT.md` (the `## 💰 비즈니스 모델 (요약)` block, ~line 198)
- Modify: `docs/FOUNDATION_PROFILE.md` (append a procurement note section)

- [ ] **Step 1: README.md — append at the end of the file**

```markdown

## 📄 License

DataPond is **Apache-2.0** ([LICENSE](LICENSE)) — everything in this repository except
the [`/ee`](ee/README.md) directory, which is reserved for commercially-licensed
Enterprise features ([ee/LICENSE](ee/LICENSE)). Third-party components and their
licenses are inventoried in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) —
regulated-procurement note included (the foundation profile deploys no AGPL/ELv2
components; see the notices file for per-profile details).
```

- [ ] **Step 2: PRODUCT_CONCEPT.md — replace the Open Core yaml block** (inside `## 💰 비즈니스 모델 (요약)`; current text says `Community: 100% 오픈소스, 고객 AWS 계정 셀프호스팅`):

```yaml
Open Core:
  Community: Apache-2.0 (이 저장소 전체, /ee 제외) — LDAP·RLS·AI 거버넌스 포함, 고객 AWS 계정 셀프호스팅
  Enterprise: /ee 디렉토리(상용 라이선스) — SSO(SAML/OIDC), 멀티테넌시, Marketplace 과금, SLA/지원
  AWS Marketplace: 종량제/구독 리스팅으로 도입 마찰 최소화
```

(keep the surrounding `Professional Services` block unchanged.)

- [ ] **Step 3: FOUNDATION_PROFILE.md — append section**

```markdown

## License considerations for regulated procurement

The **foundation profile** (`values-foundation.yaml`) deploys **no AGPL or
Elastic-licensed components**: object storage is native Amazon S3 (no MinIO) and
OpenMetadata/Elasticsearch is disabled. `values-aws.yaml` also uses native S3 (no
MinIO) but inherits OpenMetadata — and with it Elasticsearch 8.x (Elastic License
2.0/SSPL) — from the base chart defaults; set `openmetadata.enabled: false` there if
ELv2 is a procurement blocker. Profiles that enable MinIO (onprem/dev/quicktest/prod)
deploy it under AGPL-3.0 as an unmodified upstream image operated by you. Full
inventory: [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/PRODUCT_CONCEPT.md docs/FOUNDATION_PROFILE.md
git commit -m "docs(license): align README/product-concept/profile docs with Apache-2.0 open core"
```

---

### Task 4: CI license gate + allowlist + red-path check + PR

**Files:**
- Create: `.license-allowlist.txt` (repo root)
- Modify: `.github/workflows/ci.yml` (add a `license-gate` job after `frontend-check`, ~line 56)

**Interfaces:**
- Consumes: allowlist rationale documented in `THIRD_PARTY_NOTICES.md` (Task 1).

- [ ] **Step 1: Create `.license-allowlist.txt`** (grep -F patterns, one per line, NO comment lines — grep treats every line as a pattern):

```
psycopg2-binary
ldap3
elkjs
```

- [ ] **Step 2: Add the `license-gate` job to `.github/workflows/ci.yml`** (same indentation as existing jobs; mirror the `python-version` / `node-version` values used by `backend-tests` and `frontend-check` — read them from the file first):

```yaml
  license-gate:
    name: License gate (direct deps)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Python direct-deps license check
        working-directory: backend
        run: |
          pip install -q -r requirements.txt pip-licenses
          # Direct deps only: names from requirements.txt (strip extras/pins/comments)
          PKGS=$(sed -E 's/\[[^]]*\]//; s/[<>=!~;].*$//' requirements.txt | tr -d ' ' | grep -v '^#' | grep -v '^$' | tr '\n' ' ')
          pip-licenses --format=csv --packages $PKGS | tee /tmp/pylic.csv
          # Denylist (UNKNOWN fails closed); allowlisted packages (.license-allowlist.txt) are accepted-by-review
          viol=$(tail -n +2 /tmp/pylic.csv | grep -Ei 'GPL|AGPL|SSPL|Elastic|BSL|Commons Clause|UNKNOWN' | grep -vFf ../.license-allowlist.txt || true)
          if [ -n "$viol" ]; then echo "::error::Disallowed dependency licenses:"; echo "$viol"; exit 1; fi
          echo "OK: python direct deps clean"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: npm production-deps license check
        working-directory: frontend
        run: |
          npm ci --ignore-scripts
          npx --yes license-checker --production --csv | tee /tmp/jslic.csv
          viol=$(tail -n +2 /tmp/jslic.csv | grep -Ei 'GPL|AGPL|SSPL|Elastic|BSL|Commons Clause|UNKNOWN' | grep -vFf ../.license-allowlist.txt || true)
          if [ -n "$viol" ]; then echo "::error::Disallowed dependency licenses:"; echo "$viol"; exit 1; fi
          echo "OK: npm production deps clean"
```

- [ ] **Step 3: Local red-path + green-path verification** (python only — node/npm may not be available locally; CI is authoritative):

```bash
cd /Users/luke/datapond/backend
python3 -m pip install -q pip-licenses 2>/dev/null || pip3 install -q pip-licenses
# Green path against installed env (approximation of CI):
PKGS=$(sed -E 's/\[[^]]*\]//; s/[<>=!~;].*$//' requirements.txt | tr -d ' ' | grep -v '^#' | grep -v '^$' | tr '\n' ' ')
pip-licenses --format=csv --packages $PKGS 2>/dev/null | tail -n +2 | grep -Ei 'GPL|AGPL|SSPL|Elastic|BSL|Commons Clause|UNKNOWN' | grep -vFf ../.license-allowlist.txt || echo "GREEN: no violations"
# Red path: prove the pipeline trips on a synthetic violation
echo '"fakepkg","1.0","GPL v3"' | grep -Ei 'GPL|AGPL|SSPL|Elastic|BSL|Commons Clause|UNKNOWN' | grep -vFf ../.license-allowlist.txt && echo "RED: violation detected (expected)"
```

Expected: `GREEN: no violations` (or, if some local package is missing so pip-licenses reports it as absent, note it — CI installs the full set) and `RED: violation detected (expected)`.
Caveat: local python may not have all requirements installed (known pre-existing import issues); the packages that ARE resolvable must be clean. CI is the authoritative run.

- [ ] **Step 4: YAML validity + commit**

```bash
cd /Users/luke/datapond
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo CI-YAML-OK
git add .license-allowlist.txt .github/workflows/ci.yml
git commit -m "ci: license gate — deny new copyleft in direct deps (allowlist: LGPL psycopg2/ldap3, EPL elkjs)"
```

- [ ] **Step 5: Push + PR**

```bash
git push -u origin feat/license-attribution-p0-2
# PR via gh (token from git credential fill — no gh auth login):
export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
gh pr create --title "docs(license): Apache-2.0 open core + third-party attribution + CI license gate (P0-2)" --body "..."
```

PR body: Apache-2.0 LICENSE/NOTICE, curated THIRD_PARTY_NOTICES (AGPL/ELv2 callouts + procurement note), /ee scaffold (commercial stub marked for counsel), docs alignment, CI direct-deps license tripwire (denylist + allowlist). No runtime changes. Note the deferred values: legal entity name in copyright lines; commercial license text.

- [ ] **Step 6: CI green gate — fix any failures; done only when all green.** Likely failure mode: a pip package whose metadata reports a license string matching the denylist unexpectedly (e.g., dual-licensed or UNKNOWN) — resolve by verifying the actual license and, if acceptable, adding the package name to `.license-allowlist.txt` with a matching row added to THIRD_PARTY_NOTICES.md §2 (both in the same fix commit; report which packages needed this).

---

## Self-Review

**Spec coverage:** §3a root files → Task 1 (full file contents included); §3b /ee scaffold → Task 2; §3c docs (README/PRODUCT_CONCEPT/FOUNDATION_PROFILE) → Task 3; §3d CI gate → Task 4 (denylist regex + allowlist verbatim from spec); §4 red-path verification → Task 4 Step 3 (synthetic violation, never committed); §5 out-of-scope honored (no SPDX headers, no SBOM, no swaps, dev deps excluded via `--packages`/`--production`).

**Placeholder scan:** the two intentional placeholders (legal entity, commercial text) are spec-mandated deferred values, marked as such in the artifacts themselves. PR body "..." is followed by explicit content instructions. No TBDs.

**Consistency:** allowlist names match THIRD_PARTY_NOTICES flagged entries exactly (psycopg2-binary, ldap3, elkjs); `/ee` wording identical across NOTICE / ee/README / root README; denylist regex identical in both CI steps and the local red-path check.
