# Image-Tag Pinning (P0-4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate every moving container-image tag (`:latest`, `main-latest`, floating base images, rolling `pg16`/`16-alpine`) — pin third-party images to concrete versions, first-party `datapond/*` to the chart `appVersion` — and add a CI guard that fails on any moving tag.

**Spec:** `docs/superpowers/specs/2026-07-08-image-tag-pinning-design.md`

**Architecture:** Config-only change (no runtime code). Concrete versions are resolved live from registries/release pages in Task 1 and recorded to a reference file; Tasks 2-4 apply them mechanically. First-party images default to `.Chart.AppVersion` in the deployment templates. A grep-denylist CI step (matching the existing license-gate idiom) renders all Helm profiles + reads Dockerfile FROM lines and fails on the moving-tag family.

**Tech Stack:** Helm, Docker, bash, GitHub Actions. No new dependencies.

## Global Constraints

- Chart `appVersion` is `2.3.0` (helm/datapond/Chart.yaml). First-party `datapond/{backend,frontend,jupyter}` pin to it via `{{ .Values.X.image.tag | default .Chart.AppVersion }}` in templates + `tag: ""` in values.
- Drift-elimination ONLY — pin to a version the current config already works with. NO major upgrades. Family constraints: pgvector stays `*-pg16`, postgres stays `16.*-alpine`, MinIO server + `mc` pinned to the SAME `RELEASE.*` tag.
- Every pinned version MUST be verified to exist on its registry at implementation time; the resolving task records the tag + source URL.
- The 9 already-pinned images are OUT of scope — do not touch: valkey 7.2.5, mlflow v2.10.0, airflow 2.8.1, spark 3.5.8-python3, polaris/polaris-admin-tool 1.4.0, risingwave v1.7.0 (quicktest v1.6.0), openmetadata 1.3.1, elasticsearch 8.10.2, curl 8.10.1.
- CI shell guards use the bash-`-e`-safe if-form (`if ... | grep -qE ...; then echo FAIL; exit 1; fi`), scoped to resolved `image:`/`FROM` lines — never raw template text (comment false-positive lesson from P0-3's `QUARKUS_OIDC_`).
- helm/docker are NOT installed locally — Helm/Dockerfile correctness is verified by CI render; values files must parse as YAML locally.
- Branch: `feat/image-tag-pinning`; squash-merge PR at the end.

---

### Task 1: Resolve concrete pinned versions (research + record)

**Files:**
- Create: `docs/superpowers/plans/p0-4-pinned-versions.md` (the resolved-version reference table that Tasks 2-4 consume)

**Interfaces:**
- Produces: a committed table mapping each moving image → its resolved concrete tag + source URL. Tasks 2-4 read the EXACT tag values from this file.

- [ ] **Step 1: Resolve each moving image's current stable version.** For EACH image below, fetch its registry tags / release page (WebFetch or WebSearch) and pick the latest STABLE release consistent with the family constraint. Record tag + source URL.

| Image | Where to look | Family constraint |
|---|---|---|
| `minio/minio` | hub.docker.com/r/minio/minio/tags or github.com/minio/minio/releases | a `RELEASE.<UTC-date>` tag |
| `minio/mc` | hub.docker.com/r/minio/mc/tags | the `RELEASE.*` closest to the minio server release (matched pair) |
| `trinodb/trino` | hub.docker.com/r/trinodb/trino/tags or github.com/trinodb/trino/releases | latest integer version (e.g. `4NN`) |
| `ghcr.io/berriai/litellm` | github.com/BerriAI/litellm/releases or ghcr tags | a stable `v1.x.y` release tag (NOT `main-latest`) — confirm the tag exists on ghcr.io/berriai/litellm |
| `ollama/ollama` | hub.docker.com/r/ollama/ollama/tags | latest `0.x.y` |
| `vllm/vllm-openai` | hub.docker.com/r/vllm/vllm-openai/tags | latest `v0.x.y` |
| `pgvector/pgvector` | hub.docker.com/r/pgvector/pgvector/tags | latest `0.x.y-pg16` |
| `postgres` (template) | hub.docker.com/_/postgres/tags | latest `16.x-alpine` |
| `busybox` (template) | hub.docker.com/_/busybox/tags | latest `1.36.x` (family `1.36`, so `1.36.1`) |
| `jupyter/scipy-notebook` | quay.io/jupyter/scipy-notebook or hub.docker.com/r/jupyter/scipy-notebook/tags | a specific dated / `hub-*` tag (NOTE: image moved to quay.io — verify pull path still `jupyter/scipy-notebook:<tag>` works from the current Dockerfile registry) |
| `python` (backend base) | hub.docker.com/_/python/tags | latest `3.11.x-slim` |
| `node` (frontend base) | hub.docker.com/_/node/tags | latest `20.x-alpine` |

If WebFetch/WebSearch is unavailable in your environment, STOP and report NEEDS_CONTEXT listing the images you couldn't resolve — the controller will resolve them. Do NOT invent version numbers.

- [ ] **Step 2: Write `docs/superpowers/plans/p0-4-pinned-versions.md`** with a table exactly like:

```markdown
# P0-4 Resolved Pinned Versions (resolved <DATE>)

| Image | Old (moving) | Pinned | Source |
|---|---|---|---|
| minio/minio | latest | RELEASE.2025-... | https://... |
| minio/mc | latest | RELEASE.2025-... | https://... |
| trinodb/trino | latest | 4NN | https://... |
| ghcr.io/berriai/litellm | main-latest | v1.x.y | https://... |
| ollama/ollama | latest | 0.x.y | https://... |
| vllm/vllm-openai | latest | v0.x.y | https://... |
| pgvector/pgvector | pg16 | 0.x.y-pg16 | https://... |
| postgres | 16-alpine | 16.x-alpine | https://... |
| busybox | 1.36 | 1.36.1 | https://... |
| jupyter/scipy-notebook | latest | <dated tag> | https://... |
| python | 3.11-slim | 3.11.x-slim | https://... |
| node | 20-alpine | 20.x-alpine | https://... |
| datapond/{backend,frontend,jupyter} | latest | 2.3.0 (chart appVersion) | Chart.yaml |
```

- [ ] **Step 3: Commit**

```bash
git checkout -b feat/image-tag-pinning   # if not already on it
git add docs/superpowers/plans/p0-4-pinned-versions.md
git commit -m "docs(p0-4): resolved concrete pinned versions for all moving images"
```

---

### Task 2: Pin third-party images (values.yaml + hardcoded template images)

**Files:**
- Modify: `helm/datapond/values.yaml` (lines 110, 366, 396, 717, 802, 849)
- Modify: `helm/datapond/templates/minio-deployment.yaml:33`, `helm/datapond/templates/minio-bucket-init-job.yaml:18`, `helm/datapond/templates/polaris-bootstrap-job.yaml:40`, `helm/datapond/templates/litellm-deployment.yaml:100`, `helm/datapond/templates/polaris-deployment.yaml:26`, `helm/datapond/templates/openmetadata-deployment.yaml:29,35,136,139`

**Interfaces:**
- Consumes: the resolved tags from `docs/superpowers/plans/p0-4-pinned-versions.md` (Task 1). Use those EXACT values; the snippets below show the shape with `<PINNED>` — substitute the real tag.

- [ ] **Step 1: values.yaml third-party tags.** Replace each `tag:` value (keep quoting style consistent with neighbors):
  - line 110: `tag: "pg16"` → `tag: "<pgvector pinned, e.g. 0.8.0-pg16>"`
  - line 366: `tag: latest` (minio) → `tag: "<minio RELEASE.*>"`
  - line 396: `tag: latest` (trino) → `tag: "<trino integer>"`
  - line 717: `tag: "main-latest"` (litellm) → `tag: "<litellm v1.x.y>"`
  - line 802: `tag: "latest"` (ollama) → `tag: "<ollama 0.x.y>"`
  - line 849: `tag: "latest"` (vllm) → `tag: "<vllm v0.x.y>"`

- [ ] **Step 2: minio-deployment.yaml:33** — pin the default fallback so a render can never fall back to moving:

```yaml
          image: "{{ .Values.minio.image.repository | default "minio/minio" }}:{{ .Values.minio.image.tag | default "<minio RELEASE.*>" }}"
```

- [ ] **Step 3: hardcoded template images** — replace in place:
  - `minio-bucket-init-job.yaml:18` `minio/mc:latest` → `minio/mc:<mc RELEASE.*>`
  - `polaris-bootstrap-job.yaml:40`, `litellm-deployment.yaml:100`, `polaris-deployment.yaml:26` `postgres:16-alpine` → `postgres:<16.x-alpine>` (all three, same value)
  - `openmetadata-deployment.yaml:29,35,136,139` `busybox:1.36` → `busybox:1.36.1` (all four)

- [ ] **Step 4: Verify + commit**

```bash
python3 -c "import yaml; yaml.safe_load(open('helm/datapond/values.yaml'))" && echo VALUES-OK
# No moving third-party tag remains in values or the touched templates:
grep -rn 'minio/mc:latest\|minio/minio.*latest\|postgres:16-alpine\|busybox:1.36[^.]\|:pg16\|trinodb/trino.*latest\|main-latest\|ollama.*latest\|vllm.*latest' helm/datapond/values.yaml helm/datapond/templates/ || echo "OK: none remain"
git add helm/datapond/values.yaml helm/datapond/templates
git commit -m "feat(helm): pin third-party image tags to concrete versions (no moving tags)"
```
(The grep may still show the already-pinned tags in comments — inspect each hit; only unpinned refs are failures.)

---

### Task 3: First-party images → chart appVersion (+ CD context fix)

**Files:**
- Modify: `helm/datapond/templates/{frontend,backend,jupyter}-deployment.yaml` (the `image:` line)
- Modify: `helm/datapond/values.yaml` (37, 72, 177), `helm/datapond/values-quicktest.yaml` (27, 48), `helm/datapond/values-onprem.yaml` (33, 51)
- Modify: `scripts/build.sh:8`, `scripts/bundle-airgap.sh` (backend/frontend/jupyter build+save lines ~40-56), `.github/workflows/cd.yml`

**Interfaces:**
- Consumes: `appVersion: "2.3.0"` from Chart.yaml.

- [ ] **Step 1: deployment templates** — make the tag default to appVersion. In `frontend-deployment.yaml:25`, `backend-deployment.yaml:25`, and BOTH `image:` lines in `jupyter-deployment.yaml` (23 and 45):

```yaml
        image: "{{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag | default .Chart.AppVersion }}"
```
(substitute `backend`/`jupyter` for the respective files; jupyter has two identical lines — change both.)

- [ ] **Step 2: values files** — set the three first-party `tag:` to empty with a comment. In `values.yaml` (37 frontend, 72 backend, 177 jupyter), `values-quicktest.yaml` (27, 48), `values-onprem.yaml` (33, 51):

```yaml
    tag: ""   # empty ⇒ chart appVersion (Chart.yaml); override for local dev / CD sha tags
```

- [ ] **Step 3: build.sh:8** — default TAG to appVersion:

```bash
TAG="${2:-$(grep '^appVersion:' helm/datapond/Chart.yaml | tr -d ' "' | cut -d: -f2)}"
```

- [ ] **Step 4: bundle-airgap.sh** — the three `datapond/*:latest` build+save pairs (~lines 40, 47, 55 build and their `docker save` lines). First add an appVersion var near the top of the script (after `PROJECT_ROOT` is defined — find it with `grep -n PROJECT_ROOT scripts/bundle-airgap.sh | head -1`):

```bash
APPVER="$(grep '^appVersion:' "$PROJECT_ROOT/helm/datapond/Chart.yaml" | tr -d ' "' | cut -d: -f2)"
```
then replace every `datapond/backend:latest` → `datapond/backend:$APPVER`, `datapond/frontend:latest` → `datapond/frontend:$APPVER`, `datapond/jupyter:latest` → `datapond/jupyter:$APPVER` (build `-t` AND `docker save` lines). Update the comment block (~36-38): the tag is now appVersion, not `latest`, but the tag-agnostic property still holds because the chart default IS appVersion.

- [ ] **Step 5: cd.yml — pin push tags AND fix the P0-3-introduced context break.** Two changes to the backend build-push step (~lines 47-55):
  1. Backend build context is wrong post-P0-3 (the Dockerfile now needs repo-root context + a target). Change `context: backend` → `context: .`, add `file: backend/Dockerfile` and `target: enterprise`.
  2. Replace the `-backend:latest` tag line with the appVersion tag.

```yaml
      - name: Build & push backend
        uses: docker/build-push-action@v6
        with:
          context: .
          file: backend/Dockerfile
          target: enterprise
          push: true
          provenance: false
          tags: |
            ${{ env.IMAGE_BASE }}-backend:${{ steps.meta.outputs.tag }}
            ${{ env.IMAGE_BASE }}-backend:${{ steps.meta.outputs.appversion }}
```
For frontend (~lines 56-64): keep `context: frontend` (its Dockerfile was NOT changed to root context), just replace `-frontend:latest` → `-frontend:${{ steps.meta.outputs.appversion }}`.
Add an `appversion` output to the `meta` step (find it: `grep -n "id: meta\|meta.outputs\|GITHUB_OUTPUT" .github/workflows/cd.yml`). In that step's script add:
```bash
            echo "appversion=$(grep '^appVersion:' helm/datapond/Chart.yaml | tr -d ' \"' | cut -d: -f2)" >> "$GITHUB_OUTPUT"
```

- [ ] **Step 6: Verify + commit**

```bash
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('helm/datapond/values*.yaml')]" && echo VALUES-OK
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/cd.yml'))" && echo CD-YAML-OK
bash -n scripts/build.sh && bash -n scripts/bundle-airgap.sh && echo SH-OK
grep -rn 'datapond/\(backend\|frontend\|jupyter\):latest' scripts/ .github/ helm/ && echo "FAIL: first-party :latest remains" || echo "OK: no first-party :latest"
git add helm/datapond scripts/build.sh scripts/bundle-airgap.sh .github/workflows/cd.yml
git commit -m "feat: first-party images pin to chart appVersion; fix CD backend build context (P0-3 regression)"
```

---

### Task 4: Dockerfile base images

**Files:**
- Modify: `docker/jupyter/Dockerfile:1`, `backend/Dockerfile:5`, `frontend/Dockerfile:2`

**Interfaces:**
- Consumes: python/node/scipy-notebook pinned tags from Task 1's table.

- [ ] **Step 1** — `docker/jupyter/Dockerfile:1`:

```dockerfile
FROM jupyter/scipy-notebook:<dated tag from Task 1>
```
(If Task 1 found the image now lives on quay.io only, use the full path `quay.io/jupyter/scipy-notebook:<tag>` and note it — verify the tag is pullable.)

- [ ] **Step 2** — `backend/Dockerfile:5` (the `FROM ... AS base` line only; the community/enterprise stages are `FROM base`, unchanged):

```dockerfile
FROM python:<3.11.x-slim from Task 1> AS base
```

- [ ] **Step 3** — `frontend/Dockerfile:2` (the base stage `FROM` only):

```dockerfile
FROM node:<20.x-alpine from Task 1> AS base
```
(Confirm the frontend Dockerfile's first FROM is the one to pin; if it's `FROM node:20-alpine AS base` change that line — other stages inherit `FROM base`.)

- [ ] **Step 4: Verify + commit**

```bash
grep -rn '^FROM ' backend/Dockerfile frontend/Dockerfile docker/jupyter/Dockerfile | grep -vE ':[0-9].*[0-9]|@sha256|FROM base|AS base$' | grep -iE 'latest|:slim$|:alpine$|:3.11-slim|:20-alpine' && echo "FAIL: moving base image remains" || echo "OK: base images pinned"
git add backend/Dockerfile frontend/Dockerfile docker/jupyter/Dockerfile
git commit -m "build: pin Docker base images (python, node, scipy-notebook) to specific versions"
```

---

### Task 5: CI moving-tag guard + red-path verification

**Files:**
- Modify: `.github/workflows/ci.yml` (helm-lint job, after the `echo "OK: OIDC wired"` line ~158)

- [ ] **Step 1: add the guard step content** after `echo "OK: OIDC wired"` (inside the same `run: |` block, same indentation):

```bash
          echo "== no moving image tags (P0-4) =="
          MOVING='(:latest|:main-latest|:main|:stable|:edge|:nightly)$'
          for v in "" "--values helm/datapond/values-prod.yaml" "--values helm/datapond/values-onprem.yaml" \
                   "--values helm/datapond/values-quicktest.yaml" "--values helm/datapond/values-foundation.yaml" \
                   "--values helm/datapond/values-aws.yaml"; do
            imgs=$(helm template datapond helm/datapond $v | grep -E '^\s*image:' | sed -E 's/.*image:\s*"?([^"]+)"?.*/\1/')
            if echo "$imgs" | grep -qE "$MOVING"; then
              echo "FAIL: moving image tag in profile ${v:-base}:"; echo "$imgs" | grep -E "$MOVING"; exit 1
            fi
            if echo "$imgs" | grep -vqE ':'; then
              echo "FAIL: untagged image in profile ${v:-base}:"; echo "$imgs" | grep -vE ':'; exit 1
            fi
          done
          echo "== no moving Docker base images =="
          if grep -hE '^FROM ' backend/Dockerfile frontend/Dockerfile docker/jupyter/Dockerfile \
             | grep -vE 'FROM \S+ AS |FROM base' | grep -qE "$MOVING|:3.11-slim$|:20-alpine$"; then
            echo "FAIL: moving Docker base image"; exit 1
          fi
          echo "OK: no moving image tags"
```

Note the `grep -vqE ':'` untagged check: an image line like `repo:tag` always has a `:`, so this only fires on a truly untagged ref. The base-image grep excludes internal stage refs (`FROM base`, `FROM x AS y`) and explicitly rejects the two old floating base tags (`3.11-slim`, `20-alpine`) in case Task 4 was skipped.

- [ ] **Step 2: red-path verification** (do locally without helm by testing the regex logic, since helm isn't installed):

```bash
# The MOVING regex must catch the bad tags and pass the good ones:
printf 'minio/minio:latest\nghcr.io/berriai/litellm:main-latest\ndatapond/backend:2.3.0\npostgres:16.6-alpine\nbusybox:1.36.1\n' \
  | grep -E '(:latest|:main-latest|:main|:stable|:edge|:nightly)$'
# Expected output: the two moving lines ONLY (minio:latest, litellm:main-latest); the 3 pinned lines must NOT appear.
```
Confirm the pinned examples (`:2.3.0`, `:16.6-alpine`, `:1.36.1`) do NOT match and the two `:latest`/`:main-latest` DO. Record this in the report. Full helm-render verification happens in CI.

- [ ] **Step 3: YAML + commit**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo CI-YAML-OK
git add .github/workflows/ci.yml
git commit -m "ci: guard against moving image tags across all Helm profiles + Dockerfiles"
```

---

### Task 6: Docs + PR + CI + final review

**Files:**
- Modify: `THIRD_PARTY_NOTICES.md` (image table tags + the moving-tags caveat line ~135-136), `README.md` (or `docs/AWS_MVP_RUNBOOK.md`) one-line note

- [ ] **Step 1: THIRD_PARTY_NOTICES.md** — update the image-table tags that changed (the `pgvector/pgvector:pg16`, `postgres:16-alpine`, `busybox:1.36`, `minio`, `trino`, `litellm`, `ollama`, `vllm` rows) to the Task-1 pinned versions, and REPLACE the closing caveat (lines ~135-136):

```markdown
Image tags are pinned to specific versions (P0-4); they are bumped deliberately, never
floating. See helm/datapond/values.yaml and the Dockerfiles for the authoritative tags.
```

- [ ] **Step 2: README.md** — in the P0 backlog line, mark image-tag pinning done (change `image-tag pinning` from a pending item to ~~struck~~ ✅, matching the existing style of the completed items).

- [ ] **Step 3: commit + push + PR**

```bash
git add THIRD_PARTY_NOTICES.md README.md
git commit -m "docs: pinned-tag notices + mark P0-4 image pinning complete"
git push -u origin feat/image-tag-pinning
export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
gh pr create --title "feat: pin all container image tags (P0-4)" --body "..."
```
PR body: pins all ~15 moving tags to concrete versions (third-party) / chart appVersion (first-party); CI guard blocks moving-tag regressions across all profiles + Dockerfiles; fixes the P0-3-introduced CD backend build-context break; closes the P0-2 THIRD_PARTY_NOTICES moving-tag caveat. Version resolution recorded in `p0-4-pinned-versions.md`. Out of scope: SBOM scanning, docker-build-in-CI, @sha256 digests (spec §7).

- [ ] **Step 4:** CI green (helm-lint incl. the new guard, license gate, backend/frontend unaffected). Fix any failure; done only when green.
- [ ] **Step 5:** Final whole-branch review (controller dispatches).

---

## Self-Review

**Spec coverage:** §2 third-party → Task 2 (values + all hardcoded template refs incl. minio default fallback); §3 first-party → Task 3 (templates default-to-appVersion, values `tag:""`, build.sh, bundle-airgap, cd.yml); §4 base images → Task 4; §5 CI guard → Task 5 (render-all-profiles + Dockerfile FROM, safe if-form, resolved-image-line scoping); §6 docs → Task 6 (TPN tags + caveat, README); version resolution → Task 1 (the data dependency §2 defers). §7 out-of-scope honored.

**Deviation / bonus (flagged):** Task 3 Step 5 fixes the CD backend build `context: backend`→`context: .`+`target: enterprise`, a break P0-3 introduced (Dockerfile now needs repo-root context) that CI never exercises. In-scope because P0-4 already edits cd.yml for tag pinning and shipping a known-broken CD path is worse; called out for the reviewer.

**Placeholder scan:** the `<PINNED>`/`<...from Task 1>` markers are a deliberate data dependency, not a plan-failure — Task 1 produces the concrete values and Tasks 2-4 substitute them; every edit's location, shape, and family constraint is fully specified. No other TBDs.

**Consistency:** appVersion `2.3.0` used identically across templates/values/scripts/cd; `.Chart.AppVersion` default expression identical in all three first-party templates; the MOVING regex identical in the CI guard and the Task-5 red-path check; MinIO server+mc pinned to the same RELEASE (constraint stated in Tasks 1 and 2).
