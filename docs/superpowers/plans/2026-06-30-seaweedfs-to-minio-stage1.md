# SeaweedFS → MinIO Swap (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-cluster SeaweedFS object store with MinIO (S3-compatible) for all non-AWS profiles, re-pointing every storage consumer from `seaweedfs-s3:8333` to `minio:9000`, while keeping every Helm profile renderable.

**Architecture:** Add MinIO (standalone Deployment + Service `minio:9000` + PVC, gated `minio.enabled`) and a MinIO bucket-init Job; re-point the 8 storage consumers and the CoreDNS rewrite to MinIO; remove the SeaweedFS templates; update all values files (drop `seaweedfs:` blocks, set `minio.*`, dedup duplicate blocks). Endpoint-unification to `.Values.storage.endpoint` and base→AWS default are explicitly Stage 2.

**Tech Stack:** Helm (Go templates), MinIO (`minio/minio`, `minio/mc`), Kubernetes (Deployment/Service/PVC/Job), CoreDNS custom config.

**Spec:** `docs/superpowers/specs/2026-06-30-seaweedfs-to-minio-storage-migration-design.md` (Stage 1 only).

## Global Constraints

- Chart root: `helm/datapond`. SeaweedFS is in-repo templates (not a subchart); MinIO will be too.
- `helm` is NOT installed locally → template correctness is verified by inspection + the CI `Helm chart lint` job, which renders ALL of `values-quicktest|onprem|aws|dev|prod` (and base). Every task must keep all profiles rendering.
- Keep `path-style` access = `true` for every S3 consumer (MinIO requires it).
- MinIO service name `minio`, API port `9000`, console `9001`. Buckets: `iceberg` (+ existing `risingwave` if referenced).
- Stage 1 keeps per-consumer endpoint config (just `seaweedfs-s3:8333` → `minio:9000`); do NOT introduce `.Values.storage.endpoint` indirection in consumers (that is Stage 2).
- Credential secret KEY NAMES stay `SEAWEEDFS_S3_USER`/`SEAWEEDFS_S3_PASSWORD`/`S3_ACCESS_KEY`/`S3_SECRET_KEY` in Stage 1 (consumers already read them); only their gating/source changes to MinIO. Renaming is Stage 2.
- `values-aws.yaml` keeps `seaweedfs.enabled:false`; it gets `minio.enabled:false` (AWS uses native S3). Its lakehouse-services-on-S3 wiring is a Stage 2 concern — do not try to fix it here.
- Each task ends renderable; ordering: add MinIO → re-point consumers → remove SeaweedFS → values cleanup.

---

## File Structure

**Created:**
- `helm/datapond/templates/minio-deployment.yaml` — MinIO Deployment + Service + PVC (`{{- if .Values.minio.enabled }}`).
- `helm/datapond/templates/minio-bucket-init-job.yaml` — post-install/upgrade bucket creation (`{{- if and .Values.minio.enabled .Values.polaris.enabled }}`).

**Modified:**
- `helm/datapond/templates/coredns-custom-configmap.yaml` — gate `minio.enabled`, target MinIO.
- `helm/datapond/templates/secrets.yaml` — gate credentials on `minio.enabled`, source from `minio.auth`.
- `helm/datapond/templates/{polaris-deployment,spark-config-configmap,trino-deployment,risingwave-statefulset,mlflow-deployment,jupyter-deployment}.yaml` — endpoint `seaweedfs-s3:8333` → `minio:9000`.
- `helm/datapond/templates/backend-deployment.yaml` — `ICEBERG_WAREHOUSE` unchanged (`s3a://iceberg/warehouse`); no endpoint change (already uses `.Values.storage.endpoint`).
- `helm/datapond/values.yaml`, `values-dev.yaml`, `values-prod.yaml`, `values-onprem.yaml`, `values-quicktest.yaml`, `values-aws.yaml` — `seaweedfs:` → `minio:` blocks; dedup.

**Removed:**
- `helm/datapond/templates/seaweedfs-deployment.yaml`
- `helm/datapond/templates/seaweedfs-bucket-init-job.yaml`

---

## Task 1: Add MinIO deployment + base values

**Files:**
- Create: `helm/datapond/templates/minio-deployment.yaml`
- Modify: `helm/datapond/values.yaml` (add `minio:` block; keep `seaweedfs:` for now)

**Interfaces:**
- Produces: Service `minio` (port 9000 api, 9001 console); reads `.Values.minio.{enabled,image,auth.rootUser,auth.rootPassword,persistence.size,resources}`.

- [ ] **Step 1: Create the MinIO template**

