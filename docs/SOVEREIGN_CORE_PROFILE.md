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
No catalog backend, so Sources / Catalog / Analytics stay hidden.

No prompt, document text or embedding is sent to an external model provider:
`ai.egressPolicy: local-only` is enforced at the gateway and fails closed
(`backend/app/api/ai_vectors.py:152-168`). It is not a network egress control — the
NetworkPolicy allows outbound traffic (see `templates/networkpolicy.yaml`), and first
boot pulls container images and ~6 GB of Ollama models from the internet unless you
mirror them.

## Core workflow

Create a collection → ingest text or MinIO objects → search and cited answers → issue a
service-account key → call `/api/ai/rag` from your agent → review Governance.

## Prerequisites

The defaults in this profile target **k3s**: the pinned `minio.clusterIP` assumes k3s's
default service CIDR (`10.43.0.0/16`), `ingress.className` defaults to Traefik (k3s's
built-in ingress controller), and the CoreDNS custom-override ConfigMap is inert unless
CoreDNS actually imports `/etc/coredns/custom/*.override` (k3s's CoreDNS does this by
default; most other distributions do not). On a non-k3s cluster, an operator sets:

- `minio.clusterIP` — a free address inside your cluster's service CIDR. kubeadm
  defaults to `10.96.0.0/12`, OpenShift to `172.30.0.0/16`. Find yours:
  `kubectl cluster-info dump | grep -m1 service-cluster-ip-range`.
- `ingress.className` — if the cluster's ingress controller is not Traefik (e.g. nginx).
- Confirmation that CoreDNS imports `/etc/coredns/custom/*.override`, or the S3
  virtual-host hostnames MinIO needs will not resolve in-cluster.

Kubernetes + Helm; a node with at least 32 GB RAM and 8 vCPU (matching
`values-onprem.yaml`'s recommended capacity for the same two models); a storage class
for four PVCs (postgres 50Gi, minio 100Gi, ollama 20Gi, valkey 5Gi). Rendered resource
totals at the declared replica counts: requests 2.9 vCPU / 7.75 Gi, limits 10.5 vCPU /
16.5 Gi — headroom above that, plus OS/kubelet overhead, is what the 32 GB figure
covers.

Inference in this profile is **CPU-only**: Ollama has no GPU wiring here, so the 7B
chat model runs at single-digit tokens/s. The GPU-accelerated path is `vllm` (see
Model configuration), not Ollama.

## What is verified

`maturity: supported-starter` is the same evidence class as the AWS starter, minus live
acceptance: the profile is rendered, linted and flag-pinned in CI
(`backend/tests/test_helm_sovereign_core.py`, `test_helm_addon_defaults.py`,
`test_capability_support_tiers.py`). It has not been installed on a live self-hosted
cluster in this evidence chain — that acceptance run is the open item tracked in
CLAUDE.md's incomplete-items list.

## Install

```bash
helm upgrade --install datapond helm/datapond -n datapond --create-namespace \
  -f helm/datapond/values-sovereign-core.yaml
```

First start pulls the two Ollama models; the LiteLLM init job registers them as `embed`
and `default`.

1. **Admin password.** The chart generates one and stores it in the `datapond-secrets`
   Secret (`templates/secrets.yaml`):

   ```bash
   kubectl -n datapond get secret datapond-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d
   ```

2. **Reaching the UI.** Set `ingress.domain` (default `datapond.local`, resolved by the
   chart's ingress template) to a domain you control. `ingress.tls.enabled` already
   defaults to `false` in this profile — plain HTTP unless you turn it on. The
   `cert-manager.io/cluster-issuer: letsencrypt-prod` annotation is still applied to the
   Ingress regardless (there is no values key to remove it selectively); it is inert
   without cert-manager installed in the cluster, and issuing a real certificate needs
   outbound internet access to Let's Encrypt.

3. **Create a bucket.** Nothing creates one automatically — the chart's bucket-init job
   is gated on Polaris, which this profile does not run. Use Storage → create bucket in
   the UI, or `POST /api/storage/buckets/{name}` as an admin, before S3 ingestion.

4. **Confirm runtime identity.**

   ```bash
   curl -s https://<domain>/api/capabilities | jq '{profile_id, profile_maturity, knowledge, connectors, catalog, query, rls}'
   ```

   Expect `sovereign-core`, `supported-starter`, `true`, `false`, `false`, `false`,
   `false`.

5. **NetworkPolicy caveat.** With `networkPolicy.enabled: true` (this profile's
   default), the `datapond-allow-web` policy admits ingress only from the `kube-system`
   namespace and pods in the same namespace. If your ingress controller runs in its own
   namespace (common outside k3s, where Traefik lives in `kube-system`), the UI will be
   unreachable through it. There is no values key to widen the allowed namespace; set
   `networkPolicy.enabled: false` on such clusters.

## Model configuration

`ai.embedDim` must equal the embedding model's dimension. `bge-m3` is 1024-d. To use
another model, set `ollama.embedModel` and `ai.embedDim` **before the first ingest**;
changing the dimension later requires recreating `ai_chunks` and re-embedding.
To use an external OpenAI-compatible server instead of Ollama, set `ollama.enabled: false`,
`ai.llmEndpoint`, and a hand-written `litellm.config.model_list` with `embed` and
`default` entries — nothing consumes a logical model named `chat`.

## Security boundary

Same as the AWS starter: application-level collection ACL, SQL-rewrite RLS when tables
exist, PII masking, append-only audit. Add-ons are absent rather than disabled-but-present.

This profile deploys MinIO, which is AGPL-3.0 — see `THIRD_PARTY_NOTICES.md` before
procurement.

The profile inherits the chart's default external scheme (`http`); once you front it
with an HTTPS ingress, set `global.externalScheme: https` — WebAuthn and OIDC derive
their origin from it.

## When to choose another profile

You need Iceberg tables, Trino/Polaris, or any OSS add-on: `values-onprem.yaml`
(community, extended). You are on AWS: `values-foundation.yaml` or `values-prod-single.yaml`.
