# Sovereign Core

> File: `helm/datapond/values-sovereign-core.yaml`. The on-prem twin of the Portable Core · AWS starter.

## What runs

| Component | Role |
|---|---|
| Backend | Knowledge/RAG, authentication, governance, storage and AI APIs |
| Frontend | Capability-aware operator UI |
| PostgreSQL + pgvector | Application state, collections, chunks, vectors |
| LiteLLM | Logical model gateway to the local model |
| Valkey | Cache/session support |
| MinIO | S3-API object storage, in-cluster |
| Ollama | Local embedding (`bge-m3`, 1024-d) and chat (`qwen2.5-coder:7b`) models |

`minio.clusterIP` is pinned (`10.43.107.150`) because the chart's CoreDNS override needs
a fixed address to synthesize A records for virtual-host-style S3 hostnames for
in-cluster MinIO. `storage.bucket` is not a chart key.

## What does not run

trino, spark, polaris, airflow, mlflow, risingwave, openmetadata, jupyter, vllm — all stated `false`.
No catalog backend, so Sources / Catalog / Analytics stay hidden. Nothing leaves the cluster:
`ai.egressPolicy: local-only`.

## Core workflow

Create a collection → ingest text or MinIO objects → search and cited answers → issue a
service-account key → call `/api/ai/rag` from your agent → review Governance.

## Prerequisites

Kubernetes + Helm; a node with at least 16 GB RAM and 8 vCPU for Ollama's defaults; a
storage class for three PVCs (postgres 50Gi, minio 100Gi, ollama 20Gi). GPU optional.

## Install

    helm upgrade --install datapond helm/datapond -n datapond --create-namespace \
      -f helm/datapond/values-sovereign-core.yaml

First start pulls the two Ollama models; the LiteLLM init job registers them as `embed`
and `default`.

## Model configuration

`ai.embedDim` must equal the embedding model's dimension. `bge-m3` is 1024-d. To use
another model, set `ollama.embedModel` and `ai.embedDim` **before the first ingest**;
changing the dimension later requires recreating `ai_chunks` and re-embedding.
To use an external OpenAI-compatible server instead of Ollama, set `ollama.enabled: false`,
`ai.llmEndpoint`, and a hand-written `litellm.config.model_list` with `embed`, `default`,
`chat` entries.

## Security boundary

Same as the AWS starter: application-level collection ACL, SQL-rewrite RLS when tables
exist, PII masking, append-only audit. Add-ons are absent rather than disabled-but-present.

The profile inherits the chart's default external scheme (`http`); once you front it
with an HTTPS ingress, set `global.externalScheme: https` — WebAuthn and OIDC derive
their origin from it.

## When to choose another profile

You need Iceberg tables, Trino/Polaris, or any OSS add-on: `values-onprem.yaml`
(community, extended). You are on AWS: `values-foundation.yaml` or `values-prod-single.yaml`.
