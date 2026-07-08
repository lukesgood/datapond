# P0-4 Resolved Pinned Versions (resolved 2026-07-08)

All tags below were verified to exist by fetching the registry's tags API/page directly (Docker Hub `v2` tags API, GitHub Releases pages, or the quay.io tags API) — not guessed or incremented from memory.

| Image | Old (moving) | Pinned | Source |
|---|---|---|---|
| `minio/minio` | `latest` | `RELEASE.2025-09-07T16-13-09Z` | https://hub.docker.com/v2/repositories/minio/minio/tags/RELEASE.2025-09-07T16-13-09Z (also https://hub.docker.com/r/minio/minio/tags) |
| `minio/mc` | `latest` | `RELEASE.2025-08-13T08-35-41Z` | https://hub.docker.com/v2/repositories/minio/mc/tags/RELEASE.2025-08-13T08-35-41Z (also https://hub.docker.com/r/minio/mc/tags) |
| `trinodb/trino` | `latest` | `482` | https://hub.docker.com/r/trinodb/trino/tags (482 pushed ~12 days before resolution) |
| `ghcr.io/berriai/litellm` | `main-latest` | `v1.91.0` | https://github.com/BerriAI/litellm/releases/tag/v1.91.0 (release notes explicitly reference `ghcr.io/berriai/litellm:v1.91.0` with cosign verification instructions) |
| `ollama/ollama` | `latest` | `0.31.1` | https://hub.docker.com/r/ollama/ollama/tags |
| `vllm/vllm-openai` | `latest` | `v0.24.0` | https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.24.0 (confirmed present, last_updated 2026-06-29) + https://github.com/vllm-project/vllm/releases/tag/v0.24.0 (marked "Latest") |
| `pgvector/pgvector` | `pg16` | `0.8.4-pg16` | https://hub.docker.com/r/pgvector/pgvector/tags |
| `postgres` (template) | `16-alpine` | `16.14-alpine` | https://hub.docker.com/v2/repositories/library/postgres/tags/16.14-alpine ; version confirmed via https://www.postgresql.org/about/news/postgresql-184-1710-1614-1518-and-1423-released-3297/ (2026-05-14 release) |
| `busybox` (template) | `1.36` | `1.36.1` | https://hub.docker.com/_/busybox/tags?name=1.36 (family `1.36` resolves to `1.36.1`; no `1.36.2`+ exists) |
| `jupyter/scipy-notebook` | `latest` | `quay.io/jupyter/scipy-notebook:2026-07-06` | https://quay.io/api/v1/repository/jupyter/scipy-notebook/tag/ (dated tag `2026-07-06`, also aliased `hub-5.5.0`, `lab-4.6.1`, `latest`) |
| `python` (backend base) | `3.11-slim` | `3.11.15-slim` | https://hub.docker.com/v2/repositories/library/python/tags/3.11.15-slim |
| `node` (frontend base) | `20-alpine` | `20.20.0-alpine` | https://hub.docker.com/v2/repositories/library/node/tags/20.20.0-alpine |
| `datapond/{backend,frontend,jupyter}` | `latest` | `2.3.0` (chart appVersion) | `helm/datapond/Chart.yaml` (`version: 2.3.0`, `appVersion: "2.3.0"`) |

## Notes / judgment calls

1. **minio/minio vs minio/mc — no identical `RELEASE.*` tag exists.** MinIO server and the `mc` client are separate GitHub repos with independent release trains; verified by pulling both full tag lists from the Docker Hub `v2` API — their `RELEASE.<UTC-date>` timestamps have never coincided (checked both the full 2025 history and the earliest 2016-2018 history). The brief's per-row constraint ("the `RELEASE.*` closest to the minio server release — matched pair") is achievable; a literal *identical* tag string is not. Resolution: pinned each to its own latest verified-stable release — `minio/minio:RELEASE.2025-09-07T16-13-09Z` and `minio/mc:RELEASE.2025-08-13T08-35-41Z` (25 days apart, the closest available pairing between the two repos' latest releases). No newer stable tag exists for either as of 2026-07-08.

2. **litellm stable tag.** The ghcr.io package's most recent tags are pre-release (`v1.93.0-dev.1` / `dev` / `main-latest`, and `v1.92.0-rc.1` / `rc`), confirming `v1.91.0` (2026-07-04) is the newest fully-stable release. Its GitHub release notes explicitly cite the `ghcr.io/berriai/litellm:v1.91.0` image tag with cosign signature-verification steps, which is strong confirmation the container tag is published (beyond just the git tag existing).

3. **jupyter/scipy-notebook registry path.** Confirmed via the project's own docs/GitHub history: Jupyter Docker Stacks stopped pushing to Docker Hub on 2023-10-20 and publishes only to `quay.io/jupyter/*` since then. The current Dockerfile reference `jupyter/scipy-notebook:latest` (implicitly Docker Hub) is stale and must become `quay.io/jupyter/scipy-notebook:<tag>`. Chose the dated tag `2026-07-06` (most recent, 2 days before this resolution) over `hub-5.5.0`/`lab-4.6.1` for readability/traceability — all four tags point at the same manifest as of resolution date, per the quay.io tags API.

4. **node 20.x is EOL.** Node.js 20 reached end-of-life on 2026-04-30 (no longer receives security patches); `20.20.0` (2026-01-28) was its final LTS release and is the newest tag in the `20.x` family. The brief's family constraint (stay on `20.x`) is honored here, but this is flagged as a concern for a follow-up task/decision — moving to Node 22 (Active LTS) or Node 24 is likely out of scope for this pinning task but should be tracked separately.

5. **vllm/vllm-openai.** Docker Hub's default tag listing (sorted by push recency) is dominated by `nightly` / `cu129-nightly` / `hy3` tags since those are rebuilt continuously; the stable `v0.x.y` tags don't rebuild and so don't show on that page. Verified `v0.24.0` exists directly via the Docker Hub tag-detail API (`.../tags/v0.24.0`, present, ~10.6GB, last_updated 2026-06-29) and cross-checked against the GitHub Releases page where it is marked "Latest".

6. **All family constraints satisfied:** pgvector `*-pg16` ✓, postgres `16.x-alpine` (major 16) ✓, busybox `1.36.1` ✓, minio/mc same-family-latest (see note 1) ✓, no `-rc`/`-beta`/`-dev`/nightly tags picked anywhere.
