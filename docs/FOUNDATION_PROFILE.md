# Portable Core · AWS Starter

> Backward-compatible file and values name: `FOUNDATION_PROFILE.md` / `values-foundation.yaml`.

This is the smallest maintained DataPond profile for governed RAG on AWS. It uses S3 and Bedrock while keeping PostgreSQL/pgvector, LiteLLM, Valkey, and the application in Kubernetes.

## What runs

| Component | Role |
|---|---|
| Backend | Knowledge/RAG, authentication, governance, storage and AI APIs |
| Frontend | Capability-aware operator UI |
| PostgreSQL + pgvector | Application state, Knowledge collections, chunks, vectors |
| LiteLLM | Logical model gateway to Bedrock |
| Valkey | Cache/session support |
| Amazon S3, external | Source objects; accessed with AWS credentials/IAM |
| Amazon Bedrock, external | Embeddings and generation |

## What does not run

```yaml
trino: false
spark: false
polaris: false
airflow: false
mlflow: false
risingwave: false
openmetadata: false
jupyter: false
ollama: false
vllm: false
minio: false
```

The absence of these services does not provision Athena, Glue, EMR, MWAA, SageMaker, Managed Flink, DataZone, or any other replacement.

Consequences:

- Knowledge, AI Gateway, Governance, Storage, Services, System, and Settings remain available.
- Sources, Catalog, SQL Lab, Dashboards, Transforms, Streaming, Notebooks, Experiments, and external lineage are hidden.
- Direct navigation to an optional module returns a profile-aware disabled state.

## Core workflow

```text
S3/text → chunk → PII mask → Bedrock embedding → PostgreSQL/pgvector
question → vector retrieve → optional rerank → Bedrock generation → citations
```

The RAG freshness scheduler is part of the backend and does not require Airflow.

## Prerequisites

- Kubernetes and Helm
- reachable PostgreSQL storage for the in-cluster StatefulSet/PVC
- AWS credentials through node role, IRSA on a bring-your-own EKS cluster, or static credentials
- Bedrock model access in the selected region
- access to the S3 sources used by ingestion requests

## Install

```bash
helm upgrade --install datapond helm/datapond \
  --namespace datapond --create-namespace \
  --values helm/datapond/values-foundation.yaml
```

Confirm runtime identity:

```bash
curl -s https://<domain>/api/capabilities | jq '{
  profile_id,
  profile_label,
  catalog_backend,
  query_engine,
  storage_provider,
  vector_store,
  model_gateway
}'
```

Expected product identity:

```json
{
  "profile_id": "portable-core-aws",
  "profile_label": "Portable Core · AWS",
  "catalog_backend": "none",
  "query_engine": "none",
  "storage_provider": "s3",
  "vector_store": "postgres-pgvector",
  "model_gateway": "litellm"
}
```

## Use Aurora instead of in-cluster PostgreSQL

Set:

```yaml
postgres:
  enabled: false
externalDatabase:
  enabled: true
  host: <aurora-writer-endpoint>
  port: 5432
  name: datapond
  sslmode: require
```

This changes the vector/state adapter but does not add Glue/Athena or create infrastructure. For the actual Terraform-backed AWS reference use `values-prod-single.yaml` and [DEPLOY_SINGLE_NODE.md](DEPLOY_SINGLE_NODE.md).

## Model configuration

Default logical model names:

- `embed` → Titan Text Embeddings v2
- `default` → Claude Haiku
- `chat` → Claude Sonnet

Application code should use logical names. Provider model IDs stay in LiteLLM configuration. See [AWS_BEDROCK_SETUP.md](AWS_BEDROCK_SETUP.md).

## Security boundary

- Knowledge collection access is owner/admin/shared application ACL, not database-native collection RLS.
- PII masking is applied on ingestion and retrieval.
- AI egress is `cloud-allowed` because Bedrock is external to the cluster.
- The profile does not deploy AGPL MinIO or Elasticsearch/OpenMetadata; review [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## When to choose another profile

| Requirement | Profile |
|---|---|
| Terraform-backed Aurora/S3/Glue/Athena/Bedrock reference | `values-prod-single.yaml` |
| Existing Kubernetes plus AWS and intentionally retained OSS engines | `values-aws.yaml` |
| Local/self-hosted services and model path | `values-onprem.yaml` |
| Development/integration | `values-dev.yaml` or `values-quicktest.yaml` |

See [DEPLOYMENT_PROFILES.md](DEPLOYMENT_PROFILES.md) for the full matrix.
