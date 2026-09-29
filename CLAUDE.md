# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DataPond is a **governed data tool server for AI agents and applications**: cited RAG and governed SQL exposed as tools, with collection/row access, PII masking, retrieval-level audit, and model spend controlled per caller at the data layer. Agents call it directly over REST/OpenAPI or the read-only MCP server at `POST /api/mcp`; an agent gateway is optional, not assumed. The shipped core covers ingestion, chunk replacement, embeddings, pgvector retrieval, optional reranking, cited answers, service-account keys (scoped, expiring, rotatable, rate-limited), collection ACL, chunk-level caller filters, RLS/masking, PII controls, tool-call audit, and enforced per-caller budgets. Agents authenticate with a `dp_sk_` key or, when OAuth resource-server mode is configured, the customer's IdP access token (not yet exercised against a live IdP). AWS is the current reference adapter environment, not the product boundary.

Canonical product truth:
- `README.md`
- `docs/PRODUCT_CONCEPT.md`
- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT_PROFILES.md`
- `docs/PORTABILITY.md`
- `docs/POSITIONING_REVIEW.md` (why v6.0) and `docs/POSITIONING_FIT_AUDIT.md` (what still does not fit)

`docs/superpowers/plans/` and `docs/superpowers/specs/` are historical implementation records, not current product claims.

Key positioning (v6.0 — governed tool layer, 2026-09-07):
- **Target:** teams whose AI agents and applications need governed access to company documents and tables. First segment: Korean enterprises on AWS with personal-data obligations.
- **Core value:** search, cited answers, and governed SQL as tools behind service-account keys, governed at the data layer (which caller reads which collection/row; what was cited and masked; per-caller spend). Orthogonal to agent gateways such as AgentCore Gateway: register behind one if the customer runs it, never require it. Portability is a lock-in objection remover, not the headline.
- **Not doing:** gateway features (agent registry, SSO/SCIM sync, tool-level policy engine, rug-pull detection), coding-agent spend control, ontology Phase 1, more add-ons, more operator-assistant actions, regulated verticals as first partner.
- **Portability:** S3 API, PostgreSQL + pgvector, LiteLLM/OpenAI-compatible model boundary, REST/OIDC, Helm/Kubernetes.
- **AWS reference:** S3, Aurora, Glue/Athena, and Bedrock where the selected profile actually enables them.
- **Optional OSS add-ons:** Polaris, Trino, RisingWave, OpenMetadata, Airflow, Spark, Jupyter, and MLflow.

Never claim that disabling an OSS component automatically provisions an AWS replacement. EKS, EMR Serverless, S3 Tables, Lake Formation, AOSS, DataZone, Marketplace packaging, and a unified export/import CLI remain roadmap until implementation and acceptance exist.

## Architecture

### Portable Core

```text
Frontend (Next.js) + Backend (FastAPI)
  ↓
Knowledge/RAG: ingest · chunk · PII · embed · retrieve · rerank · cite
  ↓
PostgreSQL + pgvector (in-cluster or Aurora)
  ↓
LiteLLM logical model gateway (Bedrock, cloud, or local provider mapping)
  ↓
