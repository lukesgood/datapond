# AWS RAG Acceptance Runbook

This runbook validates the shipped AWS adapter path:

```text
S3 source → Bedrock embedding → PostgreSQL/pgvector → optional rerank → Bedrock answer + citations
```

It does not provision infrastructure. For the Terraform-backed EC2/K3s reference, follow [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md). For the lean starter, follow [FOUNDATION_PROFILE.md](FOUNDATION_PROFILE.md).

## 1. Choose the deployment under test

| Profile | Database | Catalog/query | Expected test scope |
|---|---|---|---|
| `values-foundation.yaml` | in-cluster PostgreSQL/pgvector | none | Knowledge/RAG, PII, spend |
| `values-prod-single.yaml` | Aurora PostgreSQL/pgvector | Glue/Athena | Core scope plus Catalog/SQL |

`values-aws.yaml` is the hybrid extended compatibility overlay and is not the default target for this runbook.

## 2. Prerequisites

- deployment is healthy and `/api/capabilities` reports the expected profile;
- Bedrock model access is enabled for Titan Embed, Claude, and optional Amazon Rerank;
- the backend/LiteLLM can obtain AWS credentials through instance profile, IRSA on a bring-your-own EKS cluster, or configured static credentials;
- the role can read the test S3 prefix and invoke the configured models;
- an administrator credential is available.

Check profile identity:

```bash
curl -sk https://<domain>/api/capabilities | jq '{
  profile_id, profile_label, knowledge, catalog, query,
  storage_provider, vector_store, model_gateway,
  catalog_backend, query_engine
}'
```

## 3. Upload a representative source

Use non-sensitive test documents containing:

- facts that can be answered deterministically;
- at least one repeated source update case;
- synthetic PII for masking verification;
- enough documents to produce multiple chunks.

```bash
aws s3 cp ./samples/ s3://<bucket>/rag-acceptance/ --recursive
```

## 4. Authenticate

```bash
TOKEN=$(curl -sk -X POST https://<domain>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<password>"}' | jq -r .access_token)

test -n "$TOKEN" && test "$TOKEN" != null
```

### 4a. Run the read-only deployment preflight

From a trusted operator workstation that has `kubectl`, `curl`, and `jq`, run the
validator against the deployed origin. With no pre-issued token it prompts for the admin
password without echoing it:

```bash
DATAPOND_BASE_URL=https://<domain> \
  bash scripts/validate-deployment.sh
```

For automation, prefer a mode-`0600` token file instead of putting a credential on the
command line:

```bash
umask 077
printf '%s' "$TOKEN" > /tmp/datapond-admin.token

DATAPOND_BASE_URL=https://<domain> \
DATAPOND_TOKEN_FILE=/tmp/datapond-admin.token \
  bash scripts/validate-deployment.sh

rm -f /tmp/datapond-admin.token
```

The script checks pod readiness/restarts, health, frontend availability, the admin role,
protected read-only API contracts, and backend TCP reachability to its configured
PostgreSQL and Valkey/Redis hosts. An absent in-cluster Postgres pod is treated as an
external-database profile and direct schema inspection is skipped with a warning. The
script does not create, update, delete, restart, or scale application resources.

Optional live boundary checks can be enabled with mode-`0600` files:

```bash
DATAPOND_BASE_URL=https://<domain> \
DATAPOND_TOKEN_FILE=/secure/admin.token \
DATAPOND_VIEWER_TOKEN_FILE=/secure/viewer.token \
DATAPOND_INTERNAL_KEY_FILE=/secure/internal-key \
  bash scripts/validate-deployment.sh
```

These optional checks assert that a viewer receives `403` from the read-only admin system
settings endpoint and that an internal key alone receives `401` on `GET /api/services`.
The validator deliberately does **not** exercise a successful internal-key callback,
because both allowed callbacks are mutating `POST` operations. Validate the positive
internal callback only against a dedicated connector/collection fixture, then verify its
result and clean up that fixture explicitly. Never print or retain the token/key files as
evidence.

## 5. Create and ingest a collection

```bash
curl -sk -X POST https://<domain>/api/ai/collections \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"aws-acceptance","description":"AWS adapter acceptance"}' | jq .

curl -sk -X POST https://<domain>/api/ai/collections/aws-acceptance/ingest-source \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"type":"s3","bucket":"<bucket>","prefix":"rag-acceptance/","max_files":50}' | jq .
```

Pass condition: `documents > 0`, `chunks > 0`, and no embedding/provider error.

## 6. Validate retrieval before generation

```bash
curl -sk -X POST https://<domain>/api/ai/search \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"collection":"aws-acceptance","query":"<known phrase>","k":5}' | jq .
```

Check:

- expected source appears near the top;
- source URIs reference the test prefix;
- synthetic PII is masked according to the configured mode;
- rerank failure, if induced, falls back without failing the search.

## 7. Validate cited RAG

```bash
curl -sk -X POST https://<domain>/api/ai/rag \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"collection":"aws-acceptance","question":"<answerable question>","k":5}' | jq .
```

Pass condition:

- `has_ai=true`;
- answer is non-empty;
- citations are non-empty and reference the expected source;
- answer is grounded in the supplied documents;
- no unmasked synthetic PII is returned.

## 8. Validate replacement and freshness

1. Change one source document while retaining the same source URI/group.
2. Re-run ingestion.
3. Confirm old chunks for that source group were replaced rather than duplicated.
4. Confirm retrieval returns the new fact and not the previous value.
5. If a schedule is configured, verify stale → scheduled re-embedding behavior.

## 9. Validate governance and spend

- non-owner cannot access a private collection unless shared;
- administrator can inspect the collection;
- shared user can access only explicitly shared collections;
- AI usage contains the actor/user metadata and model usage;
- budget status is visible where configured;
- treat durable budget notification delivery as hardening/roadmap unless separately implemented.

Collection ACL is currently application-level owner/admin/shared enforcement, not PostgreSQL-native collection RLS.

## 10. Optional Glue/Athena acceptance

Run only when `/api/capabilities` reports:

```json
{"catalog": true, "query": true, "catalog_backend": "glue", "query_engine": "athena"}
```

Verify:

1. Catalog lists expected Glue databases/tables.
2. Athena executes a bounded `SELECT` and writes results to the configured output location.
3. Catalog → Send to Knowledge creates/updates a collection.
4. The resulting collection can answer a cited question.
5. IAM denies access outside the intended bucket/catalog scope.

Do not run or claim this scope for `values-foundation.yaml`.

## 11. Evidence to record

- date, commit SHA, chart version, profile ID;
- AWS account alias/region without secrets;
- model IDs and embedding dimension;
- collection/document/chunk counts;
- retrieval and RAG result samples with test data only;
- Glue/Athena evidence when applicable;
- failures, fallbacks, latency, and cost observations.

## 12. Pass/fail summary

A release may claim the AWS RAG adapter path only when sections 5–9 pass. Glue/Athena claims require section 10. EKS, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, and Marketplace require separate implementation and acceptance; this runbook does not validate them.

For critical secret generation, preservation, and restore ordering, use [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md) and [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md).
