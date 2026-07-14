# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DataPond is an **AI Data Foundation** — an AWS-native platform that fuels production RAG and agent applications on AWS. It ships the full data pipeline (S3 data → chunking → embedding → pgvector retrieval → Bedrock responses) **with governance built in** (per-collection RLS, PII masking, cost attribution, lineage), running inside the customer's own AWS account. The heavy analytics stack is delegated to AWS-managed services; DataPond's differentiating layers (governed RAG, catalog/knowledge bridge, cost governance) are open source (no lock-in).

> **Positioning history (v3.0 → v4.0 pivot):** DataPond was previously an on-prem "AI-Native Lakehouse / sovereign Databricks alternative" (self-hosted Trino/Spark/RisingWave/Polaris/SeaweedFS). That OSS full-stack is archived to the `archive/oss-lakehouse` branch (`v3.0-oss-lakehouse` tag) and remains available as optional Helm profiles, but it is **no longer the product story**. See `README.md`, `docs/PRODUCT_CONCEPT.md`, and `docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md`.

Key product positioning (v4.0 — AWS-native):
- **Target**: teams already on AWS taking AI apps (RAG, agents) from PoC to production — who need governed retrieval without hand-wiring S3 → embeddings → vector search → governance
- **Core value**: a governance-complete AI data pipeline on AWS-managed infrastructure (S3, Aurora pgvector, Bedrock) with zero ops burden
- **Differentiator**: where Bedrock Knowledge Bases gives you retrieval, DataPond adds access control, cost attribution, and catalog integration — all open source, running in your own AWS account (data sovereignty preserved)
- **Secondary**: the OSS lakehouse profiles still deploy on-prem/private-VPC for teams that need self-hosted analytics engines

## Architecture

### Layer Structure — foundation profile (live default)

The lean **foundation profile** (`values-foundation.yaml` / `values-prod-single.yaml`, 5 workloads) is the live AWS deployment. Heavy analytics is delegated to AWS-managed services, not run on the node.

```
Ingress (Traefik) + cert-manager (Let's Encrypt DNS-01 TLS)
  ↓
Application Layer: Frontend (Next.js) · Backend (FastAPI)
  ↓
AI Layer: LiteLLM (multi-model gateway → Amazon Bedrock: Claude, Titan embeddings)
  ↓
Vector/State: Aurora Serverless v2 + pgvector (RAG) · Valkey (cache/sessions)
  ↓
Storage: Amazon S3 (native, via node instance profile / IRSA)
  ↓
AWS-managed analytics (not on the node): Athena (query) · EMR (batch) ·
  Glue Data Catalog · MWAA (Airflow) · SageMaker (MLflow/Jupyter) · DataZone (lineage)
```

> The OSS full-stack (self-hosted Trino/Spark/RisingWave/Polaris/SeaweedFS/OpenMetadata/Jupyter/Airflow/MLflow/Ollama) still exists in the chart, gated behind `enabled` flags, for on-prem/full profiles (`values-onprem.yaml`). It is **off** in the foundation profile. See `docs/FOUNDATION_PROFILE.md` for the full disabled→AWS-managed mapping.

### Critical design decisions

**Storage is native S3** (foundation profile) via the node instance profile / backend IRSA — no static keys, no SeaweedFS. The `storage.provider: s3` values key selects it. (Self-hosted profiles can still use SeaweedFS/MinIO.)

**pgvector on Aurora** is the vector store — `ai_chunks(vector(1024), HNSW cosine)`. `externalDatabase.enabled: true` points the backend at the Aurora endpoint; `postgres.enabled: false`.

**Bedrock via LiteLLM** — the LiteLLM gateway maps `embed`→Titan, `chat`→Claude Sonnet, `default`→Claude Haiku, all `bedrock/...`. This is the single egress path for embeddings/RAG/AI-SQL.

**Valkey** is used instead of Redis (license-compatible drop-in replacement).

**All Deployments use `strategy: Recreate`** (not RollingUpdate) to prevent memory pressure from simultaneous old+new pods on single-node K3s. This is set in all Helm templates.

> **Full-profile only:** Apache Polaris (central Iceberg REST catalog), RisingWave (streaming SQL → Iceberg), DuckDB-in-Jupyter, and the shared-PostgreSQL multi-DB layout (`iceberg_catalog`/`openmetadata_catalog`/`polaris_catalog` auto-created via `postgres-init-configmap.yaml`) apply only when those OSS engines are enabled. In the AWS foundation profile their roles are filled by Glue / MSK-Flink / Athena / Aurora.

### Data paths (foundation profile)

