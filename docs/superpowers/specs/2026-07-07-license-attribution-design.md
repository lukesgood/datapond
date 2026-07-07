# LICENSE & Third-Party Attribution (P0-2) — Design

**Date**: 2026-07-07
**Status**: Design approved (pre-implementation)
**Context**: The repo currently ships with ZERO licensing artifacts — no LICENSE, NOTICE, or COPYING anywhere, no license headers, no attribution for bundled OSS. PRODUCT_CONCEPT.md commits to an Open Core model (Community = open source; Enterprise = SAML/LDAP·multi-tenancy·advanced RBAC·SLA; AWS Marketplace distribution).

## 1. Decisions (confirmed)

| Decision | Choice |
|---|---|
| Community core license | **Apache-2.0** — matches the "100% 오픈소스" concept claim and the Apache ecosystem DataPond builds on (Polaris/Trino/Spark/Airflow) |
| Edition boundary | **Repo = Community; Enterprise = future only.** Everything currently in the repo (incl. already-built LDAP #41, RLS engine #13, AI governance) becomes Apache-2.0. Enterprise features (SSO/SAML P0-3, multi-tenancy, marketplace billing, SLA) are built under `/ee` with a commercial license (GitLab pattern) |
| Scope depth | **Files + CI license gate** — licensing artifacts plus a CI tripwire on direct dependencies; no SPDX headers on source files |
| Attribution strategy | **Hand-curated THIRD_PARTY_NOTICES** from the audited inventory + CI denylist gate (Approach A). NOT fully-generated attribution (unreviewable churn) and NOT image SBOMs (blocked on P0-4 tag pinning) |
| MinIO (AGPL-3.0) / Elasticsearch (ELv2/SSPL) | **Document, don't swap.** Both are unmodified upstream images pulled at deploy time and run by the customer (aggregation, not derivation); both are disabled in the AWS-native default profiles. Notices file + INSTALLATION procurement note |

## 2. Licensing exposure inventory (audited 2026-07-07)

Current state: no LICENSE/NOTICE/COPYING anywhere; no license headers; no attribution.

**Copyleft / source-available flags:**
- `minio/minio` + `minio/mc` — **AGPL-3.0** (deployed images; onprem/dev/quicktest profiles only — base/foundation/aws use native S3)
- Elasticsearch 8.10.2 (via OpenMetadata) — **Elastic License 2.0 / SSPL dual** (not OSI open source)
- `busybox:1.36` init containers — GPL-2.0 (unmodified utility; mere aggregation)
- Backend pip: `psycopg2-binary`, `ldap3` — **LGPL-3.0** (weak copyleft: attribution + relink freedom; acceptable, allowlisted)
- Frontend npm: `elkjs` — **EPL-2.0** (weak copyleft; unmodified; acceptable, allowlisted)

**Apache-2.0 NOTICE-propagation surface (attribution required):** images — Airflow, Spark, Trino, Polaris (+admin-tool), MLflow, RisingWave, OpenMetadata, vLLM; pip — kubernetes, boto3, pyiceberg, pyarrow, asyncpg, bcrypt, python-multipart, trino, mlflow-skinny, cryptography(dual); npm — class-variance-authority.

**Permissive remainder:** pgvector/PostgreSQL (PostgreSQL License), Valkey (BSD-3), LiteLLM/Ollama (MIT), DuckDB (MIT), jupyter/scipy-notebook base (BSD-3 + bundled scientific stack), curl image (MIT/X-style), nearly all npm deps (MIT/ISC).

**Vendored source:** shadcn/ui components copied into `frontend/components/ui/*.tsx` (MIT — copied by design per shadcn's distribution model; no headers today). No other vendored third-party code found (pii_ko.py, datapond_lake.py, iceberg_helper.py are first-party originals).

## 3. Deliverables

### 3a. Root licensing files
- **`LICENSE`** — verbatim Apache License 2.0. Copyright line: `Copyright 2026 DataPond contributors`. ⚠️ Open placeholder: swap in the legal entity name when one exists (the only intentionally-deferred value in this design).
- **`NOTICE`** — minimal Apache-convention notice (product name, copyright, pointer to THIRD_PARTY_NOTICES.md, `/ee` scope carve-out). Kept short and stable — downstream Apache users must propagate this file.
- **`THIRD_PARTY_NOTICES.md`** — the curated inventory in four sections mirroring §2: (1) deployed container images (table: image → project → license → profiles where enabled) with a prominent copyleft/source-available callout and the aggregation-not-derivation statement; (2) backend Python deps (full requirements.txt table + LGPL note); (3) frontend npm deps (+ Apache/EPL exceptions); (4) vendored source (shadcn/ui, with upstream MIT license text included).

### 3b. `/ee` scaffold (edition boundary)
- **`ee/README.md`** — states the convention: everything outside `/ee` is Apache-2.0; code under `/ee` is source-available under the DataPond Commercial License, requires a valid subscription; first planned tenant is SSO/SAML (P0-3).
- **`ee/LICENSE`** — short plain-English commercial-license stub, explicitly marked `⚠️ placeholder — requires legal counsel review before any Enterprise release`.
- The root `LICENSE` Apache text stays pristine; the `/ee` carve-out is stated in `NOTICE` and `README` only.

### 3c. Docs alignment
- **`README.md`** — new "License" section: Apache-2.0 core, `/ee` exception, THIRD_PARTY_NOTICES pointer.
- **`docs/PRODUCT_CONCEPT.md`** — tighten the Open Core block: Community = Apache-2.0 (this repo, explicitly including LDAP/RLS since they are already open); Enterprise (`/ee`) = SSO/SAML, multi-tenancy, marketplace billing, SLA.
- **`docs/FOUNDATION_PROFILE.md`** — "License considerations for regulated procurement" note (docs/INSTALLATION.md no longer exists post-pivot): AGPL (MinIO) and ELv2 (Elasticsearch via OpenMetadata) apply only to onprem/dev profiles; AWS-native profiles pull neither; OpenMetadata can be disabled if ELv2 is a procurement blocker.

### 3d. CI license gate (direct-deps tripwire)
New step in `.github/workflows/ci.yml`:
- **Python**: `pip-licenses` over the installed `backend/requirements.txt` set (CI py3.11 env), fail on license names matching denylist `GPL|AGPL|SSPL|Elastic|BSL|Commons Clause|UNKNOWN`; allowlist file `.license-allowlist.txt` carries the accepted entries (`psycopg2-binary` LGPL-3.0, `ldap3` LGPL-3.0) so the gate is green on day one and any NEW copyleft dep fails loudly.
- **npm**: `license-checker --production --failOn '<denylist>'` in `frontend/`, with `elkjs@EPL-2.0` allowlisted (`--excludePackages`).
- Scope: direct dependency manifests only. Container-image SBOM scanning is explicitly out of scope until P0-4 pins image tags.

## 4. Testing & failure modes

- Gate green on the current tree proves the allowlist is exact. During implementation, a deliberate red-path check (temporarily add a GPL-licensed dep locally, observe CI-style failure, remove) verifies the gate actually trips — performed and reverted, never committed.
- This PR changes no runtime behavior: files + CI only. Backend/frontend test suites are unaffected.
- Failure mode of the gate itself: a dep whose license metadata is missing reports UNKNOWN → fails → resolved by either fixing metadata upstream pin or adding a reviewed allowlist entry with a comment. UNKNOWN-fails-closed is intentional.

## 5. Out of scope

SPDX headers on first-party source; container-image SBOMs (post-P0-4); replacing MinIO or Elasticsearch; final commercial-license legal text (stub marked for counsel); CLA/DCO contributor policy (no public launch yet); `requirements-dev.txt` and other non-shipped dev tooling (gate covers shipped deps only).
