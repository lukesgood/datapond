# AWS Bedrock Setup Guide

This guide covers credential wiring and model configuration for LiteLLM integration with AWS Bedrock (embeddings, generation, optional reranking).

## Overview

DataPond's AI layer (LiteLLM proxy) connects to Bedrock for:
- **Embeddings**: Titan Embed Text v2 (1024-dim)
- **Generation**: Claude (Haiku, Sonnet) via cross-region inference profiles
- **Optional reranking**: Amazon Rerank v1:0

Three credential modes are supported depending on deployment environment:

| Mode | Environment | Auth Method | Configuration |
|------|-------------|------------|---|
| **Instance Profile** | EC2 / K3s on EC2 | Node IAM role | Zero config — auto-assumed from instance metadata |
| **IRSA** | EKS (recommended) | Pod ServiceAccount + OIDC | Terraform + Helm roleArn |
| **Static Keys** | Portable / on-prem bridging | AWS_ACCESS_KEY_ID / SECRET_KEY | Helm values + datapond-secrets Secret |

---

## Credential Modes

### Mode 1: EC2 / K3s Instance Profile (PoC)

**Use when:** Running K3s on an EC2 instance with DataPond's IAM instance profile.

**Prerequisites:**
- EC2 instance has IAM instance profile `datapond-app-profile` attached (created by PR #100 terraform).
- Instance profile has Bedrock permissions (defined in `terraform/iam.tf`).

**Configuration:** None required. LiteLLM automatically assumes the instance profile via metadata service (`http://169.254.169.254`).

**Verify:**
```bash
# From inside a pod, check role assumption
kubectl exec -it deploy/litellm -n datapond -- \
  python -c "import boto3; print(boto3.Session().get_credentials())"
```

---

### Mode 2: Bring-Your-Own EKS + IRSA

**Use when:** Running DataPond on an existing EKS cluster. The chart supports IRSA,
but the current Terraform stack does not create EKS; the maintained AWS infrastructure
reference uses EC2/K3s and an instance profile.

**Prerequisites:**
- EKS cluster with OIDC provider configured.
- AWS account with Bedrock model access enabled (console → Bedrock → Model access).

**Step 1: Terraform configuration**

Run Terraform with EKS OIDC parameters:
```bash
cd terraform
terraform apply \
  -var eks_oidc_provider_arn="arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.REGION.amazonaws.com/id/EXAMPLE" \
  -var eks_oidc_provider_url="oidc.eks.REGION.amazonaws.com/id/EXAMPLE"
```

This creates an IAM role (`datapond-litellm-bedrock-role`) with Bedrock permissions and a trust relationship to the EKS OIDC provider. `eks_oidc_provider_url` is the issuer host/path **without** `https://`, because Terraform uses it as an IAM condition-key prefix.

**Step 2: Extract role ARN**
```bash
export LITELLM_ROLE_ARN=$(terraform output -raw litellm_bedrock_role_arn)
echo $LITELLM_ROLE_ARN
# Output: arn:aws:iam::ACCOUNT_ID:role/datapond-litellm-bedrock-role
```

**Step 3: Deploy Helm with IRSA**
```bash
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-aws.yaml \
  --set litellm.serviceAccount.roleArn="$LITELLM_ROLE_ARN"
```

**Verify:**
```bash
# Check ServiceAccount annotation
kubectl get sa -n datapond litellm -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}'

# From pod, verify role assumption (should show Bedrock IAM role)
kubectl exec -it deploy/litellm -n datapond -- \
  curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/ | head -1
```

---

### Mode 3: Static Credentials (Portable / Bridging)

**Use when:** Running outside AWS (air-gapped, on-prem bridging, local dev with Bedrock access).

**Prerequisites:**
- AWS Access Key ID and Secret Access Key with Bedrock permissions.
- `datapond-secrets` Kubernetes Secret already created (for Aurora/other config).

**Step 1: Add credentials to secret**
```bash
kubectl -n datapond patch secret datapond-secrets --type merge -p \
  '{"stringData":{"AWS_ACCESS_KEY_ID":"<your-key>","AWS_SECRET_ACCESS_KEY":"<your-secret>"}}'
```

Or, recreate the secret:
```bash
kubectl -n datapond create secret generic datapond-secrets \
  --from-literal=POSTGRES_USER=datapond \
  --from-literal=POSTGRES_PASSWORD=<db_password> \
  --from-literal=POSTGRES_DB=datapond \
  --from-literal=JWT_SECRET=<random> \
  --from-literal=INTERNAL_API_KEY=<random> \
  --from-literal=AWS_ACCESS_KEY_ID=AKIA... \
  --from-literal=AWS_SECRET_ACCESS_KEY=wJ... \
  --dry-run=client -o yaml | kubectl apply -f -
```

**Step 2: Enable static credentials in Helm**
```bash
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-aws.yaml \
  --set litellm.aws.staticCredentials=true
```

**Verify:**
```bash
# Check that secrets are mounted
kubectl exec -it deploy/litellm -n datapond -- \
  printenv | grep AWS_ACCESS_KEY_ID
```

---

## Model Configuration

### Overview

LiteLLM configuration (`litellm.config.model_list` in Helm values) defines available models and their Bedrock mappings.

### Default Configuration (values-aws.yaml)

```yaml
litellm:
  config:
    model_list:
      # Embedding model (RAG, vector search)
      - model_name: "embed"
        litellm_params:
          model: "bedrock/amazon.titan-embed-text-v2:0"
          aws_region_name: "us-east-1"

      # Default generation model (fallback, non-chat)
      - model_name: "default"
        litellm_params:
          model: "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"
          aws_region_name: "us-east-1"

      # Chat model (conversational)
      - model_name: "chat"
        litellm_params:
          model: "bedrock/us.anthropic.claude-sonnet-4-6-20250514-v1:0"
          aws_region_name: "us-east-1"

  # Backend environment variables
  env:
    AI_EMBED_MODEL: "embed"          # Which model_name to use for embeddings
    AI_EMBED_DIM: "1024"              # Titan Embed v2 dimension
    LITELLM_MODEL: "default"          # Default generation fallback
```

### Region & Inference Profiles

Bedrock uses regional inference profiles for multi-region deployments:

| Region | Claude Model ID | Titan Embed |
|--------|-----------------|-------------|
| **us-east-1** (N. Virginia) | `bedrock/us.anthropic.claude-*` | ✅ v2 |
| **ap-northeast-2** (Seoul) | `bedrock/apac.anthropic.claude-*` | ✅ v2 |

**To enable Seoul region:**
```yaml
litellm:
  config:
    model_list:
      - model_name: "embed-apac"
        litellm_params:
          model: "bedrock/amazon.titan-embed-text-v2:0"
          aws_region_name: "ap-northeast-2"
      
      - model_name: "chat-apac"
        litellm_params:
          model: "bedrock/apac.anthropic.claude-sonnet-4-6-20250514-v1:0"
          aws_region_name: "ap-northeast-2"
```

### Model Access in AWS Console

**Required:** Each region must have model access explicitly enabled in Bedrock console.

**Steps:**
1. AWS Console → Bedrock → Model access (left sidebar)
2. For each region you use (us-east-1, ap-northeast-2):
   - Search for "Anthropic Claude" (Sonnet 4.6 + Haiku 4.5) → Request access → Approve
   - Search for "Amazon Titan Text Embeddings V2" → Request access → Approve
3. Wait for "Access Granted" status (usually immediate, sometimes 5-10 min)

Without model access, requests to unavailable models return 403 `ModelNotFound`.

---

## Runtime Configuration (Settings UI)

**Preferred method** for non-Helm configuration: Settings → System → AI.

### Add Bedrock Backend (Interactive)

1. **Navigate** to Settings → System → AI (or `/settings/system/ai`)
2. **Click** "+ Add Backend"
3. **Fill form:**
   - **Provider**: `bedrock`
   - **Model ID**: (e.g., `bedrock/us.anthropic.claude-sonnet-4-6-20250514-v1:0`)
   - **AWS Region**: `us-east-1` (or `ap-northeast-2`)
   - **Access Key / Secret Key**: Leave blank (uses IRSA/instance role)
4. **Save** → Backend added to `ai_backends` table

### Credential Handling

- **IRSA / Instance Profile**: Leave keys blank. Backend will use pod/node credentials.
- **Static Keys**: Fill Access Key / Secret Key. Values are encrypted in `ai_backends.auth_secret` column (via `CredentialVault`).

Backend API endpoint: `POST /api/settings/ai/backends`

```bash
curl -X POST http://localhost:8000/api/settings/ai/backends \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "bedrock",
    "model_id": "bedrock/us.anthropic.claude-sonnet-4-6-20250514-v1:0",
    "aws_region_name": "us-east-1",
    "access_key": "",
    "secret_key": ""
  }'
```

---

## Optional: Reranking

Bedrock offers Amazon Rerank v1:0 for improving RAG result relevance.

### Enable Reranking

Set environment variable (Helm values or pod env):
```yaml
litellm:
  env:
    AI_RERANK_MODEL: "bedrock/amazon.rerank-v1:0"
    AI_RERANK_REGION: "us-east-1"  # optional, defaults to us-east-1
```

### How It Works

When `/api/ai/rag` or `/api/ai/search` is called with reranking enabled:
1. Vector search returns top-k candidates (e.g., k=10)
2. Rerank model scores candidates by relevance to query
3. Top-n results returned (usually k=5 after rerank)

**API request (no change):**
```bash
curl -X POST http://localhost:8000/api/ai/rag \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "collection": "my-collection",
    "question": "What is DataPond?",
    "k": 5
  }'
```

Reranking runs automatically if `AI_RERANK_MODEL` is set.

---

## Optional: Bedrock Guardrails

Bedrock offers content filtering via Guardrails. Configuration is per-model in LiteLLM.

**Not enabled by default.** To enable:

```yaml
litellm:
  config:
    model_list:
      - model_name: "chat"
        litellm_params:
          model: "bedrock/us.anthropic.claude-sonnet-4-6-20250514-v1:0"
          aws_region_name: "us-east-1"
          # Optional: guardrails config
          guardrail_identifier: "arn:aws:bedrock:us-east-1:ACCOUNT:guardrail/G123"
          guardrail_version: "1"
```

For details, see [AWS Bedrock Guardrails docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html).

---

## Verification

### Quick Health Check

```bash
# 1. Check LiteLLM pod is running
kubectl get pods -n datapond -l app=litellm

# 2. Check LiteLLM health endpoint
kubectl exec -it deploy/litellm -n datapond -- \
  curl -s http://localhost:4000/health | jq

# Expected output:
# {
#   "status": "ok",
#   "model_list": [
#     { "model_name": "embed", ... },
#     { "model_name": "chat", ... }
#   ]
# }
```

### RAG Smoke Test

```bash
# 1. Get auth token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<password>"}' | jq -r .access_token)

# 2. Test RAG (check has_ai=true and no credential errors)
curl -s -X POST http://localhost:8000/api/ai/rag \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "collection": "default",
    "question": "What services are running?",
    "k": 3
  }' | jq

# Expected output:
# {
#   "answer": "...",
#   "citations": [...],
#   "has_ai": true
# }
```

### Logs

```bash
# Check for credential / API errors
kubectl logs -f deploy/litellm -n datapond | grep -E "(ERROR|403|Unauthorized|Bedrock)"

# Check backend for embedding errors (RAG ingest)
kubectl logs -f deploy/backend -n datapond | grep -E "(ERROR|embed|bedrock)" | head -20
```

### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ModelNotFound` (403) | Model access not enabled in console | Enable in Bedrock → Model access |
| `AccessDenied` | Credentials missing / invalid | Check instance profile (EC2) or IRSA annotation (EKS) or Secret keys (static) |
| `AuthorizationException` | IAM role lacks Bedrock perms | Update IAM policy in terraform/iam.tf; re-apply terraform |
| `ThrottlingException` | Rate limit hit | Bedrock quotas: default 100 req/min; contact AWS support for increase |
| Empty `has_ai=false` | LiteLLM not responding | Check `kubectl logs deploy/litellm` and pod status |

---

## References

- [AWS Bedrock Docs](https://docs.aws.amazon.com/bedrock/)
- [LiteLLM Bedrock Integration](https://docs.litellm.ai/docs/providers/bedrock)
- [IRSA (IAM Roles for Service Accounts)](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [DataPond AWS MVP Runbook](./AWS_MVP_RUNBOOK.md)
