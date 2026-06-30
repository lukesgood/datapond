# MinIO Stage 2 — Base→AWS Default + Endpoint Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AWS-native S3 the chart's default and unify every storage consumer on `.Values.storage.endpoint` with credential gating (mirroring the backend's existing pattern), and prune RisingWave's dead S3 configuration.

**Architecture:** Flip base `values.yaml` to AWS-native (`storage.endpoint:""`, `minio.enabled:false`); give the MinIO profiles (dev/quicktest/prod) explicit `storage` blocks since they can no longer inherit a MinIO endpoint from base. Replace each consumer's hardcoded `http://minio:9000` + unconditional credentials with `http://{{ .Values.storage.endpoint }}` + `{{- if .Values.storage.endpoint }}` gates — so MinIO profiles inject endpoint+path-style+creds, while the AWS profile (empty endpoint) omits them and uses native S3 + the instance/IRSA credential chain. Remove RisingWave's S3 env (it runs an in-memory state store).

**Tech Stack:** Helm (Go templates), Kubernetes, MinIO/S3, CI helm chart lint.

**Spec:** `docs/superpowers/specs/2026-06-30-seaweedfs-to-minio-storage-migration-design.md` (Stage 2; see §1b, §4b).

## Global Constraints

- Chart root: `helm/datapond`. `helm` NOT installed locally → render verified by inspection + CI `Helm chart lint` (renders quicktest/onprem/aws/dev/prod). Every task keeps all profiles rendering.
- **Reference pattern (already in repo):** `backend-deployment.yaml:61-75` —
  ```yaml
  - name: S3_ENDPOINT
    value: "{{ .Values.storage.endpoint | default "" }}"
  - name: S3_REGION
    value: "{{ .Values.storage.region | default "us-east-1" }}"
  {{- if .Values.storage.endpoint }}
  - name: S3_ACCESS_KEY
    valueFrom: { secretKeyRef: { name: datapond-secrets, key: SEAWEEDFS_S3_USER } }
  - name: S3_SECRET_KEY
    valueFrom: { secretKeyRef: { name: datapond-secrets, key: SEAWEEDFS_S3_PASSWORD } }
  {{- end }}
  ```
  Replicate this gating for each consumer (using each consumer's own endpoint var names + creds).
- Endpoint value when set: `http://{{ .Values.storage.endpoint }}` (scheme + host:port). When `.Values.storage.endpoint` is empty (AWS): the endpoint override + path-style + static creds are ALL omitted → client uses native AWS S3 endpoint + default credential chain (IAM role / IRSA — full IRSA setup is Stage 3).
- Keep secret KEY NAMES `SEAWEEDFS_S3_USER`/`SEAWEEDFS_S3_PASSWORD` (rename is a later cleanup). Keep the jupyter env var NAME `SEAWEEDFS_S3_ENDPOINT` (DuckDB notebook reads it; renaming touches notebook code — out of scope).
- **No `_helpers.tpl`**: inline the proven backend `{{- if }}` pattern per consumer. (Helpers with `nindent` add whitespace-bug risk that only surfaces in CI; inline conditionals are safer and match the existing backend code. This is a deliberate deviation from the spec's helper suggestion.)
- **Image tag pinning is OUT of scope here**: a pinned MinIO `RELEASE.*` tag cannot be validated locally or by `helm template`, and a wrong tag is worse than `:latest` (which matches the prior SeaweedFS convention). Defer to a step that can verify against the registry.
- RisingWave runs `--backend mem --state-store hummock+memory` (no S3) — its S3 env is dead; remove it (do not gate it).

---

## File Structure

**Modified (values):** `values.yaml` (base→AWS), `values-dev.yaml`, `values-quicktest.yaml`, `values-prod.yaml` (add explicit MinIO `storage` blocks). `values-onprem.yaml` already has `storage.endpoint:minio:9000` (verify). `values-aws.yaml` unchanged.

**Modified (consumers):** `polaris-deployment.yaml`, `spark-config-configmap.yaml`, `trino-deployment.yaml`, `mlflow-deployment.yaml`, `jupyter-deployment.yaml` (endpoint unification + cred gating).

**Modified (cleanup):** `risingwave-statefulset.yaml` (remove dead S3 env in meta/compute/compactor), `values.yaml` (remove unused `risingwave.storage`).

**Docs:** spec roadmap + `docs/PRODUCT_CONCEPT.md`/`README.md` Phase note (optional).

---

## Task 1: Base → AWS-native default; explicit MinIO storage per profile

**Files:** `values.yaml`, `values-dev.yaml`, `values-quicktest.yaml`, `values-prod.yaml` (modify); verify `values-onprem.yaml`, `values-aws.yaml`.

**Interfaces:** After this task, base default = AWS native (`storage.endpoint:""`, `minio.enabled:false`); MinIO profiles each explicitly set `storage:{provider:minio, endpoint:"minio:9000", region:us-east-1}` and `minio.enabled:true`.

- [ ] **Step 1: Flip base `values.yaml`**

Change the base `storage:` block (currently `provider: minio, endpoint: "minio:9000"`) to:
```yaml
# Object storage. Default = AWS-native S3 (endpoint empty → AWS regional
# endpoint + IAM role). Non-AWS profiles set endpoint to their MinIO service.
storage:
  provider: s3
  endpoint: ""
  region: us-east-1
```
And set base `minio.enabled: false` (MinIO is opt-in per non-AWS profile).

- [ ] **Step 2: Add explicit `storage` to the MinIO profiles**

In `values-dev.yaml`, `values-quicktest.yaml`, and `values-prod.yaml`, add (they currently inherit storage from base, which is now AWS):
```yaml
storage:
  provider: minio
  endpoint: "minio:9000"
  region: us-east-1
```
(Each already sets `minio.enabled: true` — keep it.)

- [ ] **Step 3: Verify**
```bash
cd /Users/luke/datapond
for f in values values-dev values-quicktest values-prod values-onprem values-aws; do
  python3 -c "import yaml; d=yaml.safe_load(open('helm/datapond/$f.yaml')); s=d.get('storage',{}); print('$f', 'minio.enabled=',d.get('minio',{}).get('enabled'),'storage.endpoint=',repr(s.get('endpoint')))"
done
```
Expected: `values` endpoint `''` + minio.enabled False; dev/quicktest/prod/onprem endpoint `'minio:9000'` + minio.enabled True; aws endpoint `''` + minio.enabled False.

- [ ] **Step 4: Commit**
```bash
git add helm/datapond/values.yaml helm/datapond/values-dev.yaml helm/datapond/values-quicktest.yaml helm/datapond/values-prod.yaml
git commit -m "feat(storage): base default to AWS-native S3; explicit MinIO storage for non-AWS profiles"
```

---

## Task 2: Unify consumer endpoints + gate credentials

**Files (modify):** `polaris-deployment.yaml`, `mlflow-deployment.yaml`, `jupyter-deployment.yaml`, `trino-deployment.yaml`, `spark-config-configmap.yaml`

**Interfaces:** Each consumer's S3 endpoint becomes `http://{{ .Values.storage.endpoint }}`, emitted only under `{{- if .Values.storage.endpoint }}`; static credential env emitted under the same gate; path-style emitted under the same gate. Empty endpoint (AWS) ⇒ none emitted ⇒ native S3 + default cred chain.

- [ ] **Step 1: polaris-deployment.yaml (env-based)**

Wrap the endpoint+path-style+credential env (current lines ~99-128: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3`, `AWS_ENDPOINT_URL`, `AWS_S3_FORCE_PATH_STYLE`, `POLARIS_STORAGE_AWS_ACCESS_KEY`, `POLARIS_STORAGE_AWS_SECRET_KEY`) in `{{- if .Values.storage.endpoint }}` … `{{- end }}`, and change both endpoint values from `"http://minio:9000"` to `"http://{{ .Values.storage.endpoint }}"`. Keep `AWS_REGION` (value `{{ .Values.storage.region | default "us-east-1" }}`) OUTSIDE the gate (region is always valid). Net: on AWS (empty endpoint) Polaris gets only AWS_REGION and uses native S3 + IAM role.

- [ ] **Step 2: mlflow-deployment.yaml (env-based)**

Wrap `MLFLOW_S3_ENDPOINT_URL` (→ `"http://{{ .Values.storage.endpoint }}"`) and the `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env (lines ~55-66) in `{{- if .Values.storage.endpoint }}`…`{{- end }}`.

- [ ] **Step 3: jupyter-deployment.yaml (env-based)**

Wrap `SEAWEEDFS_S3_ENDPOINT` (KEEP name; value → `"http://{{ .Values.storage.endpoint }}"`) and the `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env (lines ~81-92) in `{{- if .Values.storage.endpoint }}`…`{{- end }}`. Keep `AWS_REGION` outside the gate.

- [ ] **Step 4: trino-deployment.yaml (env creds + configmap properties)**

(a) Env block (lines ~34-43): wrap `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in `{{- if .Values.storage.endpoint }}`…`{{- end }}`; keep `AWS_REGION` outside.
(b) iceberg.properties configmap (lines ~178-180): wrap `s3.endpoint`, `s3.path-style-access` in `{{- if .Values.storage.endpoint }}`…`{{- end }}` and set `s3.endpoint=http://{{ .Values.storage.endpoint }}`. Keep `fs.native-s3.enabled=true` and `s3.region=...` unconditional.

- [ ] **Step 5: spark-config-configmap.yaml (configmap properties + find spark pod creds)**

(a) In spark-defaults.conf, wrap the four S3 lines (`spark.sql.catalog.iceberg.s3.endpoint`, `spark.sql.catalog.iceberg.s3.path-style-access`, `spark.hadoop.fs.s3a.endpoint`, `spark.hadoop.fs.s3a.path.style.access`) in `{{- if .Values.storage.endpoint }}`…`{{- end }}`, setting both endpoints to `http://{{ .Values.storage.endpoint }}`.
(b) Spark reads creds from container env. Run `grep -rn 'AWS_ACCESS_KEY_ID' helm/datapond/templates/spark-*.yaml` to find where the Spark master/worker pods set AWS creds; wrap that env block in the same `{{- if .Values.storage.endpoint }}` gate (keep AWS_REGION outside). If no spark pod env sets creds, note it in the report (they may be unset today) — do NOT invent one.

- [ ] **Step 6: Verify**
```bash
cd /Users/luke/datapond
grep -rn 'minio:9000' helm/datapond/templates/   # expect ONLY minio-deployment.yaml + minio-bucket-init-job.yaml (the MinIO service itself), NOT consumers
grep -rn 'storage.endpoint' helm/datapond/templates/  # consumers now reference it
```
Expected: no consumer hardcodes `minio:9000`; each gates on `.Values.storage.endpoint`.

- [ ] **Step 7: Commit**
```bash
git add helm/datapond/templates/polaris-deployment.yaml helm/datapond/templates/mlflow-deployment.yaml helm/datapond/templates/jupyter-deployment.yaml helm/datapond/templates/trino-deployment.yaml helm/datapond/templates/spark-config-configmap.yaml
git commit -m "feat(storage): unify consumers on .Values.storage.endpoint with credential gating"
```

---

## Task 3: Remove RisingWave dead S3 configuration

**Files:** `risingwave-statefulset.yaml`, `values.yaml`

**Interfaces:** RisingWave (meta/compute/compactor) runs an in-memory state store and never accesses S3; remove its S3 env so it neither requires credentials nor references storage.

- [ ] **Step 1: Confirm the in-memory state store (do not change behavior)**

Verify `risingwave-statefulset.yaml` meta args include `--backend mem` and `--state-store "hummock+memory"` (no S3 state store). If instead it references `hummock+s3`/`hummock+minio` anywhere, STOP and report — removal would be unsafe.

- [ ] **Step 2: Remove the S3 env from all three sections**

In `risingwave-statefulset.yaml`, delete the S3-related env entries — `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `RW_S3_ENDPOINT`, `RW_S3_PATH_STYLE_ACCESS` — from the meta (lines ~46-61), compute (~232-247), and compactor (~331-346) env blocks. Keep non-S3 env (`POD_NAME`, `POD_IP`, `RUST_BACKTRACE`).

- [ ] **Step 3: Remove the unused storage block in `values.yaml`**

Delete the `risingwave.storage` block (`bucket: risingwave`, `dataDirectory: hummock`) — it is not referenced by any template.

- [ ] **Step 4: Verify**
```bash
cd /Users/luke/datapond
grep -n 'RW_S3\|AWS_ACCESS_KEY_ID\|AWS_SECRET_ACCESS_KEY' helm/datapond/templates/risingwave-statefulset.yaml   # expect EMPTY
grep -n 'state-store' helm/datapond/templates/risingwave-statefulset.yaml   # still hummock+memory
```

- [ ] **Step 5: Commit**
```bash
git add helm/datapond/templates/risingwave-statefulset.yaml helm/datapond/values.yaml
git commit -m "refactor(risingwave): remove dead S3 env (in-memory state store, never used S3)"
```

---

## Task 4: CI render verification + docs

- [ ] **Step 1: Push branch + open PR** so CI `Helm chart lint` renders every profile. Authoritative gate (helm not installed locally).

- [ ] **Step 2: If CI render fails**, read the failing profile/line, fix the specific template/values issue, re-push. Do not mark complete until all three checks green.

- [ ] **Step 3: Mark Stage 2 done in the spec roadmap**

In the spec (§1b), append that Stage 2 is implemented (base→AWS default, endpoint unification, RisingWave cleanup); note image-pinning + full IRSA remain Stage 3. Commit:
```bash
git add docs/superpowers/specs/2026-06-30-seaweedfs-to-minio-storage-migration-design.md
git commit -m "docs(spec): mark MinIO Stage 2 complete"
```

---

## Self-Review

**Spec coverage (Stage 2):** base→AWS default (T1), endpoint unification + cred gating across all consumers (T2), RisingWave vestigial cleanup (T3), CI verify + docs (T4). Image-pinning deferred (rationale in constraints); full IRSA = Stage 3; jupyter env-var rename deferred. ✅

**Placeholder scan:** Per-file edits name the exact env/property lines and the `{{- if .Values.storage.endpoint }}` pattern; Spark cred location is discovered via an explicit grep step (the only unknown), with a "do not invent" guard. No TODO/TBD.

**Consistency:** Endpoint value `http://{{ .Values.storage.endpoint }}` and gate `{{- if .Values.storage.endpoint }}` used identically across T2; matches the backend reference pattern. T1 guarantees every MinIO profile sets `storage.endpoint:minio:9000` so the gates render the MinIO config there, and the AWS/base empty endpoint correctly omits it. RisingWave (T3) removes creds entirely, so it has no dependency on the secret regardless of profile.