- **RAG ingest**: source (text / S3 object / catalog column) → chunk + Titan embed (LiteLLM→Bedrock) → pgvector (Aurora)
- **RAG serve**: query → embed → pgvector search (+ optional rerank) → Bedrock (Claude) cited answer
- **AI SQL**: natural language → LiteLLM→Bedrock → SQL (targets Athena/Trino when an analytics engine is wired)
- **Full-profile analytics** (when enabled): Airflow→Spark→Polaris→Iceberg (batch), Trino→Polaris→Iceberg (OLAP), RisingWave→Polaris→Iceberg (streaming)

### Internal service addresses (foundation profile)

```
backend.datapond.svc.cluster.local:8000
valkey.datapond.svc.cluster.local:6379
litellm.datapond.svc.cluster.local:4000    (AI gateway → Bedrock)
# External AWS-managed:
#   Aurora Serverless v2 (pgvector)  — externalDatabase.host (terraform output)
#   Amazon S3                        — native, node instance profile
#   Amazon Bedrock                   — via LiteLLM
```

> Full-profile services (`postgres`/`seaweedfs`/`polaris`/`trino`/`spark-master`/`risingwave`/`openmetadata`/`ollama`/`mlflow` on the cluster) exist only when their `enabled` flags are set (`values-onprem.yaml`).

## Deployment

### Prerequisites

- An AWS account (foundation profile: EC2 + Aurora Serverless v2 + S3 + Bedrock + ECR)
- Terraform 1.10+ (infra in `terraform/`) · Helm 3.12+
- Single-node K3s host (m6i.xlarge+); Bedrock model access enabled in-region

### Deploy — AWS foundation (live default)

The live deployment is **single-node K3s on AWS** with external Aurora/S3/Bedrock. Infra is provisioned by `terraform/` (EC2 + EIP + Aurora + S3 + ECR + Route53 + cert-manager DNS-01). Full runbook: **`docs/DEPLOY_SINGLE_NODE.md`**.

```bash
# Foundation profile (backend/frontend/litellm/valkey + Aurora/S3/Bedrock)
helm upgrade --install datapond helm/datapond -n datapond \
  -f helm/datapond/values-prod-single.yaml \
  --set externalDatabase.host=$(terraform -chdir=terraform output -raw aurora_endpoint) \
  --set backend.image.repository=$(terraform -chdir=terraform output -raw ecr_backend_repo_url) \
  --set frontend.image.repository=$(terraform -chdir=terraform output -raw ecr_frontend_repo_url) \
  --set ingress.domain=<your-domain> \
  --wait=false
```

### Deploy — other profiles

| Profile | File | Use case |
|---------|------|----------|
| **AWS foundation (live)** | `values-prod-single.yaml` | Single-node K3s + Aurora/S3/Bedrock, 5 workloads |
| AWS foundation (generic) | `values-foundation.yaml` | Foundation defaults (S3 + Bedrock) |
| Single-node dev | `values-quicktest.yaml` | Local dev, CI — LiteLLM/Ollama disabled |
| On-prem full (OSS) | `values-onprem.yaml` | Self-hosted full lakehouse (Trino/Spark/Polaris/…), 32 GB+ |

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

**Foundation profile (live):** the UI capability-gates to what's deployed — Dashboard · Knowledge (RAG) · AI · Governance · Storage · Settings. Lakehouse pages (Catalog/Query/Connectors/Pipelines/Streaming/Notebooks/Experiments/Lineage) are hidden unless the corresponding OSS engines are enabled (`GET /api/capabilities`).

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend (Management UI) | `https://<your-domain>` | admin / (generated; see runbook) |
| Backend API + Docs | `https://<your-domain>/api` | — |

> **Full-profile only (OSS on-prem):** JupyterLab (`/jupyter`), Airflow (`/airflow`), MLflow (`/mlflow`), OpenMetadata (`/openmetadata`), SeaweedFS console (`/seaweedfs-console`) exist only when those workloads are enabled in `values-onprem.yaml`.
> **Note (full-profile):** Spark runs as a standalone master+worker via explicit `spark-class` commands on the `apache/spark` image (the old bitnami-style `SPARK_MODE` env never worked on that image). Iceberg/Polaris/S3 job config is in the `spark-defaults` ConfigMap.
> **Note (full-profile):** Airflow Webserver uses `BASE_URL=/airflow` and `AUTH_BACKENDS=basic_auth,session` — the REST API is at `/airflow/api/v1` internally.

## Helm Chart Structure

