# AWS MVP: Bedrock RAG on Real S3 + Aurora pgvector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up DataPond's existing RAG pipeline on AWS-native managed services — real Amazon S3 for source data, Aurora PostgreSQL Serverless v2 for pgvector, and Amazon Bedrock for embeddings + generation — and validate an end-to-end RAG query.

**Architecture:** The application is already Bedrock-ready (LiteLLM gateway with a `bedrock` provider, `values-aws.yaml` seeds Bedrock Claude, pgvector store unchanged). The work is therefore: (1) two small code changes to support native AWS S3 and TLS-secured Aurora; (2) Helm config wiring (Aurora host, native S3, Bedrock embedding model); (3) Terraform for S3 + IAM + Aurora; (4) an end-to-end validation runbook. No RAG-pipeline rewrite.

**Tech Stack:** Python 3.9 / FastAPI / asyncpg / boto3, PostgreSQL+pgvector (Aurora Serverless v2), Amazon Bedrock (Titan Embed v2 + Claude), LiteLLM gateway, Helm, Terraform, pytest.

## Global Constraints

- Python backend lives in `/Users/luke/datapond/backend`; run tests with `cd backend && python -m pytest tests/ -v`.
- Dependency floors (do not bump): `fastapi==0.109.0`, `asyncpg==0.29.0`, `boto3==1.34.0`.
- No new pip dependencies — boto3 default credential chain and asyncpg `ssl=` are already available.
- Keep on-prem/SeaweedFS behavior working: every change must be **additive and env-gated**, never break the existing in-cluster K3s deployment (`values.yaml`, `values-onprem.yaml`).
- pgvector store, retrieval (`_retrieve`), PII masking, and ingestion code are **unchanged** — do not touch `ai_vectors.py` RAG logic.
- Bedrock region default `us-east-1` with `us.anthropic.*` cross-region inference profiles (matches existing `values-aws.yaml`). If co-locating with the Seoul PoC (`ap-northeast-2`), swap to `apac.anthropic.*` profiles — noted where relevant.
- MVP keeps the existing EC2 Spot / K3s deployment; EKS migration is out of scope (separate plan).
- OpenSearch Serverless vector backend is out of scope for MVP (pgvector only).

---

## File Structure

**Modified (code):**
- `backend/app/api/storage.py` — add `_s3_config()`; native AWS S3 when `S3_ENDPOINT` empty (IAM role creds), SeaweedFS otherwise.
- `backend/app/api/connectors.py` — add `_pool_kwargs()`; TLS for Aurora via `POSTGRES_SSLMODE`.

**Created (tests):**
- `backend/tests/test_storage_config.py`
- `backend/tests/test_db_pool_config.py`

**Modified (config):**
- `helm/datapond/templates/backend-deployment.yaml` — env wiring for external DB host/SSL + native S3.
- `helm/datapond/values-aws.yaml` — Bedrock embedding model + DB SSL.

**Created (infra):**
- `terraform/main.tf`, `terraform/variables.tf`, `terraform/outputs.tf`
- `terraform/s3.tf`, `terraform/iam.tf`, `terraform/aurora.tf`
- `terraform/README.md`

**Created (docs):**
- `docs/AWS_MVP_RUNBOOK.md` — deploy + E2E validation runbook.

---

## Task 1: Native AWS S3 support in `storage.py`

**Files:**
- Modify: `backend/app/api/storage.py:17-29`
- Test: `backend/tests/test_storage_config.py`

