# Lakehouse-Service IRSA (S3 IAM access) — Design

**Date**: 2026-07-08
**Status**: Design approved (pre-implementation)
**Context**: Completes the deferred item from the SeaweedFS→MinIO migration spec §1b Stage 3 / §5 ("AWS IRSA 완전 구성 — lakehouse Pod들이 S3에 IAM 역할로 접근"). The endpoint-gating plumbing is already done (Stage 2: on AWS `storage.endpoint=""` ⇒ no static S3 keys injected ⇒ services fall back to the AWS credential chain). Live is single-EC2 K3s using the `iam.tf` EC2 instance profile — all S3 services already work there. IRSA is **additive, EKS-only**, gated by `eks_oidc_provider_arn`, replicating the existing LiteLLM→Bedrock IRSA (#103, `terraform/irsa.tf`). Six services touch S3: backend, trino, spark, jupyter, mlflow, polaris (RisingWave is vestigial — `hummock+memory`, no S3).

## 1. Decisions (confirmed)

| Decision | Choice |
|---|---|
| Service scope | **All 6 S3 consumers** (backend, trino, spark, jupyter, mlflow, polaris). RisingWave excluded (no S3) |
| Role model | **One shared lakehouse-S3 IAM role**, trust policy allows all 6 ServiceAccount subjects, each SA annotated with the same role ARN. Identical S3 access to the one bucket ⇒ no least-privilege lost |
| SA templating | **One values-driven ServiceAccount template ranging over the 6 services** (DRY, Approach A) |
| Gating | All Terraform gated by `local.irsa_enabled` (`eks_oidc_provider_arn != ""`); all Helm SA annotations gated by `lakehouseIrsa.roleArn` presence — K3s creates no IRSA resources and renders un-annotated SAs (falls back to node instance profile) |
| Runtime change | ONLY the backend pyiceberg credential-chain fix (fixes a latent bug affecting live K3s today) |
| Verification | terraform fmt/validate (P0-5 CI gate) + Helm render assertions + backend pytest. NO live EKS apply (AWS-live backlog item) |

## 2. Terraform — shared lakehouse-S3 IRSA role (`terraform/irsa.tf`, `variables.tf`, `outputs.tf`)

Extend `irsa.tf` (reuse the `local.irsa_enabled` gate). New variable in `variables.tf`:
```hcl
variable "lakehouse_sa_names" {
  type    = list(string)
  default = ["datapond-backend", "datapond-trino", "datapond-spark", "datapond-jupyter", "datapond-mlflow", "datapond-polaris"]
}
```

Add to `irsa.tf`:
- `data.aws_iam_policy_document.lakehouse_s3_assume` (`count = local.irsa_enabled ? 1 : 0`): `sts:AssumeRoleWithWebIdentity`, Federated principal `[var.eks_oidc_provider_arn]`, ONE `StringEquals` condition on `"${var.eks_oidc_provider_url}:sub"` with `values = [for sa in var.lakehouse_sa_names : "system:serviceaccount:${var.k8s_namespace}:${sa}"]` (IAM value-list = OR, so all 6 SAs match), plus the `:aud = sts.amazonaws.com` condition.
- `aws_iam_role.lakehouse_s3` (name `${var.name_prefix}-lakehouse-s3`, `assume_role_policy = ...lakehouse_s3_assume[0].json`).
- `data.aws_iam_policy_document.lakehouse_s3`: the S3 statement copied verbatim from `iam.tf`'s `S3Data` sid — `actions = ["s3:ListBucket","s3:GetObject","s3:PutObject","s3:DeleteObject"]`, `resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]`. NO Bedrock.
- `aws_iam_role_policy.lakehouse_s3` attachment.

`outputs.tf`: `output "lakehouse_s3_role_arn" { value = local.irsa_enabled ? aws_iam_role.lakehouse_s3[0].arn : "" }` (matches the existing `litellm_bedrock_role_arn` output's conditional form).

## 3. Helm — ranged ServiceAccount template + serviceAccountName wiring

### 3a. `helm/datapond/templates/lakehouse-serviceaccounts.yaml` (new)
Ranges over the 6 services. Each SA is emitted only when its component is enabled; annotated only when `lakehouseIrsa.roleArn` is set. Sketch:
```yaml
{{- $svcs := list
  (dict "name" "datapond-backend"  "enabled" .Values.backend.enabled)
  (dict "name" "datapond-trino"    "enabled" .Values.trino.enabled)
  (dict "name" "datapond-spark"    "enabled" .Values.spark.enabled)
  (dict "name" "datapond-jupyter"  "enabled" .Values.jupyter.enabled)
  (dict "name" "datapond-mlflow"   "enabled" .Values.mlflow.enabled)
  (dict "name" "datapond-polaris"  "enabled" .Values.polaris.enabled) }}
{{- range $svcs }}
{{- if .enabled }}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .name }}
  namespace: {{ $.Values.namespace }}
  {{- with $.Values.lakehouseIrsa.roleArn }}
  annotations:
    eks.amazonaws.com/role-arn: {{ . | quote }}
  {{- end }}
{{- end }}
{{- end }}
```
SA names must exactly match `var.lakehouse_sa_names` (the trust-policy subjects).

### 3b. `serviceAccountName:` on each S3 workload's POD spec (not just metadata)
- `backend-deployment.yaml` — `serviceAccountName: {{ .Values.backend.serviceAccountName | default "datapond-backend" }}`
- `trino-deployment.yaml` — `{{ .Values.trino.serviceAccountName | default "datapond-trino" }}`
- `spark-statefulset.yaml` — BOTH the master and worker pod specs → `datapond-spark`
- `jupyter-deployment.yaml` — `datapond-jupyter`
- `mlflow-deployment.yaml` — `datapond-mlflow`
- `polaris-deployment.yaml` — `datapond-polaris`
(added inside `spec.template.spec`, sibling to `containers:`.)

### 3c. RBAC reconciliation (backend)
`rbac-backend.yaml` binds `.Values.backend.serviceAccountName | default "default"`. Set `backend.serviceAccountName: datapond-backend` in values so the RoleBinding targets the same SA the IRSA template creates. Confirm the RoleBinding subject list includes `datapond-backend` (the existing template already hedges by binding the configured name + `default`). The other 5 services have no K8s-API RBAC needs — their SAs are IRSA-only.

### 3d. values
Base `values.yaml`: add `lakehouseIrsa: { roleArn: "" }` (comment: "EKS IRSA — set to `terraform output lakehouse_s3_role_arn`; leave empty on K3s/EC2 (node instance profile) or MinIO"). Set `backend.serviceAccountName: datapond-backend`. `values-aws.yaml`: commented placeholder next to the existing litellm roleArn note.

## 4. Backend pyiceberg credential-chain fix (`backend/app/connectors/iceberg_catalog.py`)

The ONLY runtime change. Today (lines ~34-39) the RestCatalog FileIO props unconditionally include `s3.access-key-id = os.getenv("S3_ACCESS_KEY", "datapond")`, `s3.secret-access-key = component_secret("S3_SECRET_KEY", "datapond_dev")`, `s3.endpoint = _s3_endpoint()` (defaulting `seaweedfs-s3:8333`), `s3.path-style-access = "true"`. On AWS this passes a bogus static key + a fabricated `http://` endpoint to S3FileIO instead of using the instance profile — a latent bug on live K3s.

New helper `_s3_fileio_props() -> dict`:
- Read `S3_ACCESS_KEY`/`S3_SECRET_KEY` and `S3_ENDPOINT`/`S3_ENDPOINT_URL` from env WITHOUT the literal fallbacks.
- **Keys present (MinIO/onprem)**: return `{s3.access-key-id, s3.secret-access-key, s3.endpoint (http-prefixed), s3.path-style-access "true", s3.region}` — current behavior preserved.
- **Keys absent/empty (AWS)**: return `{s3.region}` ONLY — omit access-key/secret/endpoint/path-style so pyiceberg S3FileIO uses the default AWS credential chain (instance profile / IRSA web-identity token).
- The catalog builder spreads `**_s3_fileio_props()` into the RestCatalog kwargs.
- `_s3_endpoint()`: only `http://`-prefix a NON-empty endpoint; return "" / signal-omit when `S3_ENDPOINT` is empty (no fabrication). Fold into the helper.

Mirrors the already-correct conditional pattern in `storage.py:58-72`. Same catalog is used by the writer (`iceberg_writer.py`), so the fix covers reads and writes.

## 5. Testing

- **Backend pytest** `backend/tests/test_iceberg_s3_props.py`: `_s3_fileio_props()` — (a) `S3_ACCESS_KEY`+`S3_SECRET_KEY`+`S3_ENDPOINT` set → dict includes `s3.access-key-id`, `s3.secret-access-key`, `s3.endpoint` (http-prefixed), `s3.path-style-access`, `s3.region`; (b) all unset → dict has ONLY `s3.region`, NONE of the static-cred/endpoint keys (credential-chain mode); (c) `S3_ENDPOINT` empty string → no `http://` fabrication. Run against the existing backend suite baseline (4 pre-existing local failures unrelated).
- **Terraform**: the P0-5 `terraform-validate` CI job validates the new irsa.tf blocks (fmt + validate). Implementers verify with real terraform 1.10.5 (download; the P0-5 pattern).
- **Helm CI render assertions** (helm-lint job): with `--set lakehouseIrsa.roleArn=arn:aws:iam::x:role/y` the 6 SAs render `eks.amazonaws.com/role-arn`; default render (no roleArn) → SAs render WITHOUT annotation and each deployment sets its `serviceAccountName`; assert no `eks.amazonaws.com/role-arn` leaks into the default render.

## 6. Docs (`terraform/README.md`, values-aws note)

EKS enablement: `terraform apply` with `eks_oidc_provider_arn`/`_url` set creates the lakehouse-s3 role; set Helm `lakehouseIrsa.roleArn` = `terraform output lakehouse_s3_role_arn` (and `litellm.serviceAccount.roleArn` = the bedrock output). K3s/MinIO: leave empty (node instance profile / static keys). The shared role mirrors `iam.tf`'s S3 grant on the one iceberg bucket.

## 7. Out of scope

Live EKS apply (AWS-live backlog); per-service S3 prefix scoping (breaks cross-engine Iceberg table sharing via the shared Polaris catalog); RisingWave (no S3); replacing/removing the K3s instance-profile path (IRSA is additive, they coexist); changing the LiteLLM→Bedrock role; a dedicated `values-eks.yaml` (extend `values-aws.yaml` — roleArn defaults empty, harmless on K3s).