```
helm/datapond/
  values.yaml               # Base defaults
  values-foundation.yaml    # AWS AI Data Foundation — 5 workloads, S3 + Bedrock
  values-prod-single.yaml   # Live: single-node K3s on AWS + external Aurora/S3/Bedrock + TLS
  values-quicktest.yaml     # Single-node dev/test (Recreate strategy, 1 replica)
  values-onprem.yaml        # OSS full stack (self-hosted Trino/Spark/Polaris/…), 32GB+
  values-aws.yaml           # AWS EKS profile
  Chart.yaml
  templates/
    postgres-init-configmap.yaml  # Full-profile: auto-creates DBs on first startup
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
| `README.md` | Product overview — AWS-native AI Data Foundation (v4.0) |
| `docs/PRODUCT_CONCEPT.md` | Product strategy, positioning, competitive analysis (v4.0-aws-pivot) |
| `docs/FOUNDATION_PROFILE.md` | The lean foundation profile — 5 workloads + disabled→AWS-managed mapping |
| `docs/DEPLOY_SINGLE_NODE.md` | Live deployment runbook — single-node K3s on AWS (EC2+Aurora+S3+Bedrock) |
| `docs/AWS_MVP_RUNBOOK.md` | End-to-end Bedrock RAG on S3 + Aurora pgvector; secrets handling |
| `docs/AWS_BEDROCK_SETUP.md` | LiteLLM ↔ Bedrock credential wiring + model config |
| `docs/DISASTER_RECOVERY.md` | DR runbook — Aurora PITR, S3 versioning, Secrets Manager re-seed |
| `docs/superpowers/specs/2026-06-30-aws-ai-data-platform-pivot-design.md` | Source-of-truth pivot design spec (v3.0→v4.0) |

> The v3.0 OSS lakehouse docs (ARCHITECTURE / DATABRICKS_FEATURE_COMPARISON / LITELLM_INTEGRATION / RISINGWAVE_INTEGRATION / OPENMETADATA_INTEGRATION / TROUBLESHOOTING / INSTALLATION / SPRINT_PLAN) were archived to the `archive/oss-lakehouse` branch — see `ARCHIVE.md`.

## Current Status

> **Current direction (v4.0, 2026-07):** AWS-native **AI Data Foundation** — live on single-node K3s on AWS (EC2 + Aurora pgvector + S3 + Bedrock), foundation profile (5 workloads), real-domain TLS, passkey/WebAuthn auth. The completed-work log below (through the 2026-06 Sprint work) is the history that built up to the pivot; items referencing self-hosted SeaweedFS/Ollama/Trino/Polaris pertain to the OSS full profiles, not the live AWS foundation.

### Sprint 1: Ingestion (완료)
- ✅ Incremental Sync: watermark 기반, max_value DB 저장, 빈 결과 시 덮어쓰기 방지
- ✅ Schema Evolution: append 모드에서 `ALTER TABLE ADD COLUMN` 자동 실행
- ✅ ELT Transform UI: Pipelines 페이지 SQL Editor + Source/Target namespace + Airflow CTAS DAG 생성
- ✅ CDC: RisingWave postgres-cdc (Streaming 탭 4단계 마법사)

### Sprint 2: 분석 & 품질 (완료)
- ✅ Catalog 데이터 미리보기: Preview 탭, 상위 100 rows, 컬럼 통계 (null rate, distinct count, min/max)
- ✅ Dashboard 인라인 미니 차트: 목록 카드에 실시간 쿼리 + Recharts 렌더링
- ✅ Data Quality: sync 후 row count 이상(±20% warn, ±50% alert) + null rate 체크, connector_quality_checks 테이블
- ✅ AI SQL Assistant: LiteLLM → Bedrock → Anthropic fallback chain, Query Lab 자연어 입력

### 완성도 개선 (완료)
- ✅ Notebook view 실제 JupyterLab API 연동 (mock 제거)
- ✅ Services 로그 뷰어: pod-specific 로그, 선택한 pod 배너 표시
- ✅ Experiment run 비교: MLflow compare API, metrics/params 비교 테이블 (best 값 ★ 표시)
- ✅ OpenMetadata lineage: sync 완료 후 best-effort 등록, pipelines lineage/quality 엔드포인트 실제 OM API 호출
- ✅ Per-table sync mode 편집: 테이블별 sync_mode/incremental_column 인라인 편집
- ✅ 실제 K8s metrics: kubectl top 기반 CPU/Memory 실시간 조회

### 인프라 & 안정성 (완료)
- ✅ PostgreSQL: Headless(postgres-headless) + ClusterIP(postgres) 분리로 Pod 재시작 시 안정성 확보
- ✅ SeaweedFS: initContainer로 master/filer 준비 대기, liveness probe 조정
- ✅ HPA maxReplicas: 5→2 (단일 노드 메모리 부족 방지)
- ✅ POSTGRES_PORT 버그: K8s 자동 주입 `tcp://...` 파싱 오류 수정
- ✅ DATABASE_URL env 순서 버그 수정
- ✅ Airflow trino_default connection 자동 업데이트 (Transform 배포 시)