S3 API object storage (native S3 or compatible endpoint)
```

Core navigation: Dashboard; Knowledge; AI Gateway; Governance; Storage; Services; System; Settings.

### Adapter and add-on layer

- Catalog/query: Glue + Athena in `values-prod-single.yaml`; Polaris + Trino in OSS extended profiles.
- Workloads: RisingWave, Airflow/Spark, OpenMetadata, Jupyter/DuckDB, and MLflow are capability-gated optional add-ons.
- `values-foundation.yaml` is the lean Portable Core AWS starter: in-cluster PostgreSQL/pgvector + external S3/Bedrock and no catalog/query service.
- `values-prod-single.yaml` is the current Terraform-backed AWS reference: EC2/K3s + Aurora/S3/Glue/Athena/Bedrock. It is not EKS or application-node HA.
- `values-aws.yaml` is a compatibility overlay for an existing cluster. It states none of the add-on flags, so it renders the Portable Core on a fresh install and preserves whatever an existing cluster is already running.

### Critical design rules

1. Knowledge/RAG must start cleanly with every data add-on disabled.
2. Runtime capability booleans, not profile labels, determine UI modules.
3. Optional navigation fails closed until a capability is explicitly true.
4. Provider-specific IDs and credentials belong in adapter configuration.
5. Collection access is currently application-level owner/admin/shared ACL; do not call it database-native collection RLS.
6. Capability means configured, not healthy; use Services/System for health.
7. Preserve existing profile filenames and flat capability API keys for compatibility.
8. Keep customer export/provider rebinding paths in Community.

### Data paths

- **Core RAG:** text/S3/configured table source → chunk + mask → LiteLLM embedding → pgvector → optional rerank → LiteLLM generation + citations.
- **Catalog bridge:** enabled Glue or Polaris catalog → Catalog → Send to Knowledge → scheduled freshness.
- **AI cost:** actor identity → LiteLLM `user`/metadata → usage and spend aggregation.
- **OSS extended:** Airflow/Spark/Polaris/Trino/RisingWave/OpenMetadata only when their flags are enabled.

## Deployment

### Prerequisites

- Kubernetes + Helm for all profiles
- AWS account and Terraform 1.10+ only for the AWS Single-Node Reference
- Bedrock model access for AWS profiles

### Deploy — AWS Single-Node Reference

The current infrastructure reference is single-node EC2/K3s with external Aurora, S3,
Glue/Athena, and Bedrock. Full runbook: **`docs/DEPLOY_SINGLE_NODE.md`**.

```bash
BUCKET=$(terraform -chdir=terraform output -raw bucket_name)
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=$(terraform -chdir=terraform output -raw aurora_endpoint) \
  --set backend.image.repository=$(terraform -chdir=terraform output -raw ecr_backend_repo_url) \
  --set frontend.image.repository=$(terraform -chdir=terraform output -raw ecr_frontend_repo_url) \
  --set-string catalog.glueWarehouse="s3://$BUCKET/warehouse" \
  --set-string catalog.athenaOutputLocation="s3://$BUCKET/athena-results/" \
  --set ingress.domain=<your-domain> \
  --wait=false
```

### Deploy — other profiles

| Product role | File | Use case |
|---|---|---|
| Portable Core · AWS | `values-foundation.yaml` | Lean S3/Bedrock RAG starter with in-cluster pgvector |
| Sovereign Core | `values-sovereign-core.yaml` | On-prem twin of the AWS starter: in-cluster MinIO + Ollama, no catalog/query, no add-ons |
| AWS Single-Node Reference | `values-prod-single.yaml` | Terraform-backed EC2/K3s + managed AWS adapters |
| AWS Hybrid Extended | `values-aws.yaml` | Existing Kubernetes + AWS endpoints; add-ons preserved if already running, otherwise off |
| Sovereign OSS Extended | `values-onprem.yaml` | Self-hosted optional OSS stack, 32 GB+ for full selection |
| Development/Quick Test | `values-dev.yaml` / `values-quicktest.yaml` | Local and integration validation |

```bash
# On-prem full OSS stack (secondary — self-hosted analytics engines)
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-onprem.yaml \
  --wait=false
```

### Helm operations

```bash
# Lint chart before deploy
helm lint helm/datapond --values helm/datapond/values-dev.yaml

# Dry-run to see what will be created
helm template datapond helm/datapond --namespace datapond --values helm/datapond/values-dev.yaml | grep "^kind:" | sort | uniq -c

# Uninstall
helm uninstall datapond -n datapond
```

### Post-deploy verification

```bash
kubectl get pods -n datapond
kubectl get ingress -n datapond
kubectl top nodes
```

## Key URLs

**Portable Core:** Dashboard · Knowledge · AI Gateway · Governance · Storage · Services · System · Settings are always present. Sources/Catalog/SQL Lab and add-on pages appear only when their runtime capability is explicitly true (`GET /api/capabilities`).

| Service | URL | Credentials |
|---|---|---|
| Frontend | `https://<your-domain>` | generated/configured admin |
| Backend API + OpenAPI | `https://<your-domain>/api` | bearer token |

