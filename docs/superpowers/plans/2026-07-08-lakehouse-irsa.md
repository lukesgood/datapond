# Lakehouse-Service IRSA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the 6 S3-consuming lakehouse services (backend, trino, spark, jupyter, mlflow, polaris) IRSA-based S3 access on EKS via one shared IAM role + annotated ServiceAccounts, and fix the backend pyiceberg catalog to use the AWS credential chain (a latent bug on live K3s today).

**Spec:** `docs/superpowers/specs/2026-07-08-lakehouse-irsa-design.md`

**Architecture:** Additive, EKS-only IRSA replicating the existing LiteLLM→Bedrock pattern (`terraform/irsa.tf`, `litellm-serviceaccount.yaml`). One shared IAM role trusts all 6 ServiceAccount subjects; a ranged Helm template emits the 6 SAs (annotated only when `lakehouseIrsa.roleArn` is set). Everything is gated so K3s creates no IRSA resources and pods fall back to the node instance profile. The only runtime change is the backend pyiceberg credential-chain fix.

**Tech Stack:** Terraform (AWS provider ~>5.0), Helm, Python/pyiceberg, GitHub Actions, pytest.

## Global Constraints

- Terraform gated by `local.irsa_enabled` (`var.eks_oidc_provider_arn != ""`, already in irsa.tf); Helm SA annotations gated `{{- with .Values.lakehouseIrsa.roleArn }}`. K3s (empty ARN) creates no IRSA role and renders un-annotated SAs → node instance profile, unchanged behavior.
- ServiceAccount names are the SINGLE source of truth shared between Terraform (`var.lakehouse_sa_names`) and Helm (SA `metadata.name` + each deployment's `serviceAccountName`): `datapond-backend`, `datapond-trino`, `datapond-spark`, `datapond-jupyter`, `datapond-mlflow`, `datapond-polaris`. A mismatch silently breaks the trust policy.
- The shared S3 policy mirrors `iam.tf`'s `S3Data` sid EXACTLY: `s3:ListBucket/GetObject/PutObject/DeleteObject` on `aws_s3_bucket.data.arn` + `/*`. NO Bedrock.
- Terraform tree must stay `fmt`-clean + `validate`-green (the P0-5 CI gate). Verify with real terraform 1.10.5 (download — network works, `releases.hashicorp.com/terraform/1.10.5/...`). Do NOT commit `.terraform/` (gitignored since P0-5).
- Backend: local pytest baseline has 4 pre-existing failures (test_db_pool_config) + collection errors (test_iceberg_writer, test_pipelines) — not yours. Target the new test file directly.
- RisingWave is excluded (no S3). Branch: `feat/lakehouse-irsa`; squash-merge PR at the end.

---

### Task 1: Backend pyiceberg credential-chain fix (TDD)

**Files:**
- Modify: `backend/app/connectors/iceberg_catalog.py` (the RestCatalog FileIO props ~lines 32-40, and `_s3_endpoint()` ~45-50)
- Test: `backend/tests/test_iceberg_s3_props.py`

**Interfaces:**
- Produces: `iceberg_catalog._s3_fileio_props() -> dict` — returns S3 FileIO kwargs; includes static creds+endpoint when `S3_ACCESS_KEY`/`S3_SECRET_KEY` are set, else only `{"s3.region": ...}` (credential-chain mode).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_iceberg_s3_props.py`:

```python
"""_s3_fileio_props: static creds when injected (MinIO/onprem), credential-chain when not (AWS/IRSA)."""
import importlib
import pytest


def _fresh(monkeypatch, env: dict):
    for k in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_ENDPOINT", "S3_ENDPOINT_URL", "S3_REGION"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.connectors.iceberg_catalog as c
    return importlib.reload(c)


def test_static_creds_when_injected(monkeypatch):
    c = _fresh(monkeypatch, {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk",
                             "S3_ENDPOINT": "seaweedfs-s3:8333", "S3_REGION": "us-east-1"})
    p = c._s3_fileio_props()
    assert p["s3.access-key-id"] == "ak"
    assert p["s3.secret-access-key"] == "sk"
    assert p["s3.endpoint"] == "http://seaweedfs-s3:8333"   # scheme prefixed
    assert p["s3.path-style-access"] == "true"
    assert p["s3.region"] == "us-east-1"


def test_credential_chain_when_unset(monkeypatch):
    # AWS: empty endpoint, no keys → omit all static-cred/endpoint keys
    c = _fresh(monkeypatch, {"S3_ENDPOINT": "", "S3_REGION": "us-east-1"})
    p = c._s3_fileio_props()
    assert p == {"s3.region": "us-east-1"}
    for k in ("s3.access-key-id", "s3.secret-access-key", "s3.endpoint", "s3.path-style-access"):
        assert k not in p


def test_no_endpoint_no_http_fabrication(monkeypatch):
    # keys present but endpoint empty → no s3.endpoint key, no "http://" fabricated
    c = _fresh(monkeypatch, {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk", "S3_ENDPOINT": ""})
    p = c._s3_fileio_props()
    assert "s3.endpoint" not in p
    assert p["s3.access-key-id"] == "ak"


def test_region_default(monkeypatch):
    c = _fresh(monkeypatch, {})   # nothing set
    p = c._s3_fileio_props()
    assert p == {"s3.region": "us-east-1"}   # region defaults, nothing else
```

- [ ] **Step 2: Run → fail** (`cd backend && python3 -m pytest tests/test_iceberg_s3_props.py -v` → `AttributeError: _s3_fileio_props`).

- [ ] **Step 3: Implement.** In `backend/app/connectors/iceberg_catalog.py`, replace the inline `s3.*` kwargs in the RestCatalog call and rewrite `_s3_endpoint()`. Add the helper:

```python
def _s3_fileio_props() -> dict:
    """S3 FileIO kwargs for pyiceberg's RestCatalog.

    MinIO/onprem: static keys are injected as env → pass them + the endpoint.
    AWS/IRSA: no keys, empty endpoint → omit static-cred/endpoint keys so
    pyiceberg's S3FileIO uses the default AWS credential chain (instance profile
    on K3s, projected web-identity token under IRSA)."""
    props = {"s3.region": os.getenv("S3_REGION", "us-east-1")}
    ak = os.getenv("S3_ACCESS_KEY", "").strip()
    sk = os.getenv("S3_SECRET_KEY", "").strip()
    if ak and sk:
        props["s3.access-key-id"] = ak
        props["s3.secret-access-key"] = sk
        props["s3.path-style-access"] = "true"
    ep = _s3_endpoint()
    if ep:
        props["s3.endpoint"] = ep
    return props


def _s3_endpoint() -> str:
    """Return an http-scheme'd endpoint, or '' when none is configured (AWS native S3)."""
    ep = (os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT", "")).strip()
    if not ep:
        return ""
    return ep if ep.startswith("http") else f"http://{ep}"
```

Then in `get_catalog()`, replace the five inline `"s3.*"` entries (`s3.endpoint`, `s3.access-key-id`, `s3.secret-access-key`, `s3.path-style-access`, `s3.region`) with a spread of the helper. The RestCatalog kwargs dict becomes:

```python
                _catalog = RestCatalog(
                    name="datapond",
                    **{
                        "uri":       os.getenv("POLARIS_URI", "http://polaris:8181/api/catalog"),
                        "warehouse": os.getenv("POLARIS_WAREHOUSE", "iceberg"),
                        "credential": f"{client_id}:{client_secret}",
                        "scope":      "PRINCIPAL_ROLE:ALL",
                        # S3 FileIO: static keys on MinIO, credential-chain on AWS (see _s3_fileio_props)
                        **_s3_fileio_props(),
                    },
                )
```

Note: `component_secret("S3_SECRET_KEY", "datapond_dev", ...)` is REMOVED from this path — the helper reads `S3_SECRET_KEY` directly and treats unset as credential-chain mode (do NOT fall back to a literal). Keep the `component_secret` import if still used elsewhere in the file; if it becomes unused, remove the import.

- [ ] **Step 4: Run → pass** (`cd backend && python3 -m pytest tests/test_iceberg_s3_props.py -v` → 4 pass) + `python3 -m py_compile app/connectors/iceberg_catalog.py`. Confirm no regression in the resolvable suite: `python3 -m pytest tests/ -q --ignore=tests/test_iceberg_writer.py --ignore=tests/test_pipelines 2>&1 | tail -2` (unchanged vs baseline).

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/lakehouse-irsa   # if not already on it
git add backend/app/connectors/iceberg_catalog.py backend/tests/test_iceberg_s3_props.py
git commit -m "fix(iceberg): S3 FileIO uses credential chain on AWS (omit bogus static key)"
```

---

### Task 2: Terraform shared lakehouse-S3 IRSA role

**Files:**
- Modify: `terraform/irsa.tf` (append), `terraform/variables.tf` (append), `terraform/outputs.tf` (append)

**Interfaces:**
- Consumes: existing `local.irsa_enabled`, `var.eks_oidc_provider_arn/url`, `var.k8s_namespace`, `var.name_prefix`, `aws_s3_bucket.data` (s3.tf).
- Produces: `aws_iam_role.lakehouse_s3` + output `lakehouse_s3_role_arn`. Helm (Task 3) consumes the ARN via `lakehouseIrsa.roleArn`.

- [ ] **Step 1: variables.tf — append**:

```hcl
variable "lakehouse_sa_names" {
  type    = list(string)
  default = ["datapond-backend", "datapond-trino", "datapond-spark", "datapond-jupyter", "datapond-mlflow", "datapond-polaris"]
}
```

- [ ] **Step 2: irsa.tf — append after the litellm blocks** (reuses `local.irsa_enabled`):

```hcl

# ── Shared lakehouse S3 IRSA role (backend/trino/spark/jupyter/mlflow/polaris) ──
# One role trusted by all 6 lakehouse ServiceAccounts; same S3 grant as iam.tf's
# instance profile. Created only on EKS (eks_oidc_provider_arn set); K3s uses the
# node instance profile.
data "aws_iam_policy_document" "lakehouse_s3_assume" {
  count = local.irsa_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:sub"
      values   = [for sa in var.lakehouse_sa_names : "system:serviceaccount:${var.k8s_namespace}:${sa}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lakehouse_s3" {
  count              = local.irsa_enabled ? 1 : 0
  name               = "${var.name_prefix}-lakehouse-s3"
  assume_role_policy = data.aws_iam_policy_document.lakehouse_s3_assume[0].json
}

data "aws_iam_policy_document" "lakehouse_s3" {
  count = local.irsa_enabled ? 1 : 0
  statement {
    sid     = "S3Data"
    actions = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "lakehouse_s3" {
  count  = local.irsa_enabled ? 1 : 0
  name   = "${var.name_prefix}-lakehouse-s3"
  role   = aws_iam_role.lakehouse_s3[0].id
  policy = data.aws_iam_policy_document.lakehouse_s3[0].json
}
```

- [ ] **Step 3: outputs.tf — append** (mirror the `litellm_bedrock_role_arn` conditional form):

```hcl
output "lakehouse_s3_role_arn" { value = local.irsa_enabled ? aws_iam_role.lakehouse_s3[0].arn : "" }
```

- [ ] **Step 4: Verify with real terraform + commit**

```bash
cd /tmp && curl -fsSL -o tf.zip "https://releases.hashicorp.com/terraform/1.10.5/terraform_1.10.5_$(uname -s | tr A-Z a-z)_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').zip" && unzip -o tf.zip && export PATH=/tmp:$PATH
cd /Users/luke/datapond
terraform -chdir=terraform fmt -check -recursive     # exit 0
terraform -chdir=terraform init -backend=false -input=false && terraform -chdir=terraform validate   # Success
git status --short   # ONLY the 3 .tf files (no .terraform/)
git add terraform/irsa.tf terraform/variables.tf terraform/outputs.tf
git commit -m "feat(tf): shared lakehouse-S3 IRSA role trusting all 6 lakehouse ServiceAccounts"
```
(If terraform can't be downloaded, say so and rely on careful HCL — CI validates.)

---

### Task 3: Helm — ServiceAccount template + serviceAccountName + values

**Files:**
- Create: `helm/datapond/templates/lakehouse-serviceaccounts.yaml`
- Modify: `helm/datapond/templates/{backend,trino,jupyter,mlflow,polaris}-deployment.yaml`, `helm/datapond/templates/spark-statefulset.yaml` (2 pod specs), `helm/datapond/values.yaml`

**Interfaces:**
- Consumes: `lakehouse_s3_role_arn` (Task 2) via `lakehouseIrsa.roleArn`.
- Produces: 6 ServiceAccounts named `datapond-<svc>` (matching `var.lakehouse_sa_names`).

- [ ] **Step 1: create `helm/datapond/templates/lakehouse-serviceaccounts.yaml`**:

```yaml
{{- /* One ServiceAccount per S3-consuming lakehouse service. Annotated with the
       shared IRSA role only when lakehouseIrsa.roleArn is set (EKS); un-annotated
       on K3s ⇒ pods use the node instance profile. SA names MUST match
       terraform var.lakehouse_sa_names. */}}
{{- $svcs := list
  (dict "name" "datapond-backend" "enabled" .Values.backend.enabled)
  (dict "name" "datapond-trino"   "enabled" .Values.trino.enabled)
  (dict "name" "datapond-spark"   "enabled" .Values.spark.enabled)
  (dict "name" "datapond-jupyter" "enabled" .Values.jupyter.enabled)
  (dict "name" "datapond-mlflow"  "enabled" .Values.mlflow.enabled)
  (dict "name" "datapond-polaris" "enabled" .Values.polaris.enabled) }}
{{- range $svcs }}
{{- if .enabled }}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .name }}
  namespace: {{ $.Values.namespace }}
  labels:
    app.kubernetes.io/managed-by: {{ $.Release.Service }}
  {{- with $.Values.lakehouseIrsa.roleArn }}
  annotations:
    eks.amazonaws.com/role-arn: {{ . | quote }}
  {{- end }}
{{- end }}
{{- end }}
```

- [ ] **Step 2: add `serviceAccountName` to each pod spec.** For each file, insert the line as the FIRST line under the pod-template `spec:` (sibling to `containers:`). Exact locations (the `spec:` under `template:`):
  - `backend-deployment.yaml` line 22 (`    spec:`) → add `      serviceAccountName: {{ .Values.backend.serviceAccountName | default "datapond-backend" }}`
  - `trino-deployment.yaml` line 24 → `{{ .Values.trino.serviceAccountName | default "datapond-trino" }}`
  - `jupyter-deployment.yaml` line 20 → `{{ .Values.jupyter.serviceAccountName | default "datapond-jupyter" }}`
  - `mlflow-deployment.yaml` line 20 → `{{ .Values.mlflow.serviceAccountName | default "datapond-mlflow" }}`
  - `polaris-deployment.yaml` line 23 → `{{ .Values.polaris.serviceAccountName | default "datapond-polaris" }}`
  - `spark-statefulset.yaml` — BOTH pod specs: after the master `template:`/`spec` (~line 24-30 area, the `spec:` above `containers:` at line 30) AND the worker one (~line 124, `spec:` above `containers:` at line 130) → `{{ .Values.spark.serviceAccountName | default "datapond-spark" }}`

  Read each file first to place the line at the correct indentation directly under the pod `spec:` (6 spaces for a Deployment `template.spec`, matching the `containers:` indent). Example for backend:
```yaml
    spec:
      serviceAccountName: {{ .Values.backend.serviceAccountName | default "datapond-backend" }}
      containers:
```

- [ ] **Step 3: values.yaml** — add the shared IRSA key + backend SA name.
  - Add a top-level block (near the `auth:`/`litellm` area, but top-level):
```yaml
# EKS IRSA — shared IAM role ARN for the S3-consuming lakehouse ServiceAccounts
# (backend/trino/spark/jupyter/mlflow/polaris). Set to `terraform output
# lakehouse_s3_role_arn` on EKS; leave empty on K3s/EC2 (node instance profile) or MinIO.
lakehouseIrsa:
  roleArn: ""
```
  - In the `backend:` block (after `name: backend`, ~line 68), add `serviceAccountName: datapond-backend` so the SA the template creates is the one the pod + rbac-backend RoleBinding use.

- [ ] **Step 4: verify rbac-backend binding.** No change needed to rbac-backend.yaml — it already binds `.Values.backend.serviceAccountName | default "default"` (now `datapond-backend`) + `backend`. Confirm by rendering intent: the RoleBinding subject will be `datapond-backend`, which the SA template creates. (If you set backend.serviceAccountName, the reader-role binds it — good.)

- [ ] **Step 5: Verify + commit**

```bash
python3 -c "import yaml,glob; [list(yaml.safe_load_all(open(f))) for f in ['helm/datapond/values.yaml']]" && echo VALUES-OK
# every serviceAccountName references a name the SA template creates:
grep -rn "serviceAccountName:" helm/datapond/templates/ | grep -v litellm
git add helm/datapond
git commit -m "feat(helm): IRSA ServiceAccounts + serviceAccountName for 6 lakehouse services"
```

---

### Task 4: CI render assertions + PR + final review

**Files:**
- Modify: `.github/workflows/ci.yml` (helm-lint job — add IRSA assertions)

- [ ] **Step 1: add helm render assertions** after the existing helm-lint assertions (safe if-form, matching the file's idiom):

```bash
          echo "== lakehouse IRSA ServiceAccounts =="
          # default render (no roleArn): 6 SAs exist, NO IRSA annotation leaks
          d=$(helm template datapond helm/datapond --values helm/datapond/values-onprem.yaml)
          for sa in datapond-backend datapond-trino datapond-spark datapond-jupyter datapond-mlflow datapond-polaris; do
            echo "$d" | grep -q "name: $sa" || { echo "FAIL: SA $sa missing (onprem render)"; exit 1; }
          done
          if echo "$d" | grep -q 'eks.amazonaws.com/role-arn'; then
            echo "FAIL: IRSA annotation leaked into a no-roleArn render"; exit 1
          fi
          # with roleArn set: annotation renders on the SAs
          a=$(helm template datapond helm/datapond --values helm/datapond/values-onprem.yaml --set lakehouseIrsa.roleArn=arn:aws:iam::123456789012:role/datapond-lakehouse-s3)
          echo "$a" | grep -q 'eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/datapond-lakehouse-s3"' || { echo "FAIL: IRSA annotation not rendered when roleArn set"; exit 1; }
          echo "$a" | grep -q 'serviceAccountName: datapond-backend' || { echo "FAIL: backend serviceAccountName not set"; exit 1; }
          echo "OK: lakehouse IRSA wired"
```
(onprem profile is used because it enables all 6 services — base/foundation disable most; confirm onprem has trino/spark/polaris/jupyter/mlflow enabled by reading values-onprem.yaml, else use the base `helm template datapond helm/datapond` which inherits enabled:true for all.)

- [ ] **Step 2: YAML validity**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo CI-YAML-OK
```

- [ ] **Step 3: push + PR**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: assert lakehouse IRSA SAs render + no annotation leak without roleArn"
git push -u origin feat/lakehouse-irsa
export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
gh pr create --title "feat: lakehouse-service IRSA (S3 IAM access) + pyiceberg credential-chain fix" --body "..."
```
PR body: shared lakehouse-S3 IRSA role (6 SAs, EKS-gated); ranged SA template + serviceAccountName on 6 workloads; backend pyiceberg credential-chain fix (latent bug — was passing a bogus static key on AWS); additive/K3s-safe; verified with real terraform + helm assertions. Out of scope (spec §7): live EKS apply, per-service prefix scoping, RisingWave.

- [ ] **Step 4:** CI green — terraform-validate (new role) + helm-lint (new assertions) + backend tests. Fix any failure.
- [ ] **Step 5:** Final whole-branch review (controller dispatches).

---

## Self-Review

**Spec coverage:** §2 TF role → Task 2 (assume-doc with the 6-subject StringEquals list, role, S3 policy mirroring iam.tf, output); §3a SA template → Task 3 Step 1 (ranged, enabled+roleArn gated, names match); §3b serviceAccountName → Task 3 Step 2 (all 6 incl. spark ×2); §3c RBAC → Task 3 Step 4 (backend.serviceAccountName set, binding already covers it); §3d values → Task 3 Step 3; §4 backend fix → Task 1 (TDD, helper, credential-chain); §5 testing → Task 1 pytest + Task 4 helm assertions + Task 2 terraform validate; §6 docs → folded into PR body / values comments (a dedicated README para can be added in Task 4 if desired — the values comments carry the enablement guidance). §7 out-of-scope honored.

**Placeholder scan:** all HCL/YAML/Python is complete + literal. The `lakehouseIrsa.roleArn` empty default is the documented EKS hook, not a placeholder. PR body "..." followed by explicit content. No TBDs.

**Consistency:** SA names identical across Task 2 (`var.lakehouse_sa_names`), Task 3 (SA template + serviceAccountName defaults), and Task 4 (assertions): `datapond-{backend,trino,spark,jupyter,mlflow,polaris}`. `_s3_fileio_props()` defined in Task 1 is the only new backend symbol. `lakehouse_s3_role_arn` output (Task 2) ↔ `lakehouseIrsa.roleArn` values (Task 3) ↔ the `--set lakehouseIrsa.roleArn` assertion (Task 4). Shared role name `${name_prefix}-lakehouse-s3` = `datapond-lakehouse-s3` matches the assertion's example ARN.