**Interfaces:**
- Produces: `_s3_config() -> dict` — boto3 `client("s3", **kwargs)` kwargs. Native AWS (no `endpoint_url`, region from `S3_REGION`, IAM-role creds) when `S3_ENDPOINT` is empty/unset; SeaweedFS-compatible (`endpoint_url` + static keys) when `S3_ENDPOINT` is set.
- Consumed by: `get_s3_client()` (storage.py) and `ai_vectors._read_s3_docs` (via `get_s3_client`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_storage_config.py`:

```python
import importlib

def _fresh():
    import app.api.storage as s
    return importlib.reload(s)

def test_native_aws_when_endpoint_empty(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    monkeypatch.setenv("S3_REGION", "ap-northeast-2")
    cfg = _fresh()._s3_config()
    assert "endpoint_url" not in cfg          # native AWS S3
    assert cfg["region_name"] == "ap-northeast-2"
    assert "aws_access_key_id" not in cfg     # IAM role / default chain

def test_seaweedfs_when_endpoint_set(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "seaweedfs-s3:8333")
    monkeypatch.setenv("S3_ACCESS_KEY", "k")
    monkeypatch.setenv("S3_SECRET_KEY", "s")
    cfg = _fresh()._s3_config()
    assert cfg["endpoint_url"] == "http://seaweedfs-s3:8333"
    assert cfg["aws_access_key_id"] == "k"
    assert cfg["aws_secret_access_key"] == "s"

def test_endpoint_keeps_explicit_scheme(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "https://my-minio.example.com")
    cfg = _fresh()._s3_config()
    assert cfg["endpoint_url"] == "https://my-minio.example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_storage_config.py -v`
Expected: FAIL with `AttributeError: module 'app.api.storage' has no attribute '_s3_config'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/storage.py`, replace lines 17-29:

```python
S3_ENDPOINT   = os.getenv("S3_ENDPOINT", "").strip()
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "").strip()
S3_REGION     = os.getenv("S3_REGION", "us-east-1").strip() or "us-east-1"


def _s3_config() -> dict:
    """boto3 s3 client kwargs.

    Native AWS S3 when S3_ENDPOINT is empty (default credential chain / IAM
    role). SeaweedFS / S3-compatible when S3_ENDPOINT is set; bare host:port
    is assumed http unless a scheme is given.
    """
    cfg: dict = {"region_name": S3_REGION}
    if not S3_ENDPOINT:
        return cfg
    endpoint = S3_ENDPOINT
    if not endpoint.startswith(("http://", "https://")):
        endpoint = "http://" + endpoint
    cfg["endpoint_url"] = endpoint
    if S3_ACCESS_KEY and S3_SECRET_KEY:
        cfg["aws_access_key_id"] = S3_ACCESS_KEY
        cfg["aws_secret_access_key"] = S3_SECRET_KEY
    return cfg


def get_s3_client():
    return boto3.client("s3", **_s3_config())
```

(Constants now read raw env at import; `_s3_config()` re-reads via module globals on reload. For runtime correctness no caller mutates these after import.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_storage_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Regression — ensure storage module still imports and existing callers unaffected**

Run: `cd backend && python -c "import app.api.storage as s; print(s._s3_config())"`
Expected: prints `{'region_name': 'us-east-1'}` (no crash; native by default)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/storage.py backend/tests/test_storage_config.py
git commit -m "feat(s3): native AWS S3 support (IAM role) when S3_ENDPOINT empty"
```

---

## Task 2: Aurora TLS connection in `connectors.py`

**Files:**
- Modify: `backend/app/api/connectors.py:280-292`
- Test: `backend/tests/test_db_pool_config.py`

**Interfaces:**
- Produces: `_pool_kwargs() -> dict` — kwargs for `asyncpg.create_pool`. Adds `ssl=True` when `POSTGRES_SSLMODE` requests TLS (Aurora/RDS); honors `POSTGRES_PORT`.
- Consumed by: `get_db_pool()` (connectors.py).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db_pool_config.py`:

```python
import importlib

def _fresh():
    import app.api.connectors as c
    return importlib.reload(c)

def test_ssl_enabled_for_aurora(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db.cluster-x.ap-northeast-2.rds.amazonaws.com")
    monkeypatch.setenv("POSTGRES_SSLMODE", "require")
    kw = _fresh()._pool_kwargs()
    assert kw["ssl"] is True
    assert kw["host"].endswith("rds.amazonaws.com")
    assert kw["port"] == 5432

def test_no_ssl_in_cluster(monkeypatch):
    monkeypatch.delenv("POSTGRES_SSLMODE", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    kw = _fresh()._pool_kwargs()
    assert "ssl" not in kw
    assert kw["host"] == "postgres"

def test_custom_port(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    kw = _fresh()._pool_kwargs()
    assert kw["port"] == 5433
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_db_pool_config.py -v`
Expected: FAIL with `AttributeError: module 'app.api.connectors' has no attribute '_pool_kwargs'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/connectors.py`, add above `get_db_pool` (before line 280):

```python
def _pool_kwargs() -> dict:
    """asyncpg.create_pool kwargs. Enables TLS for Aurora/RDS via POSTGRES_SSLMODE."""
    kw: dict = dict(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "datapond"),
        user=os.getenv("POSTGRES_USER", "datapond"),
        password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
        min_size=2,
        max_size=10,
    )
    sslmode = os.getenv("POSTGRES_SSLMODE", "").strip().lower()
    if sslmode in ("require", "prefer", "allow", "verify-ca", "verify-full"):
        kw["ssl"] = True  # asyncpg: ssl=True ⇒ TLS required (no cert verify)
    return kw
```

Then change lines 284-292 from the inline `asyncpg.create_pool(host=..., max_size=10,)` to:

```python
        _db_pool = await asyncpg.create_pool(**_pool_kwargs())
```

(Leave the idempotent `ALTER TABLE` migration block that follows unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_db_pool_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/connectors.py backend/tests/test_db_pool_config.py
git commit -m "feat(db): TLS pool for Aurora/RDS via POSTGRES_SSLMODE"
```

> Note: `ssl=True` requires TLS without CA verification — acceptable for MVP. `verify-full` with the RDS CA bundle is a future hardening item.

---

## Task 3: Helm wiring for external DB + native S3 + Bedrock embeddings

**Files:**
- Modify: `helm/datapond/templates/backend-deployment.yaml:49-64,126-130`
- Modify: `helm/datapond/values-aws.yaml`

**Interfaces:**
- Consumes: `_s3_config()` (Task 1) reads `S3_ENDPOINT`/`S3_REGION`; `_pool_kwargs()` (Task 2) reads `POSTGRES_HOST`/`POSTGRES_SSLMODE`.
- Produces: rendered backend env exporting `POSTGRES_HOST`, `POSTGRES_SSLMODE`, empty `S3_ENDPOINT`, `S3_REGION`, and `AI_EMBED_MODEL=embed` mapped to a Bedrock Titan model.

- [ ] **Step 1: Wire external DB host + SSL + native S3 in `backend-deployment.yaml`**

Replace the `DATABASE_URL` env (lines 49-50) and `S3_*` block (lines 53-64) with:

```yaml
        - name: POSTGRES_HOST
          value: "{{ if .Values.externalDatabase.enabled }}{{ .Values.externalDatabase.host }}{{ else }}postgres{{ end }}"
        - name: POSTGRES_PORT
          value: "{{ if .Values.externalDatabase.enabled }}{{ .Values.externalDatabase.port | default 5432 }}{{ else }}5432{{ end }}"
        {{- if .Values.externalDatabase.enabled }}
        - name: POSTGRES_SSLMODE
          value: "{{ .Values.externalDatabase.sslmode | default "require" }}"
        {{- end }}
        - name: DATABASE_URL
          value: "postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)"
        - name: REDIS_URL
          value: "redis://redis:6379"
        - name: S3_ENDPOINT
          value: "{{ .Values.storage.endpoint | default "" }}"
        - name: S3_REGION
          value: "{{ .Values.storage.region | default "us-east-1" }}"
        {{- if .Values.storage.endpoint }}
        - name: S3_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: SEAWEEDFS_S3_USER
        - name: S3_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: SEAWEEDFS_S3_PASSWORD
        {{- end }}
```

(`POSTGRES_USER/PASSWORD/DB` secret env above stays; for Aurora those secret values hold Aurora creds. When `storage.endpoint` is empty, S3 keys are omitted so boto3 uses the instance IAM role.)

- [ ] **Step 2: Add Bedrock embedding model + DB SSL to `values-aws.yaml`**

In `helm/datapond/values-aws.yaml`, add an `embed` entry to `litellm.config.model_list` and set `ai`/`externalDatabase`:

```yaml
ai:
  egressPolicy: "cloud-allowed"
  embedModel: "embed"
  embedDim: 1024

litellm:
  enabled: true
  config:
    model_list:
      - model_name: "embed"
        litellm_params:
          model: "bedrock/amazon.titan-embed-text-v2:0"
          aws_region_name: "us-east-1"
      - model_name: "default"
        litellm_params:
          model: "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"
          aws_region_name: "us-east-1"
      - model_name: "chat"
        litellm_params:
          model: "bedrock/us.anthropic.claude-sonnet-4-6"
          aws_region_name: "us-east-1"

externalDatabase:
  enabled: true
  host: ""          # set at deploy time to the Aurora writer endpoint
  port: 5432
  name: datapond
  sslmode: "require"
```

> Seoul co-location: set all `aws_region_name` to `ap-northeast-2` and use `apac.anthropic.claude-*` inference-profile model ids; Titan Embed v2 is available in `ap-northeast-2`.

- [ ] **Step 3: Verify rendered manifests**

Run:
```bash
cd /Users/luke/datapond
helm template datapond helm/datapond -f helm/datapond/values-aws.yaml \
  --set externalDatabase.host=test-aurora.example.com 2>/dev/null \
  | grep -E 'POSTGRES_HOST|POSTGRES_SSLMODE|S3_ENDPOINT|S3_REGION|AI_EMBED_MODEL' -A1
```
Expected: `POSTGRES_HOST` value `test-aurora.example.com`; `POSTGRES_SSLMODE` `require`; `S3_ENDPOINT` empty (`value: ""`); `AI_EMBED_MODEL` `embed`.

- [ ] **Step 4: Verify S3 keys are omitted in AWS profile but present on-prem**

Run:
```bash
helm template datapond helm/datapond -f helm/datapond/values-aws.yaml --set externalDatabase.host=x 2>/dev/null | grep -c S3_ACCESS_KEY   # expect 0
helm template datapond helm/datapond -f helm/datapond/values-onprem.yaml 2>/dev/null | grep -c S3_ACCESS_KEY                          # expect >=1
```
Expected: `0` for AWS, `>=1` for on-prem.

- [ ] **Step 5: Commit**

```bash
git add helm/datapond/templates/backend-deployment.yaml helm/datapond/values-aws.yaml
git commit -m "feat(helm): wire Aurora host/SSL, native S3, Bedrock embed model in AWS profile"
```

---

## Task 4: Terraform — S3 bucket + IAM (Bedrock + S3)

**Files:**
- Create: `terraform/main.tf`, `terraform/variables.tf`, `terraform/outputs.tf`, `terraform/s3.tf`, `terraform/iam.tf`, `terraform/README.md`

**Interfaces:**
- Produces: S3 bucket (`var.bucket_name`); IAM policy granting `s3:*` on that bucket + `bedrock:InvokeModel*`; an IAM role to attach to the K3s EC2 instance (instance profile). Outputs: `bucket_name`, `bedrock_s3_instance_profile`.

- [ ] **Step 1: Create provider + variables**

`terraform/main.tf`:
```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.aws_region
}
```

`terraform/variables.tf`:
```hcl
variable "aws_region"  { type = string  default = "us-east-1" }
variable "bucket_name" { type = string  default = "datapond-iceberg" }
variable "name_prefix" { type = string  default = "datapond" }
variable "vpc_id"      { type = string }            # existing PoC VPC
variable "db_subnet_ids" { type = list(string) }    # >= 2 subnets for Aurora
variable "app_security_group_id" { type = string }  # K3s EC2 SG (DB ingress source)
variable "db_master_password" { type = string  sensitive = true }
```

- [ ] **Step 2: Create S3 bucket**

`terraform/s3.tf`:
```hcl
resource "aws_s3_bucket" "data" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

- [ ] **Step 3: Create IAM role + policy (Bedrock + S3) and instance profile**

`terraform/iam.tf`:
```hcl
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.name_prefix}-app-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "app" {
  statement {
    sid     = "S3Data"
    actions = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
  }
  statement {
    sid       = "BedrockInvoke"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]  # scope to inference-profile ARNs once finalized
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.name_prefix}-app-policy"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.name_prefix}-app-profile"
  role = aws_iam_role.app.name
}
```

- [ ] **Step 4: Outputs**

`terraform/outputs.tf`:
```hcl
output "bucket_name"                 { value = aws_s3_bucket.data.bucket }
output "bedrock_s3_instance_profile" { value = aws_iam_instance_profile.app.name }
```

- [ ] **Step 5: README with apply instructions + Bedrock model-access note**

`terraform/README.md`:
```markdown
# DataPond AWS MVP — Terraform

Provisions S3, IAM (Bedrock + S3), and Aurora pgvector for the DataPond AWS MVP.

## Apply
    terraform init
    terraform validate
    terraform plan  -var vpc_id=vpc-xxx -var 'db_subnet_ids=["subnet-a","subnet-b"]' \
                    -var app_security_group_id=sg-xxx -var db_master_password=...
    terraform apply <same vars>

## Manual prerequisite — enable Bedrock model access (one-time, per region)
In the AWS console → Bedrock → Model access, enable:
- Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0)
- Anthropic Claude (Haiku + Sonnet) — the model ids in values-aws.yaml

## After apply
- Attach output `bedrock_s3_instance_profile` to the K3s EC2 instance.
- Set Helm `externalDatabase.host` to the `aurora_endpoint` output (Task 5).
```

- [ ] **Step 6: Validate**

Run:
```bash
cd /Users/luke/datapond/terraform
terraform init -backend=false && terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 7: Commit**

```bash
git add terraform/main.tf terraform/variables.tf terraform/outputs.tf terraform/s3.tf terraform/iam.tf terraform/README.md
git commit -m "feat(infra): terraform S3 bucket + IAM role (Bedrock + S3) for AWS MVP"
```

---

## Task 5: Terraform — Aurora PostgreSQL Serverless v2 (pgvector)

**Files:**
- Create: `terraform/aurora.tf`
- Modify: `terraform/outputs.tf`

**Interfaces:**
- Consumes: `var.vpc_id`, `var.db_subnet_ids`, `var.app_security_group_id`, `var.db_master_password` (Task 4 variables).
- Produces: Aurora PostgreSQL Serverless v2 cluster (engine ≥ 15.4, pgvector-capable). Output: `aurora_endpoint`.

- [ ] **Step 1: Create Aurora cluster + serverless instance + SG**

`terraform/aurora.tf`:
```hcl
resource "aws_db_subnet_group" "aurora" {
  name       = "${var.name_prefix}-aurora"
  subnet_ids = var.db_subnet_ids
}

resource "aws_security_group" "aurora" {
  name   = "${var.name_prefix}-aurora-sg"
  vpc_id = var.vpc_id

  ingress {
    description     = "Postgres from app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_cluster" "aurora" {
  cluster_identifier     = "${var.name_prefix}-pg"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  engine_version         = "15.4"                 # pgvector available (>= 15.3)
  database_name          = "datapond"
  master_username        = "datapond"
  master_password        = var.db_master_password
  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]
  storage_encrypted      = true
  skip_final_snapshot    = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 4.0
  }
}

resource "aws_rds_cluster_instance" "aurora" {
  identifier         = "${var.name_prefix}-pg-1"
  cluster_identifier = aws_rds_cluster.aurora.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.aurora.engine
  engine_version     = aws_rds_cluster.aurora.engine_version
}
```

- [ ] **Step 2: Add Aurora endpoint output**

Append to `terraform/outputs.tf`:
```hcl
output "aurora_endpoint" { value = aws_rds_cluster.aurora.endpoint }
```

- [ ] **Step 3: Validate**

Run:
```bash
cd /Users/luke/datapond/terraform
terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add terraform/aurora.tf terraform/outputs.tf
git commit -m "feat(infra): terraform Aurora PostgreSQL Serverless v2 (pgvector) for AWS MVP"
```

> pgvector: the app's `ensure_vector_schema()` runs `CREATE EXTENSION IF NOT EXISTS vector` on startup; Aurora PostgreSQL ≥ 15.3 ships the extension, so no separate provisioning step is needed.

---

## Task 6: End-to-end validation runbook

**Files:**
- Create: `docs/AWS_MVP_RUNBOOK.md`

**Interfaces:**
- Consumes: Terraform outputs (`bucket_name`, `aurora_endpoint`, `bedrock_s3_instance_profile`), Helm AWS profile (Tasks 3-5), code changes (Tasks 1-2).

- [ ] **Step 1: Write the runbook**

Create `docs/AWS_MVP_RUNBOOK.md`:

```markdown
# AWS MVP Runbook — Bedrock RAG on S3 + Aurora pgvector

## 0. Prerequisites
- `terraform apply` complete (Tasks 4-5); Bedrock model access enabled.
- Instance profile `datapond-app-profile` attached to the K3s EC2 instance.

## 1. Seed credentials secret (Aurora) and deploy
    kubectl -n datapond create secret generic datapond-secrets \
      --from-literal=POSTGRES_USER=datapond \
      --from-literal=POSTGRES_PASSWORD=<db_master_password> \
      --from-literal=POSTGRES_DB=datapond \
      --from-literal=JWT_SECRET=<random> \
      --from-literal=INTERNAL_API_KEY=<random> \
      --dry-run=client -o yaml | kubectl apply -f -

    helm upgrade --install datapond helm/datapond -n datapond \
      -f helm/datapond/values-aws.yaml \
      --set externalDatabase.host=<aurora_endpoint> \
      --set storage.bucket=<bucket_name>

## 2. Wait for backend ready
    kubectl -n datapond rollout status deploy/backend
    kubectl -n datapond logs deploy/backend | grep -i "vector schema"   # ensure_vector_schema ran

## 3. Upload sample source docs to S3
    aws s3 cp ./samples/ s3://<bucket_name>/rag-samples/ --recursive   # *.md / *.txt

## 4. End-to-end RAG smoke test
    TOKEN=$(curl -s -X POST https://<domain>/api/auth/login \
      -d '{"username":"admin","password":"<pw>"}' -H 'Content-Type: application/json' | jq -r .access_token)

    # create collection
    curl -s -X POST https://<domain>/api/ai/collections -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' -d '{"name":"mvp","description":"aws mvp"}'

    # ingest from S3 (uses IAM role; embeds via Bedrock Titan)
    curl -s -X POST https://<domain>/api/ai/collections/mvp/ingest-source \
      -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d '{"type":"s3","bucket":"<bucket_name>","prefix":"rag-samples/","max_files":50}'
    # expect: {"success":true,"documents":N,"chunks":M,...}

    # RAG query (generation via Bedrock Claude)
    curl -s -X POST https://<domain>/api/ai/rag -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d '{"collection":"mvp","question":"<a question answerable from the docs>","k":5}'
    # expect: {"answer":"... [1] ...","citations":[...],"has_ai":true}

## 5. Pass criteria
- ingest-source returns documents > 0 and chunks > 0 (Titan embeddings succeeded).
- /api/ai/rag returns has_ai=true with non-empty citations referencing s3://<bucket> sources.
- backend logs show no 502 from embeddings and no egress-policy 403.
```

- [ ] **Step 2: Commit**

```bash
git add docs/AWS_MVP_RUNBOOK.md
git commit -m "docs(aws-mvp): end-to-end Bedrock RAG validation runbook"
```

- [ ] **Step 3: Update PRODUCT_CONCEPT/README roadmap — mark Phase 3 MVP path defined**

Edit `docs/PRODUCT_CONCEPT.md` roadmap row **3** status to `🔜 계획 완료` and add a link to this plan; same for `README.md` Phase 3 line. Commit:
```bash
git add docs/PRODUCT_CONCEPT.md README.md
git commit -m "docs: link AWS MVP implementation plan from roadmap"
```

---

## Self-Review

**Spec coverage** (against `2026-06-30-aws-ai-data-platform-pivot-design.md`):
- §2 AWS core (S3, Bedrock) → Tasks 3-6. ✅
- §3 hybrid mapping (S3 native, Bedrock embed+chat, pgvector kept) → Tasks 1,3,5. ✅
- §4 vector strategy: pgvector default → Aurora (Tasks 2,5); AOSS expansion → explicitly out of scope (Global Constraints). ✅ (deferred by design)
- §6 Phase 2 IaC/security → Terraform Tasks 4-5 (S3, IAM, Aurora SG); EKS deferred (Global Constraints). ✅
- §6 Phase 3 MVP thin slice (S3→embed→vector→Bedrock RAG) → Task 6. ✅
- §8 open items: (c) Terraform chosen ✅; (d) keep K3s for MVP ✅.

**Placeholder scan:** No "TBD/TODO"; every code step shows full code; infra steps show full HCL; runbook commands are concrete. `<angle-bracket>` tokens are deploy-time secrets/IDs by design, documented in the runbook, not plan gaps.

**Type/name consistency:** `_s3_config()` (Task 1) and `_pool_kwargs()` (Task 2) names used consistently in Task 3 wiring. Env var names align across code (`S3_ENDPOINT`/`S3_REGION`/`POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_SSLMODE`) and Helm (Task 3). `AI_EMBED_MODEL=embed` maps to the `embed` model_name added to `litellm.config.model_list` (Task 3 Step 2). Consistent. ✅