> **Optional add-ons:** JupyterLab (`/jupyter`), Airflow (`/airflow`), MLflow (`/mlflow`), and OpenMetadata (`/openmetadata`) exist only when enabled. Self-hosted object storage is MinIO and is surfaced through the Storage UI.

## Helm Chart Structure

```text
helm/datapond/
  values.yaml                # Base OSS extended defaults
  values-foundation.yaml     # Portable Core · AWS starter
  values-sovereign-core.yaml # Sovereign Core (on-prem twin: MinIO + Ollama)
  values-prod-single.yaml    # AWS Single-Node Reference
  values-onprem.yaml         # Sovereign OSS Extended
  values-aws.yaml            # AWS Hybrid Extended compatibility; does not create EKS
  values-dev.yaml            # Development
  values-quicktest.yaml      # Integration/quick test
  values-prod.yaml           # Self-hosted extended compatibility
  Chart.yaml
  templates/
```

When adding a new component: add `enabled` flag, `image`, `replicas`, `resources`, `strategy: Recreate` to template, and mount `postgres-init-configmap` if DB needed.

## Local tests

Backend tests need a venv with every package in `backend/requirements.txt` (Homebrew Python refuses
system installs): `cd backend && python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt && .venv/bin/python -m pytest tests -q --ignore=tests/acceptance`.
A missing declared package surfaces as a failing test (e.g. `test_webauthn.py` without `webauthn`).
See `docs/DEVELOPMENT.md`.

## Operational Commands

```bash
# Watch pod startup
kubectl get pods -n datapond -w

# Logs
kubectl logs -f deployment/backend -n datapond
kubectl logs -f deployment/frontend -n datapond

# Restart a service
kubectl rollout restart deployment/backend -n datapond

# Scale manually
kubectl scale deployment backend --replicas=3 -n datapond

# Port-forward for direct access
kubectl port-forward svc/backend 8000:8000 -n datapond
kubectl port-forward svc/jupyter 8888:8888 -n datapond

# Debug a failing pod
kubectl describe pod <pod-name> -n datapond
kubectl logs <pod-name> -n datapond
```

## Agent Team

DataPond uses a **hierarchical AI agent system** for project management. The PM Agent coordinates specialized sub-agents to handle different aspects of the project.

### Available Agents

| Agent | Model | Agent Tool Param | Specialization | File |
|-------|-------|------------------|----------------|------|
| **PM Agent** | Opus 5 | `model: "opus"` | Project leadership, strategy, coordination | `pm-agent.md` |
| **Architecture Agent** | Opus 5 | `model: "opus"` | System design, tech decisions, ADRs | `architecture-agent.md` |
| **ML Consultant Agent** | Opus 5 | `model: "opus"` | ML strategy, data science workflows | `ml-consultant-agent.md` |
| **Backend Agent** | Sonnet 5 | `model: "sonnet"` | FastAPI, database, API implementation | `backend-agent.md` |
| **Frontend Agent** | Sonnet 5 | `model: "sonnet"` | Next.js, React, UI implementation | `frontend-agent.md` |
| **Design Agent** | Sonnet 5 | `model: "sonnet"` | UI/UX design, design system | `design-agent.md` |
| **DevOps Agent** | Sonnet 5 | `model: "sonnet"` | Kubernetes, Docker, CI/CD | `devops-agent.md` |
| **Error Correction Agent** | Sonnet 5 | `model: "sonnet"` | Debugging, error fixes, quality assurance | `error-correction-agent.md` |
| **Technical Writer Agent** | Sonnet 5 | `model: "sonnet"` | Documentation, help guides, user manuals | `technical-writer-agent.md` |

