# Lean "AI Data Foundation" Profile

`helm/datapond/values-foundation.yaml` — the minimal DataPond footprint for the
**AWS-native AI-app use case**: `S3 → embed → pgvector → Bedrock` RAG with
governance (RLS, PII masking, spend), and nothing else.

It cuts the deployable workloads from **~16 to ~5** by disabling the heavy
lakehouse components, which on AWS are better served by managed services.

## What runs (core, ~5 workloads)

| Component | Role |
|---|---|
| **backend** (FastAPI) | AI data APIs — ingest, embed, vector search, RAG, governance |
| **frontend** (Next.js) | Management UI |
| **Postgres + pgvector** | The AI vector store (`ai_collections`/`ai_chunks`) |
| **LiteLLM → Bedrock** | Embeddings (Titan) + generation (Claude), multi-model routing |
| **Valkey** | Cache/sessions (lightweight) |
| **S3** (external) | Source data + object storage (no in-cluster MinIO) |

## What's disabled → AWS managed alternative

| Disabled OSS | Use instead on AWS |
|---|---|
| Trino | **Amazon Athena** |
| Spark | **EMR Serverless / Glue ETL** |
| Airflow | **MWAA** |
| MLflow | **SageMaker** (Experiments / Model Registry) |
| RisingWave | **MSK / Managed Service for Apache Flink** |
| Polaris | **Glue Data Catalog** |
| OpenMetadata | **DataZone** — or re-enable as an OSS differentiator (`--set openmetadata.enabled=true`) |
| Jupyter | **SageMaker Studio** |
| Ollama / vLLM | **Bedrock** / SageMaker endpoints |

## Graceful degradation (no code changes)

The backend **starts cleanly** with the heavy components off: their clients
connect lazily (inside request handlers), and startup steps that do reach out
(Trino medallion init, Airflow maintenance DAG) are best-effort `try/except`.
The core RAG path (`/api/ai/*`) depends only on S3 + LiteLLM + pgvector.

Lakehouse-only UI pages (Catalog, Query Lab, Pipelines, Streaming, Experiments)
return handled errors / empty states when their backend component is absent —
the frontend already degrades per-page. (A capability-based UI that *hides*
those pages in this profile is a possible future enhancement.)

## Deploy

```bash
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-foundation.yaml \
  --set storage.bucket=<your-s3-bucket>
```

- **Bedrock credentials**: see [AWS_BEDROCK_SETUP.md](AWS_BEDROCK_SETUP.md)
  (EKS IRSA / EC2 instance profile / static keys).
- **Aurora instead of in-cluster Postgres**: set `postgres.enabled=false` +
  `externalDatabase.enabled=true` (see `values-aws.yaml`).

## When to use which profile

| Profile | For |
|---|---|
| **values-foundation** | AI-app teams — lean RAG data foundation on AWS |
| values-aws | Full lakehouse on AWS (S3 + Bedrock, all engines) |
| values-onprem / values-quicktest | Self-hosted / sovereign (MinIO, optional local LLM) |

## License considerations for regulated procurement

The **foundation profile** (`values-foundation.yaml`) deploys **no AGPL or
Elastic-licensed components**: object storage is native Amazon S3 (no MinIO) and
OpenMetadata/Elasticsearch is disabled. `values-aws.yaml` also uses native S3 (no
MinIO) but inherits OpenMetadata — and with it Elasticsearch 8.x (Elastic License
2.0/SSPL) — from the base chart defaults; set `openmetadata.enabled: false` there if
ELv2 is a procurement blocker. Profiles that enable MinIO (onprem/dev/quicktest/prod)
deploy it under AGPL-3.0 as an unmodified upstream image operated by you. Full
inventory: [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