`helm/datapond/templates/minio-deployment.yaml`:
```yaml
{{- if .Values.minio.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: minio-data
  namespace: {{ .Values.namespace }}
spec:
  accessModes: ["ReadWriteOnce"]
  {{- if .Values.global.storageClass }}
  storageClassName: {{ .Values.global.storageClass }}
  {{- end }}
  resources:
    requests:
      storage: {{ .Values.minio.persistence.size | default "50Gi" }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: {{ .Values.namespace }}
  labels: { app: minio }
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector:
    matchLabels: { app: minio }
  template:
    metadata:
      labels: { app: minio }
    spec:
      containers:
        - name: minio
          image: "{{ .Values.minio.image.repository | default "minio/minio" }}:{{ .Values.minio.image.tag | default "latest" }}"
          args: ["server", "/data", "--console-address", ":9001"]
          env:
            - name: MINIO_ROOT_USER
              valueFrom:
                secretKeyRef: { name: datapond-secrets, key: SEAWEEDFS_S3_USER }
            - name: MINIO_ROOT_PASSWORD
              valueFrom:
                secretKeyRef: { name: datapond-secrets, key: SEAWEEDFS_S3_PASSWORD }
          ports:
            - { containerPort: 9000, name: api }
            - { containerPort: 9001, name: console }
          readinessProbe:
            httpGet: { path: /minio/health/ready, port: 9000 }
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            {{- toYaml (.Values.minio.resources | default dict) | nindent 12 }}
          volumeMounts:
            - { name: data, mountPath: /data }
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: minio-data }
---
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: {{ .Values.namespace }}
  labels: { app: minio }
spec:
  {{- if .Values.minio.clusterIP }}
  clusterIP: {{ .Values.minio.clusterIP }}
  {{- end }}
  selector: { app: minio }
  ports:
    - { name: api, port: 9000, targetPort: 9000 }
    - { name: console, port: 9001, targetPort: 9001 }
{{- end }}
```

- [ ] **Step 2: Add `minio` block to base `values.yaml`**

Add near the (still-present) `seaweedfs:` block:
```yaml
# MinIO (S3-compatible object store). Default ON for self-contained local/dev.
# AWS profile disables it and uses native S3.
minio:
  enabled: true
  image:
    repository: minio/minio
    tag: latest
  auth:
    rootUser: datapond
    rootPassword: datapond_s3_password
  persistence:
    size: 50Gi
  resources:
    requests: { cpu: 200m, memory: 512Mi }
    limits: { cpu: "1", memory: 1Gi }
```

- [ ] **Step 3: Verify render (inspection — helm unavailable)**

Confirm by inspection: `{{- if .Values.minio.enabled }}` wraps all three docs; `.Values.minio.*` paths exist in base values; `secretKeyRef` keys (`SEAWEEDFS_S3_USER/PASSWORD`) exist in secrets.yaml (they do, gated on seaweedfs.enabled — Task 4 re-gates). Run YAML sanity on values: `cd /Users/luke/datapond && python3 -c "import yaml; assert yaml.safe_load(open('helm/datapond/values.yaml'))['minio']['enabled'] is True; print('minio base OK')"`.

- [ ] **Step 4: Commit**

```bash
git add helm/datapond/templates/minio-deployment.yaml helm/datapond/values.yaml
git commit -m "feat(minio): add MinIO deployment + base values (alongside seaweedfs)"
```

---

## Task 2: MinIO bucket-init job

**Files:**
- Create: `helm/datapond/templates/minio-bucket-init-job.yaml`

**Interfaces:** Consumes `minio:9000`, `SEAWEEDFS_S3_USER/PASSWORD` secret, `.Values.polaris.warehouseBucket` (default `iceberg`).

- [ ] **Step 1: Create the job (mirrors seaweedfs-bucket-init logic, MinIO endpoint)**

`helm/datapond/templates/minio-bucket-init-job.yaml`:
```yaml
{{- if and .Values.minio.enabled .Values.polaris.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: minio-bucket-init
  namespace: {{ .Values.namespace }}
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 5
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: mc
          image: minio/mc:latest
          env:
            - name: S3_USER
              valueFrom: { secretKeyRef: { name: datapond-secrets, key: SEAWEEDFS_S3_USER } }
            - name: S3_PASS
              valueFrom: { secretKeyRef: { name: datapond-secrets, key: SEAWEEDFS_S3_PASSWORD } }
            - name: BUCKET
              value: "{{ .Values.polaris.warehouseBucket | default "iceberg" }}"
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -e
              for i in $(seq 1 36); do
                mc alias set local http://minio:9000 "$S3_USER" "$S3_PASS" && break
                echo "waiting for minio... ($i)"; sleep 5
              done
              mc mb --ignore-existing "local/$BUCKET"
              echo "bucket '$BUCKET' ready."
{{- end }}
```

