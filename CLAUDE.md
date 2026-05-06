# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DataPond is an **AI-Native Lakehouse Platform** targeting on-premises and private cloud environments where Databricks cannot operate. It is positioned as an enterprise-grade product — not as a budget alternative — with AI as a first-class architectural concern. The primary differentiator is enabling organizations with strict data sovereignty requirements (regulated industries, air-gapped environments, private infrastructure) to run a full Databricks-class lakehouse on their own infrastructure.

Key product positioning (critical — do not revert):
- **Target**: Organizations that **cannot use Databricks** due to regulatory, air-gap, or data sovereignty requirements — financial institutions (FSS regulations), public sector (network isolation mandates), healthcare (EMR data residency), defense, manufacturing (OT network separation)
- **NOT** "cheap Databricks alternative" — price is not the differentiator
- **NOT** open-source community play — no public GitHub launch planned currently
- **Unique position**: Databricks is SaaS-only and cannot enter this market; DataPond is the enterprise-grade AI-Native Lakehouse for sovereign infrastructure

## Architecture

### Layer Structure (top to bottom)

```
Ingress (Traefik/Nginx)
  ↓
Application Layer: Frontend (Next.js) · Backend (FastAPI) · JupyterLab · Airflow · MLflow
  ↓
Compute Layer: Trino (OLAP SQL) · Spark (batch) · RisingWave (streaming SQL)
  ↓
Catalog & Governance: Apache Polaris REST Catalog (Unity Catalog equivalent)
  ↓
Storage Layer: SeaweedFS (S3-compatible) + Apache Iceberg (ACID table format)
  ↓
Metadata/State: PostgreSQL (primary DB for all services) · Valkey (cache/sessions)
  ↓
Observability: OpenMetadata (lineage, catalog, data quality)
  ↓
AI Layer: LiteLLM (multi-model proxy: Claude, GPT-4, Gemini, Llama)
```

### Critical design decisions

**Apache Polaris** (port 8181) is the central catalog — all compute engines (Trino, Spark, RisingWave) connect via REST to the same Iceberg catalog. This enables cross-engine table sharing and RBAC at the catalog level. Polaris stores metadata in PostgreSQL and data in SeaweedFS.

**RisingWave** (port 4566, PostgreSQL wire protocol) replaces the Kafka + Spark Streaming combination. It processes streams with PostgreSQL-compatible SQL and sinks directly to Iceberg tables via Polaris.

**DuckDB** runs embedded inside JupyterLab (no separate pod). It reads Iceberg tables directly from SeaweedFS via S3 API — no Spark cluster needed for exploratory queries under ~100GB.

**PostgreSQL** is shared across services: `datapond` (app data), `mlflow` (experiment metadata), `airflow` (workflow metadata), `iceberg_catalog` (Polaris metastore), `openmetadata_catalog`, `polaris_catalog`. All databases are auto-created on first PostgreSQL startup via `/docker-entrypoint-initdb.d/01-init-databases.sh` (mounted from `postgres-init-configmap.yaml`).

**Valkey** is used instead of Redis (license-compatible drop-in replacement).

**All Deployments use `strategy: Recreate`** (not RollingUpdate) to prevent memory pressure from simultaneous old+new pods on single-node K3s. This is set in all Helm templates.

### Data paths

- **Real-time**: Kafka/Kinesis → RisingWave → Polaris → Iceberg (SeaweedFS)
- **Batch**: Airflow DAG → Spark → Polaris → Iceberg (SeaweedFS)
- **Analytics**: Trino → Polaris (auth check) → Iceberg (SeaweedFS)
- **DS/exploration**: JupyterLab → DuckDB → Iceberg direct S3 read
- **Lineage**: All services → OpenMetadata (automatic collection)

### Internal service addresses

```
backend.datapond.svc.cluster.local:8000
postgres.datapond.svc.cluster.local:5432
valkey.datapond.svc.cluster.local:6379
seaweedfs.datapond.svc.cluster.local:9000
polaris.datapond.svc.cluster.local:8181
trino.datapond.svc.cluster.local:8080
spark-master.datapond.svc.cluster.local:7077
risingwave.datapond.svc.cluster.local:4566
openmetadata.datapond.svc.cluster.local:8585
litellm.datapond.svc.cluster.local:4000
mlflow.datapond.svc.cluster.local:5000
```

