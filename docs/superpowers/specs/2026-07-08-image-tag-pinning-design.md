# Image-Tag Pinning (P0-4) — Design

**Date**: 2026-07-08
**Status**: Design approved (pre-implementation)
**Context**: 25 distinct container images; 9 already version-pinned; ~15 on moving tags (`:latest`, `main-latest`, floating base images, rolling `pg16`/`16-alpine`). No `@sha256` pins, no scan infra. Silent drift risk on every deploy. Unblocks the P0-2 image-SBOM and P0-3 docker-build-CI follow-ups.

## 1. Decisions (confirmed)

| Decision | Choice |
|---|---|
| Pin granularity | **Concrete version tags** — specific released versions, verified from upstream at implementation time. NOT `@sha256` digests (registry-resolution + multi-arch + air-gap cost too high for a P0) |
| First-party images | **Chart `appVersion`** (currently `2.3.0`) — datapond/{backend,frontend,jupyter} default to appVersion, keeping the "one tag, all profiles + air-gap bundle" property while making it a real version. Overridable (local dev, CD sha tags) |
| Adjacent scope | **Moving-tag CI guard only.** SBOM/trivy scanning and the docker `--target community\|enterprise` build check are separate follow-up PRs |
| Version policy | Drift-elimination only — pin to a version the current config already works with; NO major upgrades in this PR |

## 2. Third-party moving tags → concrete versions

Each pinned to a specific released version, verified against its registry/release page at implementation time (implementer records source URL + resolution date in the task report). Tag schemes:

| Image | Current | Refs | Pin scheme |
|---|---|---|---|
| `minio/minio` | `latest` | values.yaml:366; minio-deployment.yaml:33 (`\| default "latest"`) | `RELEASE.<date>` |
| `minio/mc` | `latest` | minio-bucket-init-job.yaml:18 | `RELEASE.<date>` (matched pair with minio) |
| `trinodb/trino` | `latest` | values.yaml:396 | integer version |
| `ghcr.io/berriai/litellm` | `main-latest` | values.yaml:717 | stable `v1.x.y` (or `-stable`) tag |
| `ollama/ollama` | `latest` | values.yaml:802 | `0.x.y` |
| `vllm/vllm-openai` | `latest` | values.yaml:849 | `v0.x.y` |
| `pgvector/pgvector` | `pg16` | values.yaml:110 | `0.x.y-pg16` (keep pg16 family) |
| `postgres` | `16-alpine` | polaris-bootstrap-job.yaml:40, litellm-deployment.yaml:100, polaris-deployment.yaml:26 | `16.x-alpine` (keep 16 major) |
| `busybox` | `1.36` | openmetadata-deployment.yaml:29,35,136,139 | `1.36.1` |

Constraints: pgvector stays pg16-family, postgres stays 16-major (the initdb/schema and Iceberg-catalog config assume PG16). MinIO server + client (`mc`) pinned to the SAME RELEASE. `minio-deployment.yaml:33`'s `| default "latest"` fallback → `| default "<pinned>"` so a values render can never fall back to a moving tag.

## 3. First-party `datapond/*` → chart appVersion

- **Templates**: backend/frontend/jupyter deployment templates render the tag as `{{ .Values.X.image.tag | default .Chart.AppVersion }}` (values can't reference `.Chart`, so the default lives in the template). Set the values `tag: ""` (empty ⇒ appVersion). Rendered image line resolves to `datapond/backend:2.3.0`, never an empty tag.
- **values.yaml + values-quicktest + values-onprem**: the three `datapond/*` `tag: latest` → `tag: ""` with a comment (`# empty ⇒ chart appVersion (see Chart.yaml); override for local dev / CD sha tags`).
- **scripts/build.sh**: `TAG="${2:-latest}"` → default resolved from Chart.yaml appVersion (`TAG="${2:-$(grep '^appVersion:' helm/datapond/Chart.yaml | tr -d ' "' | cut -d: -f2)}"`), still overridable by `$2`.
- **scripts/bundle-airgap.sh**: the three hardcoded `datapond/*:latest` → `:<appVersion>` (resolve the same way); update the comments (the tag-agnostic property holds — the chart default now IS appVersion).
- **cd.yml**: keep the `sha-<commit>` tag; replace the redundant `:latest` push with `:<appVersion>` so the registry carries no moving first-party tag. (Deploy job's `--set *.image.tag=$TAG` unchanged — CD still injects the sha for precise per-commit deploys.)

## 4. Docker base images

| Dockerfile | Current | Pin |
|---|---|---|
| `docker/jupyter/Dockerfile:1` | `jupyter/scipy-notebook:latest` | a specific dated/`hub-*` upstream tag (highest priority — fully floating) |
| `backend/Dockerfile:5` | `python:3.11-slim` | `python:3.11.x-slim` (specific patch) |
| `frontend/Dockerfile:2` | `node:20-alpine` | `node:20.x-alpine` (specific minor) |

Backend/frontend Dockerfiles are multi-stage; only the single `FROM ... AS base` line changes each (other stages are `FROM base`).

## 5. CI moving-tag guard (`.github/workflows/ci.yml`, helm-lint job)

New step after the existing helm assertions (grep denylist, Approach A). Fails the build on any moving tag:

- **Rendered Helm**: `helm template` for base + every profile (`values-prod/dev/quicktest/onprem/foundation/aws`); extract `image:` lines; fail on any tag matching `:(latest|main-latest|main|stable|edge|nightly)$` or an image ref with no `:tag`.
- **Dockerfiles**: grep every `Dockerfile` `^FROM ` line for the same moving family (excluding `FROM base`/`FROM ... AS` internal stage refs).
- Scoped to resolved `image:` / `FROM` lines only — NOT raw template source — to avoid comment false-positives (the `QUARKUS_OIDC_` grep lesson from P0-3).
- Ends with `echo "OK: no moving image tags"`.
- Because first-party tags render via `| default .Chart.AppVersion`, the rendered `image:` line always shows `2.3.0` — the guard sees a pinned tag, never an empty one.

Guard implementation detail: use the safe bash-`-e` idiom (`if ... | grep -qE ...; then echo FAIL; exit 1; fi`, not bare `grep && fail`) — same pattern as the existing weak-literal and OIDC-leak checks.

## 6. Docs & testing

- **`THIRD_PARTY_NOTICES.md`** (P0-2): update the image table's tags to the pinned versions; remove the "moving tags … until image pinning (P0-4) lands" caveat line (now satisfied).
- **README / runbook**: one line that image tags are pinned and bumped deliberately (no `:latest`).
- **Testing = CI**: helm renders all profiles (existing) + the new guard passes on the pinned tree. Red-path check done once during implementation (temporarily reintroduce a `:latest`, observe the guard fail, revert — never committed). No runtime/pytest surface (config only). Docker base-image pins are validated by the image build at deploy time (docker-in-CI is the deferred follow-up).

## 7. Out of scope

`@sha256` digest pinning; SBOM/trivy/grype scanning; docker `--target community|enterprise` build-in-CI verification; renovate/dependabot auto-bump; any major-version component upgrade; the already-pinned 9 images (valkey 7.2.5, mlflow v2.10.0, airflow 2.8.1, spark 3.5.8-python3, polaris 1.4.0, risingwave v1.7.0/v1.6.0, openmetadata 1.3.1, elasticsearch 8.10.2, curl 8.10.1) — left as-is.