- [ ] **Step 2: Verify (inspection)** — `{{- if and .Values.minio.enabled .Values.polaris.enabled }}` gate; secret keys exist; bucket name templated.

- [ ] **Step 3: Commit**

```bash
git add helm/datapond/templates/minio-bucket-init-job.yaml
git commit -m "feat(minio): bucket-init job (creates iceberg bucket on minio)"
```

---

## Task 3: Re-point storage consumers + CoreDNS to MinIO

**Files (modify):** `polaris-deployment.yaml`, `spark-config-configmap.yaml`, `trino-deployment.yaml`, `risingwave-statefulset.yaml`, `mlflow-deployment.yaml`, `jupyter-deployment.yaml`, `coredns-custom-configmap.yaml`

**Interfaces:** Every S3 endpoint string `http://seaweedfs-s3:8333` (or `seaweedfs-s3:8333`) becomes `http://minio:9000` (or `minio:9000`). path-style flags unchanged. CoreDNS gate/target → MinIO.

- [ ] **Step 1: Replace the endpoint string in all six consumer templates**

For each file, replace the SeaweedFS endpoint with the MinIO one (keep scheme and surrounding config identical):
- `polaris-deployment.yaml`: `AWS_ENDPOINT_URL_S3` and `AWS_ENDPOINT_URL` values `http://seaweedfs-s3:8333` → `http://minio:9000`.
- `spark-config-configmap.yaml`: `spark.sql.catalog.iceberg.s3.endpoint` and `spark.hadoop.fs.s3a.endpoint` `http://seaweedfs-s3:8333` → `http://minio:9000`.
- `trino-deployment.yaml`: `s3.endpoint=http://seaweedfs-s3:8333` → `s3.endpoint=http://minio:9000`.
- `risingwave-statefulset.yaml`: all three `RW_S3_ENDPOINT` (meta/compute/compactor) `http://seaweedfs-s3:8333` → `http://minio:9000`.
- `mlflow-deployment.yaml`: `MLFLOW_S3_ENDPOINT_URL` → `http://minio:9000`.
- `jupyter-deployment.yaml`: the S3 endpoint env (`SEAWEEDFS_S3_ENDPOINT` value) → `http://minio:9000`. Keep the env var NAME as-is (Stage 1) to avoid touching DuckDB notebook code; only the value changes.

Use exact-string edits; do not alter path-style flags or credential refs.

- [ ] **Step 2: Re-point CoreDNS to MinIO**

In `coredns-custom-configmap.yaml`: change the gate `{{- if .Values.seaweedfs.enabled }}` → `{{- if .Values.minio.enabled }}`; change the match/answer domain from `seaweedfs-s3.<ns>` to `minio.<ns>`; change the required value `.Values.seaweedfs.s3.clusterIP` → `.Values.minio.clusterIP` (update the `required` message text to reference `minio`).

- [ ] **Step 3: Verify (inspection)** — `grep -rn 'seaweedfs-s3:8333' helm/datapond/templates/` returns ONLY the soon-to-be-removed `seaweedfs-deployment.yaml` / `seaweedfs-bucket-init-job.yaml` (Task 4 removes them). No consumer still points at seaweedfs. CoreDNS references `minio` + `.Values.minio.clusterIP`.

- [ ] **Step 4: Commit**

```bash
git add helm/datapond/templates/polaris-deployment.yaml helm/datapond/templates/spark-config-configmap.yaml helm/datapond/templates/trino-deployment.yaml helm/datapond/templates/risingwave-statefulset.yaml helm/datapond/templates/mlflow-deployment.yaml helm/datapond/templates/jupyter-deployment.yaml helm/datapond/templates/coredns-custom-configmap.yaml
git commit -m "feat(minio): re-point all S3 consumers + coredns from seaweedfs to minio"
```

---

## Task 4: Remove SeaweedFS, re-gate secrets, clean values profiles

**Files:**
- Remove: `seaweedfs-deployment.yaml`, `seaweedfs-bucket-init-job.yaml`
- Modify: `secrets.yaml`, `values.yaml`, `values-dev.yaml`, `values-prod.yaml`, `values-onprem.yaml`, `values-quicktest.yaml`, `values-aws.yaml`

**Interfaces:** After this task no template references `seaweedfs`; credentials gate on `minio.enabled`; each profile sets `minio.enabled` (false only for aws) and a `minio.clusterIP` where coredns needs it.

- [ ] **Step 1: Remove SeaweedFS templates**

```bash
git rm helm/datapond/templates/seaweedfs-deployment.yaml helm/datapond/templates/seaweedfs-bucket-init-job.yaml
```

- [ ] **Step 2: Re-gate secrets**

