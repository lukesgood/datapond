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
litellm.datapond.svc.cluster.local:4000    (AI proxy — disabled on values-quicktest)
ollama.datapond.svc.cluster.local:11434    (LLM runtime — disabled on values-quicktest)
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

Three values profiles are available depending on the environment:

| Profile | File | RAM | Use case |
|---------|------|-----|----------|
| Single-node dev | `values-quicktest.yaml` | 15 GB | Local dev, CI — LiteLLM/Ollama disabled |
| On-prem production | `values-onprem.yaml` | 32 GB+ | Full stack incl. LiteLLM + Ollama |
| AWS EKS | `values-aws.yaml` | — | S3 + Bedrock, no SeaweedFS/Ollama/PG |

```bash
# Single-node dev (current default)
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-quicktest.yaml \
  --wait=false

# On-prem production (all services, LiteLLM + Ollama)
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-onprem.yaml \
  --wait=false

# AWS EKS (S3 + Bedrock)
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-aws.yaml \
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

> **Note:** Spark runs as a standalone master+worker via explicit `spark-class` commands on the `apache/spark` image (the old bitnami-style `SPARK_MODE` env never worked on that image). Enabled in `values-onprem.yaml` (32GB+); disabled in `values-quicktest.yaml` for memory. Iceberg/Polaris/S3 job config is in the `spark-defaults` ConfigMap. Air-gap still needs the Iceberg/S3 jars baked into a custom image (`spark.jars.packages` resolves from Maven at submit time).
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
| `docs/ARCHITECTURE.md` | Full component specs, AI layer, multi-env profiles |
| `docs/PRODUCT_CONCEPT.md` | Product strategy, positioning, roadmap |
| `docs/DATABRICKS_FEATURE_COMPARISON.md` | Feature parity analysis (updated 2026-05-11) |
| `docs/LITELLM_INTEGRATION.md` | AI assistant config — LiteLLM + Ollama + Bedrock |
| `docs/RISINGWAVE_INTEGRATION.md` | Streaming SQL setup (CDC) |
| `docs/OPENMETADATA_INTEGRATION.md` | Lineage and catalog setup |
| `docs/TROUBLESHOOTING.md` | Common failure modes incl. POSTGRES_PORT, SeaweedFS |
| `docs/INSTALLATION.md` | Detailed install guide (quicktest/onprem/aws profiles) |
| `docs/SPRINT_PLAN.md` | Sprint 진행 현황 및 완료 항목 |

## Current Status (2026-06-09)

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
- ✅ ~~LDAP 연동~~ — 완료 (#41). SSO(SAML/OIDC)는 미구현
- ✅ ~~에어갭 설치 패키지 (bundle-airgap.sh 검증)~~ — 구성요소 검증 완료 (#59). **단절 호스트 클린룸 E2E + Ollama 모델 blob 번들은 미수행**
- ✅ ~~Iceberg VACUUM DAG~~ — startup `deploy_maintenance_dag()`로 유지보수 DAG 배포
- [ ] 주권 AI 실증: onprem `local-only` + Ollama로 외부 egress 없는 RAG 라이브 시연 (메커니즘 구현 완료, 라이브는 cloud-allowed+Bedrock 운영 중)
- [ ] SSO(SAML/OIDC), 모니터링 스택(Prometheus/Grafana)·Langfuse 실배포(차트 opt-in만), 커넥터 RAG sink(자동 재임베딩)

> **배포 주의 (AWS 라이브):** 라이브는 단일 EC2(K3s) + SSM tar-sync 파이프라인으로 운영되며 `/home/ubuntu/datapond`는 풀 체크아웃이 아님 — 새 런타임 파일(라우트/스키마/설정)을 추가하면 배포 시 전체 소스를 동기화해야 이미지에 포함됨. 정식 신규설치(helm/install.sh)는 무관.
