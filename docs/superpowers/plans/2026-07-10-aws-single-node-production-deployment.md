# AWS Single-Node K3s Production Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Terraform, Helm, CI, and cloud-init artifacts that turn DataPond's validated single-node K3s topology into a repeatable production deployment (ECR images, Elastic IP, Route53 domain + cert-manager TLS).

**Spec:** `docs/superpowers/specs/2026-07-10-aws-single-node-production-deployment-design.md`

**Architecture:** Extend the existing `terraform/` (Aurora/S3/IAM/Secrets already there) with ECR repos, an EC2 node + Elastic IP + cloud-init, Route53, and expanded IAM (ECR pull + Route53 DNS-01 + SSM). Add a `values-prod-single.yaml` Helm profile (foundation + ECR images + real-domain TLS + external Aurora), cert-manager/ClusterIssuer manifests, an ECR pull-secret refresh timer, and a CI job that builds+pushes images to ECR. All 8 bring-up bugs are already fixed on `main`.

**Tech Stack:** Terraform (AWS provider ~>5.0, >=1.10), Helm, K3s, cert-manager, GitHub Actions, bash/cloud-init.

## Global Constraints

- **This plan produces + validates ARTIFACTS, not a live deploy.** Verification per task = `terraform fmt -check`/`validate` (real terraform 1.10.5), `helm lint`/`template`, `shellcheck`, `python -c yaml.safe_load`. The live `terraform apply` + E2E is a separate deploy-time step (needs the customer domain + Bedrock model access).
- Terraform tree stays `fmt`-clean + `validate`-green (CI `terraform-validate` gates both `terraform/` and `terraform/bootstrap/`). Do NOT commit `.terraform/`.
- Single-node K3s, NOT EKS. Node auth = the `iam.tf` instance profile (extend it; do NOT use IRSA — that's EKS-only, stays dormant).
- Image tags stay chart-appVersion-pinned (P0-4); only the `repository` changes to ECR URIs.
- SSM policy folds into `iam.tf` (the bring-up attached it out-of-band — don't repeat that).
- Naming: `${var.name_prefix}` = `datapond`. ECR repos `datapond-backend`, `datapond-frontend`. Region `var.aws_region` default us-east-1.
- New required deploy-time vars have NO insecure defaults: `domain`, `route53_zone_id` (empty default + documented). `allowed_cidrs` default `["0.0.0.0/0"]`.

---

### Task 1: Terraform IAM — ECR pull + Route53 DNS-01 + SSM on the app role

**Files:**
- Modify: `terraform/iam.tf` (append statements to `data.aws_iam_policy_document.app` + attach SSM managed policy)
- Modify: `terraform/variables.tf` (append `route53_zone_id`)

**Interfaces:**
- Consumes: existing `aws_iam_role.app`, `aws_s3_bucket.data`.
- Produces: the node instance profile now grants ECR-pull, Route53-DNS-01, SSM — consumed by Task 3 (EC2) + Task 5 (cert-manager/ECR refresh).

- [ ] **Step 1: variables.tf — append**

```hcl
variable "route53_zone_id" {
  type    = string
  default = "" # Hosted zone ID for var.domain; required at deploy time for DNS-01 + the A record.
}
```

- [ ] **Step 2: iam.tf — add ECR + Route53 statements to `data.aws_iam_policy_document.app`** (inside the existing `data` block, after the BedrockInvoke statement):

```hcl
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken is account-wide, cannot be resource-scoped
  }
  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [
      aws_ecr_repository.backend.arn,
      aws_ecr_repository.frontend.arn,
    ]
  }
  statement {
    sid       = "Route53DNS01"
    actions   = ["route53:GetChange"]
    resources = ["arn:aws:route53:::change/*"]
  }
  statement {
    sid       = "Route53Records"
    actions   = ["route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/${var.route53_zone_id}"]
  }
```

- [ ] **Step 3: iam.tf — attach the SSM managed policy** (append, so admin is SSM-only + no out-of-band attach):

```hcl
resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
```

- [ ] **Step 4: Verify + commit** (real terraform — the ECR refs resolve after Task 2, so this task's `validate` will be run again at the end of Task 2; for now `fmt` + parse):

```bash
cd /tmp && curl -fsSL -o tf.zip "https://releases.hashicorp.com/terraform/1.10.5/terraform_1.10.5_$(uname -s|tr A-Z a-z)_$(uname -m|sed 's/x86_64/amd64/;s/aarch64/arm64/').zip" && unzip -oq tf.zip && export PATH=/tmp:$PATH
cd /Users/luke/datapond && terraform -chdir=terraform fmt -check -recursive
git add terraform/iam.tf terraform/variables.tf
git commit -m "feat(tf): node role gains ECR-pull, Route53 DNS-01, and SSM (single-node prod)"
```
Note: `validate` will FAIL until Task 2 adds `aws_ecr_repository.backend/frontend`. That's expected; Task 2 closes it. If splitting is undesirable, do Task 1+2 as one commit.

---

### Task 2: Terraform ECR repositories

**Files:**
- Create: `terraform/ecr.tf`
- Modify: `terraform/outputs.tf` (append repo URL outputs)

**Interfaces:**
- Produces: `aws_ecr_repository.backend`, `aws_ecr_repository.frontend` (+ `.repository_url`, `.arn`) — consumed by Task 1 (IAM ARNs), Task 6 (values image repos), Task 7 (CI push target).

- [ ] **Step 1: create `terraform/ecr.tf`**

```hcl
# Private ECR repos for the datapond app images (built + pushed by CI, pulled by the node).
locals {
  ecr_repos = toset(["backend", "frontend"])
}

resource "aws_ecr_repository" "backend" {
  name                 = "${var.name_prefix}-backend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${var.name_prefix}-frontend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

# Keep the last 15 images per repo; expire older to control storage cost.
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy     = local.ecr_lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name
  policy     = local.ecr_lifecycle_policy
}

locals {
  ecr_lifecycle_policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 15 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 15 }
      action       = { type = "expire" }
    }]
  })
}
```

- [ ] **Step 2: outputs.tf — append**

```hcl
output "ecr_backend_repo_url"  { value = aws_ecr_repository.backend.repository_url }
output "ecr_frontend_repo_url" { value = aws_ecr_repository.frontend.repository_url }
```

- [ ] **Step 3: Verify + commit** (now the whole tree validates, incl. Task 1's ECR ARN refs):

```bash
export PATH=/tmp:$PATH
cd /Users/luke/datapond
terraform -chdir=terraform fmt -check -recursive          # exit 0
rm -rf terraform/.terraform && terraform -chdir=terraform init -backend=false -input=false >/dev/null && terraform -chdir=terraform validate   # Success
git status --short   # only ecr.tf + outputs.tf (+ Task1 files if not yet committed); NO .terraform/
git add terraform/ecr.tf terraform/outputs.tf
git commit -m "feat(tf): private ECR repos (immutable, scan-on-push, keep-last-15)"
```
Expected: `Success! The configuration is valid.`

---

### Task 3: Terraform EC2 node + Elastic IP + cloud-init + SG

**Files:**
- Create: `terraform/ec2.tf`
- Create: `terraform/templates/user-data.sh.tftpl`
- Modify: `terraform/variables.tf` (append node/network vars)
- Modify: `terraform/outputs.tf` (append node/eip outputs)

**Interfaces:**
- Consumes: `aws_iam_instance_profile.app` (Task 1), `aws_ecr_repository.*` (Task 2), `aws_rds_cluster.aurora`, `aws_s3_bucket.data`.
- Produces: `aws_eip.node.public_ip`, `aws_instance.node.id` — consumed by Task 4 (A record).

- [ ] **Step 1: variables.tf — append**

```hcl
variable "instance_type" {
  type    = string
  default = "m6i.xlarge" # 4 vCPU / 16 GB — headroom over the t3.xlarge that ran foundation
}
variable "vpc_id" {
  type = string
  # Existing VPC to place the node in. Default "" ⇒ the account default VPC (data lookup below).
  default = ""
}
variable "subnet_id" {
  type    = string
  default = "" # Public subnet for the node. Default "" ⇒ first default-VPC subnet (data lookup).
}
variable "domain" {
  type    = string
  default = "" # e.g. datapond.example.com — the app hostname. Required at deploy time.
}
variable "allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"] # Restrict to a customer CIDR in production if desired.
}
variable "acme_email" {
  type    = string
  default = "" # Let's Encrypt account email (cert-manager ClusterIssuer). Required at deploy time.
}
```

- [ ] **Step 2: create `terraform/ec2.tf`**

```hcl
# Single-node K3s production host. Availability = P0-5 backup/restore, not HA (by design).
data "aws_vpc" "selected" {
  id      = var.vpc_id != "" ? var.vpc_id : null
  default = var.vpc_id == "" ? true : null
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }
}

# Ubuntu 24.04 LTS amd64 (Canonical SSM public parameter — always current).
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "aws_security_group" "node" {
  name        = "${var.name_prefix}-node"
  description = "DataPond single-node K3s: 443/80 in, SSM-only admin (no 22)"
  vpc_id      = data.aws_vpc.selected.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }
  ingress {
    description = "HTTP (Traefik 301 -> 443 + ACME HTTP-01 fallback)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "node" {
  ami                    = data.aws_ssm_parameter.ubuntu.value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id != "" ? var.subnet_id : data.aws_subnets.public.ids[0]
  vpc_security_group_ids = [aws_security_group.node.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  root_block_device {
    volume_size           = 60
    volume_type           = "gp3"
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user-data.sh.tftpl", {
    aws_region     = var.aws_region
    domain         = var.domain
    acme_email     = var.acme_email
    ecr_registry   = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    backend_repo   = aws_ecr_repository.backend.repository_url
    frontend_repo  = aws_ecr_repository.frontend.repository_url
    aurora_host    = aws_rds_cluster.aurora.endpoint
    bucket_name    = aws_s3_bucket.data.bucket
    app_version    = var.app_version
  })

  tags = { Name = "${var.name_prefix}-k3s", managed-by = "terraform" }
}

resource "aws_eip" "node" {
  instance = aws_instance.node.id
  domain   = "vpc"
  tags     = { Name = "${var.name_prefix}-eip" }
}
```
(Add `data "aws_caller_identity" "current" {}` — check it isn't already declared elsewhere in the tree via `grep -rn 'aws_caller_identity' terraform/`; irsa.tf may not have it. If absent, add to ec2.tf; if present, reuse.)

- [ ] **Step 3: variables.tf — append `app_version`** (the image tag CI pushes; keep in sync with Chart.yaml appVersion):

```hcl
variable "app_version" {
  type    = string
  default = "2.3.0" # image tag pushed to ECR by CI; matches helm Chart.yaml appVersion
}
```

- [ ] **Step 4: create `terraform/templates/user-data.sh.tftpl`** (cloud-init; installs K3s + Helm + cert-manager + ECR-refresh timer + Helm-installs foundation from ECR). Full content:

```bash
#!/bin/bash
set -euxo pipefail
exec > /var/log/datapond-bootstrap.log 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get install -y curl jq unzip

# AWS CLI v2 (for ECR login + secret ops)
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
cd /tmp && unzip -q awscliv2.zip && ./aws/install && cd /

# K3s single-node
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--write-kubeconfig-mode 644" sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
until kubectl get nodes | grep -q ' Ready'; do sleep 3; done

# Helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# ECR pull-secret refresh (tokens expire 12h → refresh every 10h via systemd timer)
cat > /usr/local/bin/ecr-refresh.sh <<'EOS'
#!/bin/bash
set -e
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
REG="${ecr_registry}"
TOKEN=$(/usr/local/bin/aws ecr get-login-password --region ${aws_region})
kubectl -n datapond create secret docker-registry regcred \
  --docker-server="$REG" --docker-username=AWS --docker-password="$TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
EOS
chmod +x /usr/local/bin/ecr-refresh.sh
cat > /etc/systemd/system/ecr-refresh.service <<'EOS'
[Unit]
Description=Refresh datapond ECR pull secret
[Service]
Type=oneshot
ExecStart=/usr/local/bin/ecr-refresh.sh
EOS
cat > /etc/systemd/system/ecr-refresh.timer <<'EOS'
[Unit]
Description=Refresh ECR pull secret every 10h
[Timer]
OnBootSec=60
OnUnitActiveSec=10h
[Install]
WantedBy=timers.target
EOS
kubectl create namespace datapond --dry-run=client -o yaml | kubectl apply -f -
/usr/local/bin/ecr-refresh.sh
systemctl enable --now ecr-refresh.timer

# cert-manager (for Let's Encrypt DNS-01 via Route53)
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --set crds.enabled=true --wait
kubectl apply -f - <<EOS
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: ${acme_email}
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef: { name: letsencrypt-prod-key }
    solvers:
    - dns01:
        route53:
          region: ${aws_region}
EOS

# Note: app install (helm upgrade --install datapond ... from ECR) is done by the operator
# post-boot OR by a follow-up provisioning step that injects ADMIN_PASSWORD/ENCRYPTION_KEY
# from the Secrets Manager vault (see DISASTER_RECOVERY.md re-seed ordering). Cloud-init leaves
# the cluster ready with cert-manager + regcred; the helm install is a deliberate manual gate
# so secrets are seeded from the vault BEFORE the app touches Aurora.
echo "datapond-bootstrap-complete" > /opt/datapond-ready
```
(The template uses `${...}` for Terraform interpolation; the shell heredocs use `'EOS'` quoting to keep `$TOKEN`/`$REG` as runtime shell vars — verify no Terraform-var/shell-var collision. `aws_region`, `ecr_registry`, `acme_email`, `domain`, `backend_repo`, `frontend_repo`, `aurora_host`, `bucket_name`, `app_version` are Terraform-injected.)

- [ ] **Step 5: outputs.tf — append**

```hcl
output "node_public_ip" { value = aws_eip.node.public_ip }
output "node_instance_id" { value = aws_instance.node.id }
```

- [ ] **Step 6: Verify + commit**

```bash
export PATH=/tmp:$PATH
shellcheck -s bash terraform/templates/user-data.sh.tftpl || true   # tftpl isn't pure bash (has ${tf} interp); eyeball shell heredoc quoting
cd /Users/luke/datapond
terraform -chdir=terraform fmt -check -recursive
rm -rf terraform/.terraform && terraform -chdir=terraform init -backend=false -input=false >/dev/null && terraform -chdir=terraform validate
git add terraform/ec2.tf terraform/templates/user-data.sh.tftpl terraform/variables.tf terraform/outputs.tf
git commit -m "feat(tf): single-node EC2 (m6i.xlarge) + Elastic IP + cloud-init (K3s/cert-manager/ECR refresh)"
```
Expected: `Success! The configuration is valid.`

---

### Task 4: Terraform Route53 A record

**Files:**
- Create: `terraform/route53.tf`

- [ ] **Step 1: create `terraform/route53.tf`**

```hcl
# A record for the app hostname → the node's Elastic IP. Created only when a zone+domain
# are supplied (deploy time); empty ⇒ skipped so plan/validate work without them.
resource "aws_route53_record" "app" {
  count   = var.route53_zone_id != "" && var.domain != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.node.public_ip]
}
```

- [ ] **Step 2: Verify + commit**

```bash
export PATH=/tmp:$PATH
cd /Users/luke/datapond
terraform -chdir=terraform fmt -check -recursive
rm -rf terraform/.terraform && terraform -chdir=terraform init -backend=false -input=false >/dev/null && terraform -chdir=terraform validate
git add terraform/route53.tf
git commit -m "feat(tf): Route53 A record for the app hostname (count-gated on zone+domain)"
```

---

### Task 5: Helm `values-prod-single.yaml` profile

**Files:**
- Create: `helm/datapond/values-prod-single.yaml`
- Modify: `helm/datapond/templates/backend-deployment.yaml`, `helm/datapond/templates/frontend-deployment.yaml` (add `imagePullSecrets` — VERIFIED absent from the chart today; required for ECR pull)
- Modify: `helm/datapond/values.yaml` (add `imagePullSecrets` default `[]`)

**Interfaces:**
- Consumes: ECR repo URLs (Task 2), the domain (Task 3). At deploy time these are `--set` from `terraform output`.

- [ ] **Step 1a: add `imagePullSecrets` to the pod specs** (the chart has none; ECR pull needs it). In `backend-deployment.yaml` and `frontend-deployment.yaml`, add as the FIRST line under the pod-template `spec:` (line 22, sibling to `containers:`/`serviceAccountName:`):

```yaml
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```
And in `values.yaml` (top level, near `namespace:`):

```yaml
# Pull secrets for private registries (e.g. ECR regcred on single-node prod). Empty on
# profiles that use public images.
imagePullSecrets: []
```
The prod-single values (Step 1b) set `imagePullSecrets: [{name: regcred}]` (the secret the cloud-init ECR-refresh timer maintains). Un-set on every other profile → no change to public-image deploys.

- [ ] **Step 1b: create `helm/datapond/values-prod-single.yaml`** (foundation + ECR + real-domain TLS + external Aurora; extends the foundation scope):

```yaml
# Single-node K3s PRODUCTION profile. Foundation workloads + ECR images + real-domain TLS +
# external Aurora/S3/Bedrock. Set ecr repo URLs + domain + externalDatabase.host at deploy
# time from `terraform output` (they are account/deploy specific).
namespace: datapond

# Pull the ECR images via the regcred secret the cloud-init ecr-refresh timer maintains.
imagePullSecrets:
  - name: regcred

global:
  externalScheme: https

# --- Storage: native AWS S3 via the node instance profile (no static keys) ---
storage:
  provider: s3
  endpoint: ""
  region: us-east-1

# --- Postgres: external Aurora (not in-cluster) ---
postgres:
  enabled: false
externalDatabase:
  enabled: true
  host: ""          # deploy time: terraform output -raw aurora_endpoint
  port: 5432
  name: datapond
  sslmode: require

# --- Images from ECR (repository set at deploy time; tag = chart appVersion via default) ---
backend:
  enabled: true
  serviceAccountName: datapond-backend
  image:
    repository: ""  # deploy time: terraform output -raw ecr_backend_repo_url
    pullPolicy: IfNotPresent
frontend:
  enabled: true
  image:
    repository: ""  # deploy time: terraform output -raw ecr_frontend_repo_url
    pullPolicy: IfNotPresent
valkey:
  enabled: true

litellm:
  enabled: true
  config:
    model_list:
      - model_name: "embed"
        litellm_params: { model: "bedrock/amazon.titan-embed-text-v2:0", aws_region_name: "us-east-1" }
      - model_name: "default"
        litellm_params: { model: "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0", aws_region_name: "us-east-1" }
      - model_name: "chat"
        litellm_params: { model: "bedrock/us.anthropic.claude-sonnet-4-6", aws_region_name: "us-east-1" }
  serviceAccount:
    roleArn: ""     # K3s: empty (node instance profile). Not EKS/IRSA.

# --- Heavy analytics: AWS-managed (Athena/EMR), not on the node ---
trino: { enabled: false }
spark: { enabled: false }
polaris: { enabled: false }
airflow: { enabled: false }
mlflow: { enabled: false }
jupyter: { enabled: false }
risingwave: { enabled: false }
openmetadata: { enabled: false }
ollama: { enabled: false }
vllm: { enabled: false }
minio: { enabled: false }

# --- Ingress: real domain + cert-manager Let's Encrypt TLS ---
ingress:
  enabled: true
  className: traefik
  domain: ""        # deploy time: var.domain (e.g. datapond.example.com)
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  tls:
    enabled: true
    secretName: datapond-tls
```

- [ ] **Step 2: Verify** (helm render with the deploy-time `--set`s that a real install supplies):

```bash
cd /Users/luke/datapond
helm lint helm/datapond --values helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=x --set backend.image.repository=r --set frontend.image.repository=r --set ingress.domain=d.example.com
# assert: backend+frontend+valkey+litellm render; postgres does NOT; ingress has the cert-manager annotation + tls
d=$(helm template datapond helm/datapond --values helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=aurora.x --set backend.image.repository=1.dkr.ecr.us-east-1.amazonaws.com/datapond-backend \
  --set frontend.image.repository=1.dkr.ecr.us-east-1.amazonaws.com/datapond-frontend --set ingress.domain=datapond.example.com)
grep -q 'cert-manager.io/cluster-issuer: letsencrypt-prod' <<<"$d" || { echo FAIL annotation; exit 1; }
grep -q 'host: datapond.example.com' <<<"$d" || { echo FAIL host; exit 1; }
grep -q 'datapond-backend' <<<"$d" || { echo FAIL image; exit 1; }
grep -qE 'kind: Deployment' <<<"$d" && ! grep -q 'name: postgres' <<<"$d" && echo "OK render"
```

- [ ] **Step 3: Commit**

```bash
git add helm/datapond/values-prod-single.yaml
git commit -m "feat(helm): values-prod-single profile (foundation + ECR + real-domain TLS + Aurora)"
```

---

### Task 6: CI — build + push images to ECR on release

**Files:**
- Create: `.github/workflows/ecr-push.yml`

**Interfaces:**
- Consumes: ECR repos (Task 2). Authenticates to AWS via OIDC (no long-lived keys) or repo secrets.

- [ ] **Step 1: create `.github/workflows/ecr-push.yml`**

```yaml
name: Build + push images to ECR
on:
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      tag:
        description: "Image tag (defaults to chart appVersion)"
        required: false

permissions:
  id-token: write   # OIDC to assume the AWS role
  contents: read

env:
  AWS_REGION: us-east-1

jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Resolve tag
        id: tag
        run: |
          TAG="${{ github.event.inputs.tag }}"
          [ -z "$TAG" ] && TAG=$(grep '^appVersion:' helm/datapond/Chart.yaml | awk '{print $2}' | tr -d '"')
          echo "tag=$TAG" >> "$GITHUB_OUTPUT"
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.ECR_PUSH_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr
      - name: Build + push backend (enterprise, repo-root context)
        run: |
          REG=${{ steps.ecr.outputs.registry }}
          docker build -f backend/Dockerfile --target enterprise -t $REG/datapond-backend:${{ steps.tag.outputs.tag }} .
          docker push $REG/datapond-backend:${{ steps.tag.outputs.tag }}
      - name: Build + push frontend
        run: |
          REG=${{ steps.ecr.outputs.registry }}
          docker build -f frontend/Dockerfile -t $REG/datapond-frontend:${{ steps.tag.outputs.tag }} frontend/
          docker push $REG/datapond-frontend:${{ steps.tag.outputs.tag }}
```

- [ ] **Step 2: Verify YAML + logic**

```bash
python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/ecr-push.yml')); assert 'push' in d['jobs']; print('CI YAML OK')"
```
(Note the two documented prerequisites for the operator: an ECR-push IAM role with an OIDC trust for this repo, stored as `secrets.ECR_PUSH_ROLE_ARN`; and the backend build uses `--target enterprise` from repo-root context per P0-3/P0-4.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ecr-push.yml
git commit -m "ci: build + push backend/frontend to ECR on release (OIDC, enterprise target)"
```

---

### Task 7: Deploy runbook + README + final review

**Files:**
- Create: `docs/DEPLOY_SINGLE_NODE.md`
- Modify: `terraform/README.md` (add the single-node prod apply flow)

- [ ] **Step 1: create `docs/DEPLOY_SINGLE_NODE.md`** — the end-to-end operator runbook. Sections (write full prose + commands):
  1. **Prereqs**: a Route53 hosted zone + domain; Bedrock model access enabled (console) for Titan + Claude Haiku/Sonnet; the ECR-push OIDC role + `ECR_PUSH_ROLE_ARN` secret; the bootstrap state bucket (from `terraform/bootstrap`).
  2. **Build images**: cut a GitHub Release (or `workflow_dispatch`) → `ecr-push.yml` pushes `datapond-{backend,frontend}:<appVersion>` to ECR.
  3. **Apply infra**: `terraform init -backend-config=...` (account-scoped state bucket per #114); `terraform apply -var domain=datapond.example.com -var route53_zone_id=Z... -var acme_email=ops@example.com -var db_master_password=...` (or `manage_master_user_password` follow-up). Creates ECR/Aurora/S3/IAM/EC2/EIP/Route53/secrets.
  4. **Seed the critical-secrets vault** (DR §26 procedure) BEFORE the app runs.
  5. **Install the app**: SSM onto the node (or a provisioning step) → `helm upgrade --install datapond helm/datapond --values values-prod-single.yaml --set externalDatabase.host=$(tf output aurora_endpoint) --set backend.image.repository=$(tf output ecr_backend_repo_url) --set frontend.image.repository=$(tf output ecr_frontend_repo_url) --set ingress.domain=$DOMAIN` + inject `ADMIN_PASSWORD`/`ENCRYPTION_KEY`/etc. from the vault.
  6. **Verify**: `https://datapond.example.com/` (frontend), `/api/health` 200, login 200+JWT, litellm→Bedrock, cert-manager cert Ready.
  7. **DR**: point to `DISASTER_RECOVERY.md`; single-node availability = restore, secrets-first ordering.
  8. **Teardown**: `-var db_deletion_protection=false` apply, then `terraform destroy`; delete out-of-band nothing (all in TF now).

- [ ] **Step 2: terraform/README.md — add a "Single-node production" section** pointing to `docs/DEPLOY_SINGLE_NODE.md` + the new vars (`domain`, `route53_zone_id`, `acme_email`, `instance_type`, `allowed_cidrs`, `app_version`).

- [ ] **Step 3: Verify + commit**

```bash
python3 -c "print(open('docs/DEPLOY_SINGLE_NODE.md').read().count('##'), 'sections')"   # >=8
git add docs/DEPLOY_SINGLE_NODE.md terraform/README.md
git commit -m "docs: single-node production deploy runbook + terraform README"
```

- [ ] **Step 4: PR + CI (terraform-validate + helm-lint gate the new artifacts) + final whole-branch review.**

---

## Self-Review

**Spec coverage:** §1 decisions → all tasks; §2 compute/EIP → Task 3; §3 ECR → Task 2 + Task 6 (CI) + Task 3 (refresh timer) + Task 1 (pull IAM); §4 TLS/domain → Task 3 (cert-manager in cloud-init) + Task 4 (A record) + Task 5 (ingress) + Task 1 (Route53 IAM); §5 data/AI → already on main (Aurora/S3/secrets exist) + Task 5 (litellm/externalDB values); §6 backups → already merged (P0-5), referenced in Task 7 runbook; §7 deploy automation → Task 3 (cloud-init) + Task 5 (values) + Task 7 (runbook); §8 out-of-scope honored (no EKS/IRSA/OpenSearch); §9 open items → Task 7 prereqs + count-gated Route53 (Task 4) + vars with empty defaults (Task 3).

**Placeholder scan:** the empty-string var defaults (`domain`, `route53_zone_id`, `acme_email`, image repos) are documented deploy-time inputs, not placeholders — each has a comment naming its `terraform output`/deploy source. All HCL/YAML/bash is literal + complete. No TBDs.

**Consistency:** ECR repo names `datapond-backend`/`datapond-frontend` identical across Task 2 (resource), Task 1 (ARN refs), Task 3 (cloud-init `backend_repo`), Task 5 (image repository), Task 6 (CI push target). `letsencrypt-prod` ClusterIssuer name matches between Task 3 (cloud-init creates it) and Task 5 (ingress annotation references it). `regcred` secret + `imagePullSecrets`: Task 3 creates `regcred` in `datapond` ns — the deployments must reference it via `imagePullSecrets` (CHECK the chart already sets `imagePullSecrets` or add it in Task 5 values; if the chart has no imagePullSecrets support, Task 5 must add a `global.imagePullSecrets` or the pods can't pull from ECR — verify during Task 5 and extend the chart if needed). `app_version` (Task 3) = Chart.yaml appVersion = CI tag (Task 6) = helm image tag default (P0-4).

**Gap flagged for the implementer:** the chart's deployments may not currently reference an `imagePullSecrets`. ECR pull REQUIRES it (the node isn't logged into ECR globally). Task 5 must confirm `helm/datapond/templates/*-deployment.yaml` honor an `imagePullSecrets` value (grep); if not, add `imagePullSecrets: [{name: regcred}]` to the backend+frontend pod specs gated on a value, as part of Task 5. This is the one spot where a chart-template change (not just values) may be required.