### AI 아키텍처 (완료)
- ✅ LiteLLM Helm template: ConfigMap(model_list) + Deployment + Service
- ✅ Ollama Helm template: StatefulSet + initContainer(모델 auto-pull) + PVC
- ✅ AI Provider 우선순위 체인: LiteLLM(내부) → Bedrock(AWS) → Anthropic → 스키마 템플릿
- ✅ values-onprem.yaml: 완전한 온프레미스 프로파일 (SeaweedFS, Ollama, LiteLLM, 32GB+ 노드)
- ✅ values-aws.yaml: EKS + S3 + Bedrock 프로파일
- ✅ Settings UI → System → AI SQL Assistant: provider/URL/key 설정
- ✅ System Settings API: DB 저장 + 암호화(CredentialVault) + startup 복원

### 2026-06 업데이트 — AI 플랫폼·RAG·거버넌스·안정성 (완료)
**Vector/RAG (AI 데이터 플랫폼)**
- ✅ pgvector 벡터스토어 + RAG: `ai_collections`/`ai_chunks(vector(1024), HNSW)`, Knowledge UI(사이드바 Analyze→Knowledge), 텍스트/lakehouse/S3 적재
- ✅ AI 데이터 파이프라인: `ingest-source`(iceberg 테이블 컬럼 / S3 객체) + Airflow `schedule`(주기 재임베딩 DAG)
- ✅ 컬렉션별 RLS: `ai_collections.owner_id`, 소유자/admin 게이트, 공용(owner NULL) 전사 노출, 삭제는 owner/admin (#52/#57)
- ✅ Ingestion→RAG 브릿지: Knowledge Ingest 카탈로그 드롭다운(schema/table/column) + Catalog 'Send to Knowledge'(✨) 다이얼로그 (#71)
- ✅ Bedrock E2E 검증: Titan 임베딩 → pgvector → 검색 → Claude RAG 인용답변 (라이브)

**외부 LLM 거버넌스 (LiteLLM 활용)**
- ✅ 토큰/비용 대시보드 + 날짜범위 Spend report + 예산 알림 배너 (Settings→AI) (#53~56)
- ✅ 모델 폴백(router fallbacks) — 단일모델 SPOF 제거, `litellm.fallbacks` (#62, 라이브 mock_testing_fallbacks 검증)
- ✅ 사용자별 비용 귀속(per-user spend) — chat/embed payload에 `user`/metadata, usage `users[]` 집계 (#63)
- ✅ 관측성 배선 — `/metrics` prometheus scrape 어노테이션 + Langfuse 트레이싱 opt-in (#64)
- ✅ 가드레일 전 경로 — 한국 PII(`pii_ko`)를 RAG/search/sql/ingest에 적용 + 게이트웨이 Presidio passthrough opt-in (#54)
- ✅ RAG rerank opt-in — `AI_RERANK_MODEL` 설정 시 `/v1/rerank` 재정렬 (#65)

**데이터계층 안정성**
- ✅ SeaweedFS durability: master/volume/filer를 `/data` PVC에 영속(`-mdir/-dir/-defaultStoreDir`) — /tmp 휘발 손상 근본수정 (#49)
- ✅ Iceberg DROP 복구: Polaris `DROP_WITH_PURGE_ENABLED` 활성 — CREATE/INSERT/SELECT/DROP 전 라이프사이클 라이브 동작 (#58)
- ✅ 무거운 sync를 `asyncio.to_thread` + 관대한 liveness probe로 이벤트루프 보호 (#49/#50)
- ✅ Catalog 트리 성능: `/catalog/schemas` 지연 컬럼 로딩(37s 504 → 0.3s) + `/catalog/columns` on-demand (#70)

**보안/인증/재현성**
- ✅ Row-Level Security 엔진: 정책관리·Trino 네이티브·DuckDB 가드 (P0~P4, #13)
- ✅ LDAP/AD 인증(환경설정, 기본 OFF, 로컬 admin 항상 동작) (#41)
- ✅ 예약 DAG 인증: 내부 서비스 키 `X-Internal-Key`(`require_user_or_internal`) — 무인증 콜백 401 해소 (#61)
- ✅ 기반 스키마 부트스트랩: `auth.sql`/`queries.sql` git 추적 + startup 멱등 적용(센티넬 가드) — 신규/에어갭 설치 재현성 (#60)
- ✅ AI SQL 응답 파서 견고화: 제어문자/프로즈/이중래핑 JSON/plain-SQL salvage (#66~69)
- ✅ 에어갭 번들 검증: jupyter 커스텀 이미지 빌드 추가 + datapond 이미지 `:latest` 통일(전 프로파일 동작) (#59)

### 새로 추가된 DB 테이블
- `connector_quality_checks`: Data Quality 결과 저장
- `saved_transforms`: ELT Transform 정의 저장
- `system_settings`: 시스템 설정 (암호화 저장)
- `ai_collections` / `ai_chunks`: pgvector 컬렉션·청크(embedding vector(1024), HNSW cosine). `ai_collections.owner_id`로 컬렉션 RLS
- `rls_policies` / `column_masking_policies` / `user_roles` 등: RLS 엔진 스키마 (rls_migration.sql)

### 새로 추가된 API 엔드포인트
- `POST /api/ai/sql`: 자연어 → Trino SQL (LiteLLM 게이트웨이 단일 경로 + egress 가드)
- `GET/PATCH /api/settings/system`: 시스템 설정 CRUD
- `GET /api/settings/system/ai`: AI 설정 조회
- `GET /api/connectors/{id}/quality`: Data Quality 결과
- `POST /api/transforms`: ELT Transform CRUD
- `GET /api/catalog/tables/{namespace}/{table}/preview`: 데이터 미리보기 + 컬럼 통계
- `GET /api/catalog/schemas?columns=false`: 카탈로그 트리(지연 컬럼) · `GET /api/catalog/columns`: 테이블 컬럼 on-demand
- **Vector/RAG**: `POST /api/ai/embed`, `GET/POST/DELETE /api/ai/collections`, `POST /api/ai/collections/{name}/{ingest,ingest-source,schedule}`, `POST /api/ai/search`, `POST /api/ai/rag`
- **AI 거버넌스**: `GET /api/settings/ai/{usage,spend/report,budget-alerts}`, `/api/settings/ai/{providers,status,backends,active,keys}`, `/backends/{name}/test`
- 내부 자동화 인증: 신뢰된 in-cluster 호출은 `X-Internal-Key`(=`INTERNAL_API_KEY`)로 `require_user_or_internal` 엔드포인트(`/ingest-source`) 접근

### 미완성 항목
- ✅ ~~Row-level security~~ — 완료 (엔진 #13 + 컬렉션 RLS #52/#57)
- ✅ ~~LDAP 연동~~ — 완료 (#41). ✅ ~~SSO OIDC~~ — 완료 (enterprise 이미지, /ee). ✅ ~~Passkey/WebAuthn~~ — 완료 (passwordless). SAML은 미구현
- ✅ ~~에어갭 설치 패키지~~ — 구성요소 검증 완료 (#59). *(OSS 온프렘 프로파일 한정; AWS 파운데이션은 ECR pull 기반)*
- ✅ ~~Iceberg VACUUM DAG~~ — startup `deploy_maintenance_dag()`로 유지보수 DAG 배포 *(full-profile Airflow 한정)*
- ✅ ~~**자동 신선도(AI Data Foundation 핵심)**~~ — 완료: 백엔드 인프로세스 재임베딩 스케줄러(`backend/app/rag_scheduler.py`, pg advisory-lock으로 replica 중복 방지, interval 기반). Airflow DAG 경로 제거, append→replace(`ai_chunks.source_group`) 버그 수정. `RAG_SCHEDULER_ENABLED`/`TICK_SECONDS` env
- [ ] 커넥터 RAG sink(소스 변경 시 자동 재임베딩), 모니터링 스택(Prometheus/Grafana)·Langfuse 실배포(차트 opt-in만)
- [ ] (deprioritized) 주권 AI(onprem local-only + Ollama) 실증 — v3.0 OSS 방향, AWS-native 전환으로 우선순위 하향

> **배포 주의 (AWS 라이브):** 라이브는 단일 EC2(K3s) + SSM tar-sync 파이프라인으로 운영되며 `/home/ubuntu/datapond`는 풀 체크아웃이 아님 — 새 런타임 파일(라우트/스키마/설정)을 추가하면 배포 시 전체 소스를 동기화해야 이미지에 포함됨. 정식 신규설치(helm/install.sh)는 무관.