**Model Selection Rationale:**
- **Opus**: Strategic thinking, architecture decisions, complex reasoning (PM, Architecture, ML)
- **Sonnet**: Fast implementation, code generation, following patterns (Frontend, Backend, Design, DevOps, Error Correction)

### How to Use Agents

DataPond agents can be utilized in **TWO ways**:

#### Method 1: Read & Apply (Simple Tasks)
For straightforward implementation, Claude reads agent files and applies their guidelines directly.

```
User: "@pm-agent! shadcn/ui 기반으로 통합 관리 UI를 만들어줘"

Claude (as PM Agent):
1. Reads .claude/agents/frontend-agent.md
2. Reads .claude/agents/design-agent.md
3. Reads .claude/agents/backend-agent.md
4. Implements directly following their standards
5. Coordinates integration across components
```

**When to use:** Task requires <5 file changes, straightforward implementation

#### Method 2: Spawn Agent (Complex Tasks)
For complex work, PM Agent spawns specialized agents using the Agent tool.

**IMPORTANT: Each agent uses a specific model**
- **Opus**: PM, Architecture, ML Consultant (strategic thinking)
- **Sonnet**: Frontend, Backend, Design, DevOps (implementation)

```
User: "@pm-agent! ui가 별로임. Databricks 수준의 ui로 다시 작성"

Claude (as PM Agent):
1. Reads frontend-agent.md (model: claude-sonnet-5)
2. Reads design-agent.md (model: claude-sonnet-5)
3. Analyzes scope: Large redesign, data visualization needed
4. Spawns Frontend Agent with correct model:

Agent({
  description: "Redesign dashboard to Databricks-level UI",
  model: "sonnet",  // ← Frontend Agent uses Sonnet for fast implementation
  prompt: `You are the Frontend Agent for DataPond.

AGENT IDENTITY:
[Full contents of frontend-agent.md]

SUPPORTING CONTEXT:
[Contents of design-agent.md]

TASK:
Redesign entire dashboard with:
- Advanced data visualization (sparklines, trend charts)
- Professional layout (split panels, collapsible sections)
- Rich interactions (tooltips, smooth transitions)
- Databricks-level polish

FILES TO MODIFY:
- components/dashboard/stats-cards.tsx
- components/dashboard/service-card.tsx
- app/dashboard/page.tsx
...

Report back with implementation details.`
})
```

**When to use:** Task requires >5 file changes, extensive research, deep domain expertise, or user wants parallel work

**Model Selection:**
| Agent | Model | Use Case |
|-------|-------|----------|
| PM, Architecture, ML | `opus` | Strategy, complex decisions |
| Frontend, Backend, Design, DevOps | `sonnet` | Fast implementation |

#### Parallel Agent Execution

For truly independent tasks, spawn multiple agents in **single message** with correct models:

```typescript
// Read agent files to get model info
const frontendAgent = Read(".claude/agents/frontend-agent.md")  // sonnet
const backendAgent = Read(".claude/agents/backend-agent.md")    // sonnet
const devopsAgent = Read(".claude/agents/devops-agent.md")      // sonnet

// Spawn all in single message
Agent({
  description: "Frontend redesign",
  model: "sonnet",
  prompt: `${frontendAgent}\n\nTASK: ...`
})

Agent({
  description: "Backend APIs",
  model: "sonnet",
  prompt: `${backendAgent}\n\nTASK: ...`
})

Agent({
  description: "DevOps deployment",
  model: "sonnet",
  prompt: `${devopsAgent}\n\nTASK: ...`
})
```

**Agent Workflow (Complex Tasks):**
```
User Request → PM Agent Analysis
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   Spawn Agent    Spawn Agent   Spawn Agent
   (Frontend)     (Backend)     (DevOps)
        ↓             ↓             ↓
   Implementation Implementation Implementation
        ↓             ↓             ↓
   Agent Reports → PM Integration → User
```

### Agent Coordination Protocol

