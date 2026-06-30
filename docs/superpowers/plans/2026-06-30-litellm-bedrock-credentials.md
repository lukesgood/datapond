# LiteLLM Bedrock Credential Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the LiteLLM gateway actually authenticate to Amazon Bedrock on AWS — via IRSA (EKS, keyless, recommended), a static-key fallback (portable), or the EC2 instance profile (current PoC) — and document Bedrock configuration end-to-end.

**Background / current state:** Bedrock works on the live single-node EC2 K3s PoC only by accident — the LiteLLM pod inherits the node instance-profile credentials via IMDS. On EKS the LiteLLM pod has **no AWS credentials** (`litellm-deployment.yaml` sets no `AWS_*` env and no serviceAccount/IRSA), so Bedrock InvokeModel would fail. The Bedrock model_list (embed/default/chat + `aws_region_name`), the `bedrock` provider in `ai_backends.py`, and runtime backend registration already exist — only credential delivery to the LiteLLM pod is missing. Ollama and vLLM are already `enabled:false` in base and AWS profiles (local LLM runtimes are sovereign/on-prem options only).

**Design decisions:**
- The backend calls Bedrock **only via the LiteLLM gateway**, so credentials are needed by **one pod (LiteLLM)**. Wire them there.
- Three credential modes, in preference order: **IRSA** (EKS — serviceAccount annotated with an IAM role; keyless) → **static keys** (env from secret; portable, e.g. non-EKS) → **instance profile** (default chain; current PoC, no config). All three converge on boto3's default credential chain once the pod has a role/keys.
- Keep secret-based static keys OPTIONAL and OFF by default (PoC/EKS shouldn't need them).
- Terraform IRSA role is OPTIONAL (only for EKS; created when an OIDC provider is supplied). The existing EC2 instance-profile role (PR #100) stays for the K3s PoC.

**Tech Stack:** Helm (Go templates, ServiceAccount), Kubernetes IRSA, Terraform (IAM OIDC trust), Amazon Bedrock, LiteLLM.

## Global Constraints

- Chart root `helm/datapond`. `helm`/`terraform` NOT installed locally → render verified by inspection + CI `Helm chart lint`; terraform by inspection. Keep all profiles rendering.
- Additive & backward-compatible: with no new values set, LiteLLM behaves exactly as today (default serviceAccount, no AWS env → instance-profile/default chain). Non-AWS profiles unaffected.
- Do NOT put AWS secret keys in values; static keys come from the `datapond-secrets` Secret only, gated.
- The backend needs no AWS creds (it uses the gateway) — do not add any to backend.

---

## File Structure

**Created:**
- `helm/datapond/templates/litellm-serviceaccount.yaml` — ServiceAccount (optional IRSA `eks.amazonaws.com/role-arn` annotation).
- `terraform/irsa.tf` — optional IAM role with EKS OIDC trust for the LiteLLM serviceAccount (Bedrock invoke).
- `docs/AWS_BEDROCK_SETUP.md` — Bedrock configuration guide.

**Modified:**
- `helm/datapond/templates/litellm-deployment.yaml` — `serviceAccountName` + optional `AWS_*` env.
- `helm/datapond/values.yaml` — `litellm.serviceAccount.*`, `litellm.aws.*` defaults.
- `helm/datapond/values-aws.yaml` — explicit `vllm.enabled:false`; doc-comment for IRSA roleArn.
- `terraform/variables.tf`, `terraform/outputs.tf` — OIDC inputs + IRSA role ARN output.
- `docs/AWS_MVP_RUNBOOK.md` — Bedrock credential section.
- `docs/superpowers/specs/2026-06-30-seaweedfs-to-minio-storage-migration-design.md` — note Stage-3 IRSA (LiteLLM) done.

---

## Task 1: LiteLLM ServiceAccount + IRSA + static-key env (Helm)

**Files:** Create `helm/datapond/templates/litellm-serviceaccount.yaml`; modify `helm/datapond/templates/litellm-deployment.yaml`, `helm/datapond/values.yaml`, `helm/datapond/values-aws.yaml`.

**Interfaces:** Produces a ServiceAccount named `{{ .Values.litellm.serviceAccount.name | default "litellm" }}` (created when `litellm.serviceAccount.create`), optionally IRSA-annotated; the LiteLLM Deployment runs as it; optional `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env from secret when `litellm.aws.staticCredentials`.

- [ ] **Step 1: Add values defaults to base `values.yaml` (under the `litellm:` block)**
```yaml
  serviceAccount:
    create: true
    name: litellm
    # For EKS IRSA, set the IAM role ARN (keyless Bedrock access). Leave empty
    # on K3s/EC2 (uses the node instance profile) or when using static keys.
    roleArn: ""
  aws:
    # Inject static AWS creds (AWS_ACCESS_KEY_ID/SECRET from datapond-secrets) into
    # the LiteLLM pod for Bedrock. Leave false on EKS (IRSA) or EC2 (instance profile).
    staticCredentials: false
```

- [ ] **Step 2: Create `helm/datapond/templates/litellm-serviceaccount.yaml`**
```yaml
{{- if and .Values.litellm.enabled .Values.litellm.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .Values.litellm.serviceAccount.name | default "litellm" }}
  namespace: {{ .Values.namespace }}
  labels:
    app: {{ .Values.litellm.name }}
  {{- with .Values.litellm.serviceAccount.roleArn }}
  annotations:
    eks.amazonaws.com/role-arn: {{ . | quote }}
  {{- end }}
{{- end }}
```

- [ ] **Step 3: Wire the Deployment (`litellm-deployment.yaml`)**
Under `spec.template.spec` (the line after `spec:` at ~line 95, before `initContainers:`), add:
```yaml
      serviceAccountName: {{ .Values.litellm.serviceAccount.name | default "default" }}
```
In the LiteLLM **main container** env list (the block containing `LITELLM_MASTER_KEY`, ~line 138), append:
```yaml
        {{- if .Values.litellm.aws.staticCredentials }}
        - name: AWS_ACCESS_KEY_ID
          valueFrom: { secretKeyRef: { name: datapond-secrets, key: AWS_ACCESS_KEY_ID } }
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom: { secretKeyRef: { name: datapond-secrets, key: AWS_SECRET_ACCESS_KEY } }
        {{- end }}
```
(When `staticCredentials` is true, the operator must add `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` to the secret; document this. When false, no AWS env → boto3 uses IRSA role or instance profile.)

- [ ] **Step 4: `values-aws.yaml` — make intent explicit**
Add `vllm:\n  enabled: false` (parity with ollama, even though base already defaults false), and a commented IRSA hint under litellm:
```yaml
litellm:
  serviceAccount:
    # Set to the IRSA role ARN from `terraform output litellm_bedrock_role_arn`.
    roleArn: ""   # e.g. arn:aws:iam::<acct>:role/datapond-litellm-bedrock
```
(Keep existing litellm.config.model_list.)

- [ ] **Step 5: Verify (inspection — helm unavailable)**
Confirm: SA template gates on create; `eks.amazonaws.com/role-arn` only renders when roleArn set (`with` skips empty); deployment has `serviceAccountName`; AWS env only under `staticCredentials`; YAML indentation valid. `python3 -c "import yaml; d=yaml.safe_load(open('helm/datapond/values.yaml')); print(d['litellm']['serviceAccount'], d['litellm']['aws'])"`.

- [ ] **Step 6: Commit**
```bash
git add helm/datapond/templates/litellm-serviceaccount.yaml helm/datapond/templates/litellm-deployment.yaml helm/datapond/values.yaml helm/datapond/values-aws.yaml
git commit -m "feat(litellm): ServiceAccount + IRSA + static-key option for Bedrock credentials"
```

---

## Task 2: Terraform IRSA role for LiteLLM → Bedrock

**Files:** Create `terraform/irsa.tf`; modify `terraform/variables.tf`, `terraform/outputs.tf`.

**Interfaces:** When an EKS OIDC provider is supplied, creates an IAM role trusted by the `litellm` serviceAccount with `bedrock:InvokeModel*`. Output `litellm_bedrock_role_arn` for Helm `litellm.serviceAccount.roleArn`. No-op when OIDC vars are empty (K3s PoC uses the instance profile from iam.tf).

- [ ] **Step 1: Add variables (`terraform/variables.tf`)**
```hcl
variable "eks_oidc_provider_arn" { type = string  default = "" }   # arn:aws:iam::<acct>:oidc-provider/oidc.eks.<region>.amazonaws.com/id/XXXX
variable "eks_oidc_provider_url" { type = string  default = "" }   # oidc.eks.<region>.amazonaws.com/id/XXXX (no https://)
variable "k8s_namespace"         { type = string  default = "datapond" }
variable "litellm_sa_name"       { type = string  default = "litellm" }
```

- [ ] **Step 2: Create `terraform/irsa.tf`**
```hcl
# Optional IRSA role for the LiteLLM serviceAccount to call Bedrock on EKS.
# Created only when eks_oidc_provider_arn is set (K3s/EC2 PoC uses the instance profile in iam.tf).
locals {
  irsa_enabled = var.eks_oidc_provider_arn != ""
}

data "aws_iam_policy_document" "litellm_irsa_assume" {
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
      values   = ["system:serviceaccount:${var.k8s_namespace}:${var.litellm_sa_name}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "litellm_bedrock" {
  count              = local.irsa_enabled ? 1 : 0
  name               = "${var.name_prefix}-litellm-bedrock"
  assume_role_policy = data.aws_iam_policy_document.litellm_irsa_assume[0].json
}

data "aws_iam_policy_document" "litellm_bedrock" {
  count = local.irsa_enabled ? 1 : 0
  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]  # scope to inference-profile ARNs once finalized
  }
}

resource "aws_iam_role_policy" "litellm_bedrock" {
  count  = local.irsa_enabled ? 1 : 0
  name   = "${var.name_prefix}-litellm-bedrock"
  role   = aws_iam_role.litellm_bedrock[0].id
  policy = data.aws_iam_policy_document.litellm_bedrock[0].json
}
```

- [ ] **Step 3: Output (`terraform/outputs.tf`)** — append:
```hcl
output "litellm_bedrock_role_arn" {
  value = local.irsa_enabled ? aws_iam_role.litellm_bedrock[0].arn : ""
}
```

- [ ] **Step 4: Verify (inspection — terraform unavailable)**
Check HCL syntax, `count`/`local.irsa_enabled` gating, references resolve, variables declared, output guarded. README note: set `eks_oidc_provider_arn`/`url` for EKS; leave empty for the EC2 PoC.

- [ ] **Step 5: Commit**
```bash
git add terraform/irsa.tf terraform/variables.tf terraform/outputs.tf
git commit -m "feat(infra): optional IRSA role for LiteLLM Bedrock access on EKS"
```

---

## Task 3: Bedrock setup guide + runbook + spec note

**Files:** Create `docs/AWS_BEDROCK_SETUP.md`; modify `docs/AWS_MVP_RUNBOOK.md`, the migration spec.

- [ ] **Step 1: Create `docs/AWS_BEDROCK_SETUP.md`** covering:
  - **Credential modes**: (a) EC2/K3s → node instance profile (PR #100 `datapond-app-profile`, no config); (b) EKS → IRSA: `terraform apply -var eks_oidc_provider_arn=... -var eks_oidc_provider_url=...`, then set Helm `--set litellm.serviceAccount.roleArn=<terraform output litellm_bedrock_role_arn>`; (c) portable → `litellm.aws.staticCredentials=true` + add `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` to `datapond-secrets`.
  - **Model configuration**: `litellm.config.model_list` (embed=`bedrock/amazon.titan-embed-text-v2:0`, default/chat = Claude on Bedrock) with `aws_region_name`; backend env `AI_EMBED_MODEL=embed`, `AI_EMBED_DIM=1024`, `LITELLM_MODEL=default`.
  - **Region & inference profiles**: us-east-1 uses `bedrock/us.anthropic.claude-*` cross-region profiles; ap-northeast-2 (Seoul) uses `bedrock/apac.anthropic.claude-*`; Titan embed v2 available in both. Bedrock **model access must be enabled in the console** per region (Claude + Titan Embed).
  - **Runtime configuration** (preferred): Settings → AI → add a Bedrock backend (provider `bedrock`, model id, `aws_region_name`; leave keys blank to use IRSA/instance role) — handled by `ai_backends.py` `_build_params`.
  - **Optional**: rerank (`AI_RERANK_MODEL=bedrock/amazon.rerank-v1:0`), Bedrock Guardrails.
  - **Verify**: a `curl` to `/api/ai/rag` (or check LiteLLM `/health`) returns has_ai=true with no 403/credential error.

- [ ] **Step 2: Add a "Bedrock credentials" subsection to `docs/AWS_MVP_RUNBOOK.md`** pointing to AWS_BEDROCK_SETUP.md and noting the per-deploy mode (instance profile on the PoC; IRSA on EKS).

- [ ] **Step 3: Spec note** — in the migration spec §1b Stage 3 line, mark "AWS IRSA (LiteLLM → Bedrock)" as done; remaining Stage 3 = lakehouse-service IRSA, coredns removal, image pinning, MinIO distributed.

- [ ] **Step 4: Commit**
```bash
git add docs/AWS_BEDROCK_SETUP.md docs/AWS_MVP_RUNBOOK.md docs/superpowers/specs/2026-06-30-seaweedfs-to-minio-storage-migration-design.md
git commit -m "docs: AWS Bedrock setup guide (IRSA / static keys / instance profile) + runbook"
```

---

## Task 4: CI render verification + PR

- [ ] **Step 1: Push branch + open PR** so CI `Helm chart lint` renders every profile (the SA template + deployment changes must render with roleArn empty AND set, staticCredentials false AND true). Authoritative gate.
- [ ] **Step 2: If CI render fails**, read the failing profile/line, fix, re-push. Do not complete until all three checks green.

---

## Self-Review

**Spec coverage:** LiteLLM Bedrock credential delivery via IRSA (T1 SA + T2 terraform role), static-key fallback (T1), instance-profile path preserved (no-op default); vLLM/Ollama confirmed off (T1 explicit in aws); Bedrock config documented (T3); CI verify (T4). The "configure Bedrock in LiteLLM" need is met by the existing model_list + runtime Settings path, now with working credentials + a guide.

**Placeholder scan:** Helm/HCL/doc content is complete; `roleArn:""`/empty OIDC vars are intentional defaults (feature off), not gaps. The `resources=["*"]` Bedrock policy matches the PR #100 convention with the same "scope later" note.

**Consistency:** SA name `litellm` is used by the SA template (T1), the deployment `serviceAccountName` (T1), and the Terraform trust condition `system:serviceaccount:<ns>:litellm` (T2 default `litellm_sa_name`). The Terraform output `litellm_bedrock_role_arn` feeds Helm `litellm.serviceAccount.roleArn` (documented in T3). Static-key secret keys `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are consistent between the deployment env (T1) and the runbook instruction (T3).