In `secrets.yaml`, change `{{- if .Values.seaweedfs.enabled }}` (around the S3 cred block) → `{{- if .Values.minio.enabled }}`, and source values from `.Values.minio.auth.rootUser`/`.rootPassword` (keep the four key names `S3_ACCESS_KEY`,`S3_SECRET_KEY`,`SEAWEEDFS_S3_USER`,`SEAWEEDFS_S3_PASSWORD`).

- [ ] **Step 3: Update every values file**

- `values.yaml`: remove the `seaweedfs:` block (Task 1 already added `minio:`). Keep `storage` as-is for now (Stage 2 changes base default to AWS).
- `values-aws.yaml`: replace `seaweedfs: {enabled:false}` with `minio: {enabled:false}`.
- `values-dev.yaml`: remove BOTH duplicate `seaweedfs:` blocks; add `minio: {enabled:true, clusterIP:10.43.107.150, auth:{rootUser:datapond, rootPassword:datapond_dev}, persistence:{size:20Gi}}`.
- `values-quicktest.yaml`: remove BOTH duplicate `seaweedfs:` blocks; add `minio: {enabled:true, clusterIP:10.43.107.150, auth:{rootUser:datapond, rootPassword:datapond_dev}, persistence:{size:20Gi}}`.
- `values-onprem.yaml`: replace `seaweedfs:` block with `minio: {enabled:true, clusterIP:10.43.107.150, auth:{rootUser:datapond, rootPassword:datapond_s3_password}, persistence:{size:100Gi}}`.
- `values-prod.yaml`: remove BOTH duplicate `seaweedfs:` blocks; add `minio: {enabled:true, clusterIP:10.43.107.150, auth:{rootUser:CHANGE_THIS_MINIO_USER, rootPassword:CHANGE_THIS_MINIO_PASSWORD}, persistence:{size:500Gi}}` (with CHANGE THIS comments).

(Reuse the same K3s ClusterIP `10.43.107.150` the SeaweedFS coredns used — it is now the MinIO service IP; operators set their real one.)

- [ ] **Step 4: Verify (inspection + sanity)**

```bash
cd /Users/luke/datapond
grep -rn 'seaweedfs' helm/datapond/templates/ ; echo "templates seaweedfs refs above should be EMPTY"
for f in values values-dev values-prod values-onprem values-quicktest values-aws; do
  python3 -c "import yaml,sys; d=yaml.safe_load(open('helm/datapond/$f.yaml')); print('$f minio.enabled=', d.get('minio',{}).get('enabled'))"
done
```
Expected: no `seaweedfs` in templates; `minio.enabled` true for all except aws (false).

- [ ] **Step 5: Commit**

```bash
git add -A helm/datapond
git commit -m "feat(minio): remove seaweedfs templates, re-gate secrets, switch all profiles to minio"
```

---

## Task 5: CI render verification + runbook note

**Files:** none code; relies on CI `Helm chart lint` (renders all profiles).

- [ ] **Step 1: Push branch and open PR** so CI renders every profile (base/aws/dev/prod/onprem/quicktest). The `Helm chart lint` job must pass for all — that is the authoritative render gate (helm is not installed locally).

- [ ] **Step 2: If CI render fails**, read the failing profile/line from the job log and fix the specific template/values issue, then re-push. Do not mark complete until `Helm chart lint` is green.

- [ ] **Step 3: Add a MinIO note to the runbook**

In `docs/AWS_MVP_RUNBOOK.md`, add a short "Local/on-prem (MinIO)" subsection: MinIO replaces SeaweedFS; console at `minio:9001`; buckets auto-created by `minio-bucket-init`. Commit:
```bash
git add docs/AWS_MVP_RUNBOOK.md
git commit -m "docs: note MinIO (replaces seaweedfs) for local/on-prem in runbook"
```

---

## Self-Review

**Spec coverage (Stage 1 of migration spec):** MinIO add (T1-2), consumer + coredns re-point (T3), seaweedfs removal + secrets + values (T4), CI render verify (T5). Endpoint unification / base-AWS-default / coredns full-removal / IRSA explicitly deferred to Stage 2-3 per spec §1b. ✅

**Placeholder scan:** Template/job code is complete; per-file edits in T3/T4 name exact strings and `.Values` paths. `CHANGE_THIS_*` in prod are intentional operator placeholders (matches existing convention), not plan gaps.

**Consistency:** Service/endpoint `minio:9000` used uniformly across T1 (service), T2 (init), T3 (consumers), T4 (gating). Secret key names held constant in Stage 1 (`SEAWEEDFS_S3_USER/PASSWORD`) so T1/T2 secretKeyRefs match T4's re-gated secret. `minio.clusterIP` used by both the Service (T1) and CoreDNS (T3) — consistent. Each task leaves the chart renderable (MinIO added before SeaweedFS removed; consumers re-pointed before removal).