1. **PM Agent receives task**
2. **Analyzes complexity**: Simple → Read & Apply, Complex → Spawn Agent
3. **Reads agent files** for context and standards
4. **Executes or Spawns**: Direct implementation or Agent tool
5. **Reviews & Integrates**: Ensures consistency across agents
6. **Reports to user**: Summary of work completed

See `.claude/agents/pm-agent.md` for detailed spawning examples and coordination workflow.

## Key Documentation

| Doc | Purpose |
|-----|---------|
| `README.md` | Public overview — governed tool layer for AI agents and apps |
| `docs/README.md` | Active documentation index and status matrix |
| `docs/PRODUCT_CONCEPT.md` | Product strategy, boundary, users, and open-core policy |
| `docs/ARCHITECTURE.md` | Portable Core, adapters, add-ons, and capability semantics |
| `docs/DEPLOYMENT_PROFILES.md` | Truthful profile matrix and selection guide |
| `docs/FOUNDATION_PROFILE.md` | Portable Core · AWS starter (`values-foundation.yaml`) |
| `docs/PORTABILITY.md` | Portability boundaries and exit strategy |
| `docs/DEPLOY_SINGLE_NODE.md` | Current EC2/K3s AWS reference deployment |
| `docs/AWS_MVP_RUNBOOK.md` | S3 → Bedrock → pgvector RAG acceptance test |
| `docs/AWS_BEDROCK_SETUP.md` | LiteLLM ↔ Bedrock credential and model setup |
| `docs/DISASTER_RECOVERY.md` | Aurora/S3/critical-secret recovery |

> The v3.0 OSS lakehouse docs (ARCHITECTURE / DATABRICKS_FEATURE_COMPARISON / LITELLM_INTEGRATION / RISINGWAVE_INTEGRATION / OPENMETADATA_INTEGRATION / TROUBLESHOOTING / INSTALLATION / SPRINT_PLAN) were archived to the `archive/oss-lakehouse` branch — see `ARCHIVE.md`.

## Current Status

> **Direction (v6.0, 2026-09-07):** governed data tool server for AI agents and apps (v5.0 "Portable AI Data Foundation" superseded; see `docs/POSITIONING_REVIEW.md`). Where the build still does not fit: `docs/POSITIONING_FIT_AUDIT.md` §0. The pre-v6 completion log lives in `docs/archive/IMPLEMENTATION_LOG_2026H1.md`.

- **Tool surface:** REST/OpenAPI, read-only MCP at `POST /api/mcp` (26 read actions), gateway OpenAPI at `GET /api/tools/openapi.json`.
- **Caller identity:** service-account keys (scoped, expiring, rotatable, per-key rate limit) and OAuth resource-server mode for IdP tokens (off by default; never exercised against a live IdP). A key or IdP token never passes `require_admin`/`require_human` and cannot set a password.
- **Governance at the data layer:** collection ACL, chunk-level caller filters (`app/chunk_access.py`), SQL RLS/masking on `/queries/execute` (the catalog preview runs through it), per-caller/collection PII modes and sensitivity labels, tool-call audit (`tool_call_log`, incl. refused calls and `ai.embed`), enforced per-caller budgets (402).
- **Sovereign Core** is installed from nothing on every CI run (kind: MinIO via `pgsty/minio`, Ollama, local-only egress, embed → ingest → search).
- **Open:** OAuth-client linking UI; JWT kept in `localStorage`; a long-running self-hosted Sovereign install and the Bedrock→local provider exit drill; Aurora 15.12+ for pgvector 0.8 (live is 15.10 / 0.7.4); demand gate (design partner) by 2026-10-27. Demo walkthrough: `docs/DEMO_SCRIPT.md`.

> **Deploying to the live AWS node:** `gh workflow run deploy-aws.yml --ref main` after CI is green on that SHA (builds immutable ECR tags, rolls the node over SSM). The node runs weekdays 07:30–18:00 KST only. Fresh installs (`helm`/`scripts/install.sh`) are unaffected.
