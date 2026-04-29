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

**PostgreSQL** is shared across services: `datapond` (app data), `mlflow` (experiment metadata), `airflow` (workflow metadata), `iceberg_catalog` (Polaris metastore).

**Valkey** is used instead of Redis (license-compatible drop-in replacement).

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
sudo bash scripts/install-k3s.sh
echo "127.0.0.1  datapond.local" | sudo tee -a /etc/hosts
```

### Deploy / upgrade

```bash
# First install (dev)
bash scripts/deploy.sh values-dev.yaml

# Upgrade existing release
bash scripts/deploy.sh values-dev.yaml
# (script detects existing release and prompts for upgrade)

# Production
bash scripts/deploy.sh values-prod.yaml
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

| Service | URL |
|---------|-----|
| Frontend | http://datapond.local |
| Backend API | http://datapond.local/api |
| JupyterLab | http://datapond.local/jupyter (token: `jupyter`) |
| Airflow | http://datapond.local/airflow (airflow/airflow) |
| MLflow | http://datapond.local/mlflow |
| Spark UI | http://datapond.local/spark |
| SeaweedFS Console | http://datapond.local/seaweedfs-console |

## Helm Chart Structure

```
helm/datapond/
  values.yaml          # Base defaults (all services)
  values-dev.yaml      # Dev overrides (minimal resources, 1 replica)
  values-prod.yaml     # Prod overrides (HA, full resources)
  values-quicktest.yaml
  Chart.yaml
```

When adding a new component, follow the existing pattern in `values.yaml`: enabled flag, image, replicas, resources (requests + limits), service ports, autoscaling config.

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

| Agent | Model | Specialization | File |
|-------|-------|----------------|------|
| **PM Agent** | Opus 4.7 | Project leadership, strategy, coordination | `pm-agent.md` |
| **Architecture Agent** | Opus 4.7 | System design, tech decisions, ADRs | `architecture-agent.md` |
| **ML Consultant Agent** | Opus 4.7 | ML strategy, data science workflows | `ml-consultant-agent.md` |
| **Backend Agent** | Sonnet 4.6 | FastAPI, database, API implementation | `backend-agent.md` |
| **Frontend Agent** | Sonnet 4.6 | Next.js, React, UI implementation | `frontend-agent.md` |
| **Design Agent** | Sonnet 4.6 | UI/UX design, design system | `design-agent.md` |
| **DevOps Agent** | Sonnet 4.6 | Kubernetes, Docker, CI/CD | `devops-agent.md` |

### How to Use Agents

**When you need coordinated multi-agent work:**
```
User: "shadcn/ui 기반으로 통합 관리 UI를 만들어줘"

Claude will:
1. Read pm-agent.md to understand PM responsibilities
2. Read relevant specialist agents (frontend-agent.md, design-agent.md, backend-agent.md)
3. Coordinate implementation across agents
4. Ensure consistency with project architecture and standards
```

**Agent Workflow:**
```
User Request → Main Claude (reads pm-agent.md)
                      ↓
            PM Agent Analysis & Planning
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
  Architecture    Backend      Frontend
  Agent Context   Agent        Agent
  (design review) (API impl)   (UI impl)
                      ↓
            Integration & Deployment
```

**Direct Agent Reference:**
When Claude needs specialized knowledge, it will:
1. Read the relevant agent file from `.claude/agents/`
2. Apply that agent's expertise and guidelines
3. Follow that agent's code standards and practices
4. Report back with agent-appropriate recommendations

See `.claude/AGENT_TEAM_GUIDE.md` for detailed coordination workflow and best practices.

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