## Deployment

### Prerequisites

- Kubernetes 1.25+ (K3s recommended for on-prem)
- Helm 3.12+
- 8GB+ RAM (dev), 32GB+ RAM (prod)

### Install K3s + Helm (on-prem bootstrap)

```bash
# Full install (interactive, handles K3s + Helm + deploy)
sudo bash scripts/install.sh --domain datapond.local

# Air-gapped environment
sudo bash scripts/bundle-airgap.sh          # on internet machine
sudo bash datapond-airgap-*/install.sh       # on target machine
```

### Deploy / upgrade

```bash
# Upgrade existing release (recommended — always use values-quicktest.yaml on single node)
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-quicktest.yaml \
  --wait=false

# Production
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-prod.yaml \
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

## Key URLs (dev)

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend (Management UI) | http://datapond.local | — |
| Backend API + Docs | http://datapond.local/api | — |
| JupyterLab | http://datapond.local/jupyter | token: `jupyter` |
| Airflow | http://datapond.local/airflow | airflow / airflow |
| MLflow | http://datapond.local/mlflow | — |
| OpenMetadata | http://datapond.local/openmetadata | — |
| SeaweedFS Console | http://datapond.local/seaweedfs-console | — |

> **Note:** Spark is currently disabled (`spark.enabled: false` in values-quicktest.yaml) due to image issues.
> **Note:** Airflow Webserver uses `BASE_URL=/airflow` and `AUTH_BACKENDS=basic_auth,session` — the REST API is at `/airflow/api/v1` internally.

## Helm Chart Structure

```
helm/datapond/
  values.yaml            # Base defaults (HA, production scale)
  values-quicktest.yaml  # Single-node dev/test (Recreate strategy, 1 replica)
  values-dev.yaml        # Dev overrides
  values-prod.yaml       # Production (HA, full resources)
  Chart.yaml             # v2.3.0
  templates/
    postgres-init-configmap.yaml  # Auto-creates all DBs on first startup
    *-deployment.yaml             # All use strategy: Recreate
```

When adding a new component: add `enabled` flag, `image`, `replicas`, `resources`, `strategy: Recreate` to template, and mount `postgres-init-configmap` if DB needed.

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
| **PM Agent** | Opus 4.7 | `model: "opus"` | Project leadership, strategy, coordination | `pm-agent.md` |
| **Architecture Agent** | Opus 4.7 | `model: "opus"` | System design, tech decisions, ADRs | `architecture-agent.md` |
| **ML Consultant Agent** | Opus 4.7 | `model: "opus"` | ML strategy, data science workflows | `ml-consultant-agent.md` |
| **Backend Agent** | Sonnet 4.6 | `model: "sonnet"` | FastAPI, database, API implementation | `backend-agent.md` |
| **Frontend Agent** | Sonnet 4.6 | `model: "sonnet"` | Next.js, React, UI implementation | `frontend-agent.md` |
| **Design Agent** | Sonnet 4.6 | `model: "sonnet"` | UI/UX design, design system | `design-agent.md` |
| **DevOps Agent** | Sonnet 4.6 | `model: "sonnet"` | Kubernetes, Docker, CI/CD | `devops-agent.md` |
| **Error Correction Agent** | Sonnet 4.6 | `model: "sonnet"` | Debugging, error fixes, quality assurance | `error-correction-agent.md` |
| **Technical Writer Agent** | Sonnet 4.6 | `model: "sonnet"` | Documentation, help guides, user manuals | `technical-writer-agent.md` |

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
1. Reads frontend-agent.md (model: claude-sonnet-4-6)
2. Reads design-agent.md (model: claude-sonnet-4-6)
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
| `docs/ARCHITECTURE.md` | Full component specs, resource sizing, HA config |
| `docs/PRODUCT_CONCEPT.md` | Product strategy, positioning, roadmap |
| `docs/DATABRICKS_FEATURE_COMPARISON.md` | Feature parity analysis |
| `docs/LITELLM_INTEGRATION.md` | AI assistant configuration |
| `docs/RISINGWAVE_INTEGRATION.md` | Streaming SQL setup |
| `docs/OPENMETADATA_INTEGRATION.md` | Lineage and catalog setup |
| `docs/TROUBLESHOOTING.md` | Common failure modes |
| `docs/INSTALLATION.md` | Detailed install guide |
