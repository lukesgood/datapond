# DataPond — AI-Native Lakehouse for Sovereign Infrastructure

**Databricks가 진입할 수 없는 온프렘·에어갭 환경을 위한 엔터프라이즈 AI 데이터 플랫폼**

**Last Updated:** 2026-05-04 | **Version:** 2.3.0

[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.25+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Helm](https://img.shields.io/badge/Helm-3.12+-0F1689?logo=helm&logoColor=white)](https://helm.sh/)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js_16-black?logo=next.js)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Apache Iceberg](https://img.shields.io/badge/Table_Format-Apache_Iceberg-blue)](https://iceberg.apache.org/)

---

## 왜 DataPond인가?

Databricks는 클라우드 SaaS 전용 제품입니다. 다음 환경의 조직들은 Databricks를 도입할 수 없습니다:

| 산업 | 규제·제약 |
|------|----------|
| 🏦 금융 | 금감원 망분리 의무, 고객 데이터 외부 반출 금지 |
| 🏛️ 공공·국방 | 에어갭 네트워크, 국정원 CC 인증 요건 |
| 🏥 의료·바이오 | EMR 외부 전송 금지, 개인정보보호법 |
| 🏭 제조·에너지 | OT 망 분리, 산업 기밀 보호 |

DataPond는 이 조직들이 **자체 인프라 위에서** Databricks 수준의 AI 데이터 플랫폼을 운영할 수 있게 합니다. AI는 부가기능이 아니라 1급 설계 요소입니다 — 자연어 SQL·RAG·벡터 검색이 **LiteLLM 단일 게이트웨이를 통해 egress 정책(주권 모드 = 외부 무유출)·PII 가드레일·비용 거버넌스 아래에서** 동작합니다.

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    Ingress (Traefik)                             │
├──────────┬──────────┬──────────┬──────────┬────────────────────┤
│ Frontend │ Backend  │JupyterLab│ Airflow  │     MLflow         │
│(Next.js) │(FastAPI) │          │          │                    │
├──────────┴──────────┴──────────┴──────────┴────────────────────┤
│         Compute: Trino (OLAP) · RisingWave (Streaming SQL)     │
├─────────────────────────────────────────────────────────────────┤
│         Catalog: Apache Polaris (Iceberg REST Catalog)         │
├─────────────────────────────────────────────────────────────────┤
│    Storage: SeaweedFS (S3-compatible) + Apache Iceberg         │
├─────────────────────────────────────────────────────────────────┤
│    Metadata: PostgreSQL (shared) · Valkey (cache/session)       │
├─────────────────────────────────────────────────────────────────┤
│    Observability: OpenMetadata (lineage · catalog · quality)    │
└─────────────────────────────────────────────────────────────────┘
```

**PostgreSQL 공유 DB 구조** — 서비스별 독립 데이터베이스, 초기 설치 시 자동 생성:
`datapond` · `mlflow` · `airflow` · `polaris_catalog` · `iceberg_catalog` · `openmetadata_catalog`

### 데이터 경로

| 경로 | 흐름 |
|------|------|
| 실시간 | Kafka/Kinesis → RisingWave → Polaris → Iceberg |
| 배치 | Airflow DAG → Trino → Polaris → Iceberg |
| 분석 | SQL Lab (Trino) → Polaris → Iceberg |
| 탐색 | JupyterLab → DuckDB → Iceberg direct S3 |
| 실험 | Notebook / SQL Lab → MLflow → S3 artifacts |
| AI/RAG | Knowledge / Catalog → LiteLLM(임베딩) → pgvector → 검색·RAG(LiteLLM chat) |
| 자연어 SQL | SQL Lab 질문 → LiteLLM(egress 가드·PII 가드레일) → Trino SQL |

---

## 플랫폼 서비스 (v2.3.0 — 전체 Running)

| 서비스 | 역할 | 접근 |
|--------|------|------|
| **Frontend** | 통합 관리 UI (Next.js 16) | http://datapond.local |
| **Backend** | REST API (FastAPI) | http://datapond.local/api |
| **JupyterLab** | 데이터 과학 노트북 | http://datapond.local/jupyter |
| **MLflow** | ML 실험 추적·모델 레지스트리 | http://datapond.local/mlflow |
| **Airflow** | 워크플로우 오케스트레이션 | http://datapond.local/airflow |
| **OpenMetadata** | 데이터 카탈로그·리니지 | http://datapond.local/openmetadata |
| **SeaweedFS** | S3 호환 오브젝트 스토리지 | http://datapond.local/seaweedfs-console |
| **Trino** | 분산 SQL 쿼리 엔진 | 내부 (SQL Lab에서 사용) |
| **RisingWave** | 스트리밍 SQL (PostgreSQL wire) | 내부 (port 4566) |
| **Apache Polaris** | Iceberg REST Catalog | 내부 (port 8181) |
| **LiteLLM** | AI 게이트웨이 (멀티 프로바이더 · 비용/키/폴백/가드레일 통합) | 내부 (port 4000) |
| **Ollama** | 로컬 LLM 런타임 (주권/에어갭, onprem 프로파일) | 내부 (port 11434) |
| **PostgreSQL** | 공유 메타데이터 DB + **pgvector** 벡터스토어 | 내부 (port 5432) |
| **Valkey** | Redis 호환 캐시 (응답 캐싱·카탈로그 캐시) | 내부 (port 6379) |

---

## 관리 UI 기능 (v2.3.0)

### Dashboard (`/dashboard`)
- 전체 서비스 상태 실시간 모니터링 (30초 자동 갱신)
- CPU·메모리 사용률 차트
- 서비스 health 카드 (healthy / unhealthy / unknown)

### SQL Lab (`/query`)
- Monaco 에디터 (SQL 문법 강조, `Ctrl+Enter` / `Cmd+Enter` 실행)
- Trino 연결, 세미콜론 자동 제거, 자동 LIMIT 1000 보호
- 스키마 브라우저: 드래그 리사이즈, 컬럼 타입 뱃지, 시스템 스키마 토글
- 결과 테이블: 타입 감지(숫자·날짜·불린), sticky 헤더, Copy TSV, CSV 내보내기
- 5가지 차트 (Table·Line·Bar·Area·Pie) + 차트 설정 패널
- 쿼리 히스토리: 백엔드 저장, 검색, 즐겨찾기
- **"Log to MLflow"** — 쿼리 결과를 MLflow 실험 런으로 직접 기록 (params/metrics 커스텀 추가 가능)
- **"Save Dashboard"** — 차트를 대시보드로 저장
- **AI SQL Assistant** — 자연어 질문 → Trino SQL (LiteLLM 게이트웨이, PII 가드레일·egress 정책 적용)
- 스키마 트리는 컬럼을 지연 로딩(테이블 확장 시 on-demand) — 대규모 카탈로그에서도 즉시 로드

### ML Experiments (`/experiments`)
- 3-컬럼 네이티브 UI: 실험 목록 → 런 테이블 → 런 상세
- 런 상태 배지: FINISHED·RUNNING·FAILED·KILLED
- Metrics 시각화: step 기반 Recharts 라인차트, scalar 테이블
- 멀티 런 비교: 체크박스 선택 → 피벗 테이블, 최적값 하이라이트
- New Experiment 생성 다이얼로그
- **Query Lab 연동**: SQL 결과 → MLflow 런 1-클릭 기록

### Data Pipelines (`/pipelines`)
- Airflow DAG 목록·상태 실시간 조회 (30초 갱신)
- DAG 트리거, 일시정지·재개 제어
- 런 히스토리 및 태스크 상세·로그

### Data Catalog (`/catalog`)
- Apache Polaris / Iceberg 테이블 탐색
- 네임스페이스·테이블·컬럼·파티션 상세, 데이터 미리보기 + 컬럼 통계
- **"Send to Knowledge"** (✨) — 테이블 텍스트 컬럼을 RAG 컬렉션으로 한 번에 적재 / 예약

### Knowledge (`/knowledge`) — Vector / RAG
- pgvector 기반 벡터 컬렉션 생성·관리 (컬렉션별 RLS: 소유자·admin·공용)
- 적재: 텍스트 붙여넣기 / 레이크하우스(Iceberg 테이블 컬럼) / S3 객체 — 카탈로그 드롭다운으로 소스 선택
- **Search / RAG**: 시맨틱 검색 또는 출처 인용 답변 (임베딩·chat 모두 LiteLLM 경유 = egress 정책 적용)
- **예약 적재**: Airflow DAG로 소스를 주기적으로 재임베딩 (AI 데이터 파이프라인)
- PII 가드레일(질의·문서 마스킹) 표시

### Notebooks (`/notebooks`)
- JupyterLab 실제 파일 목록 (`/jupyter/api/contents` 연동)
- 노트북 생성·삭제 (JupyterLab API 직접 호출)
- 클릭 시 JupyterLab 새 탭으로 직접 열기

### Connectors (`/connectors`)
- 커넥터 마켓플레이스: PostgreSQL·MySQL·S3·Kafka·BigQuery 등
- 3단계 설정 마법사: 연결 정보 → 테스트 → 테이블 선택 → 동기화 설정
- 연결 목록: 실시간 상태, Sync Now, Delete

### Jobs (`/jobs`)
- Airflow DAG 런 목록 (상태·시작시간·소요시간)
- 런 상세: 태스크 인스턴스 목록, 로그 뷰어

### Dashboards (`/dashboards`)
- SQL Lab에서 저장한 시각화 대시보드 관리
- 쿼리 재실행, 차트 편집, 공개/비공개 설정

### Services (`/services`)
- 서비스별 health 카드 + 접근 링크 (ingress 경로)
- 상세: Pod 상태, 메트릭, 재시작

### System (`/system`)
- 필요/권장/실제 사양 비교, 컴포넌트 리소스, 노드 상태

### Settings → AI — 외부 LLM 거버넌스
- AI 게이트웨이(LiteLLM) 상태 + 백엔드(Bedrock/Anthropic/OpenAI/Gemini/Ollama/vLLM) 런타임 등록·테스트·전환
- **토큰·비용 대시보드**: 총/모델별/**사용자별** spend·토큰, 날짜범위 Spend report, 예산 알림 배너
- **가상 키 & 예산**: 키 발급·모델범위·예산·rpm/tpm 한도
- **모델 폴백**: 1차 모델 장애 시 백업 모델 자동 전환 (SPOF 제거)
- **egress 정책**: `local-only`(주권/에어갭 — 외부 LLM 차단, fail-closed) vs `cloud-allowed`

---

## 선언적 파이프라인 DSL

Python 데코레이터 기반 파이프라인 정의 → Airflow DAG 자동 생성:

```python
from app.pipelines.decorators import pipeline, source, live_table, quality

@pipeline(name="sales_analytics", schedule="@daily")
def sales_pipeline():

    @source(name="raw_orders", connector="postgresql")
    def orders(): ...

    @live_table(mode="incremental")
    def daily_revenue():
        return """
        SELECT date, SUM(amount) as revenue
        FROM {{ source('raw_orders') }}
        {{ incremental_filter('date') }}
        GROUP BY date
        """

    @quality(table="daily_revenue")
    def revenue_positive():
        return "revenue > 0"
```

```bash
# 검증
python -m app.pipelines.cli validate my_pipeline.py

# Airflow DAG 컴파일
python -m app.pipelines.cli compile my_pipeline.py --output ./dags/
```

---

## 설치

### 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| CPU | 4코어 | 8코어+ |
| RAM | 8GB | 16GB+ |
| Disk | 50GB | 100GB+ |
| OS | Ubuntu 20.04+ / RHEL 8+ | Rocky Linux 9 권장 |

### 인터넷 환경

```bash
git clone https://github.com/datapond/datapond-k8s && cd datapond-k8s
sudo bash scripts/install.sh --domain datapond.local
sudo bash scripts/build-images.sh    # Docker 이미지 빌드 필요 시
```

### 에어갭 환경 (인터넷 차단)

```bash
# Step 1: 인터넷 가능 서버에서 번들 생성
sudo bash scripts/bundle-airgap.sh

# Step 2: 고객사 서버로 전송
scp datapond-airgap-2.3.0-*.tar.gz user@customer-server:/tmp/

# Step 3: 고객사 서버에서 설치
tar -xzf datapond-airgap-2.3.0-*.tar.gz
cd datapond-airgap-2.3.0-*/
sudo bash install.sh --domain your.domain.com --values your-values.yaml
```

`scripts/install.sh` 포함 기능:
- Pre-flight 체크 (CPU/RAM/Disk/포트)
- K3s + Helm 자동 설치
- Helm 차트 배포
- `/etc/hosts` 자동 등록
- Pending Pod 자동 정리
- 설치 로그 `/tmp/datapond-install-*.log` 저장

---

## 기본 인증 정보

| 서비스 | URL | 계정 |
|--------|-----|------|
| Frontend | http://datapond.local | — |
| JupyterLab | http://datapond.local/jupyter | token: `jupyter` |
| Airflow | http://datapond.local/airflow | airflow / airflow |
| MLflow | http://datapond.local/mlflow | — |

---

## 운영 명령어

```bash
# 상태 확인
kubectl get pods -n datapond
kubectl top nodes

# 로그
kubectl logs -f deployment/backend -n datapond
kubectl logs -f deployment/frontend -n datapond

# 재시작
kubectl rollout restart deployment/backend -n datapond

# 업그레이드
helm upgrade datapond helm/datapond \
  --namespace datapond \
  --values helm/datapond/values-quicktest.yaml \
  --wait=false

# 포트 포워딩 (직접 접근)
kubectl port-forward svc/backend 8000:8000 -n datapond
kubectl port-forward svc/trino 8080:8080 -n datapond
```

---

## Helm 차트

```
helm/datapond/
├── values.yaml              # 기본값 (HA, 프로덕션 규모)
├── values-quicktest.yaml    # 개발·테스트 (단일 노드)
├── values-dev.yaml          # 개발 환경
├── values-prod.yaml         # 프로덕션 (HA)
└── templates/
    ├── postgres-init-configmap.yaml   # DB 자동 초기화 (mlflow·airflow 등)
    └── ...                            # 각 서비스 Deployment/StatefulSet
```

**모든 Deployment에 `strategy: Recreate` 적용** — 롤링 업데이트로 인한 메모리 부족 Pending 방지

---

## 문서

| 문서 | 내용 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 컴포넌트 상세 스펙, 리소스 사이징, HA 구성 |
| [docs/PRODUCT_CONCEPT.md](docs/PRODUCT_CONCEPT.md) | 제품 전략, 포지셔닝, 로드맵 |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | 상세 설치 가이드 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 장애 대응, 일반적인 오류 해결 |
| [docs/QUICK_START.md](docs/QUICK_START.md) | 5분 시작 가이드 |
| [docs/LITELLM_INTEGRATION.md](docs/LITELLM_INTEGRATION.md) | AI 게이트웨이·거버넌스(폴백·비용·가드레일)·Vector/RAG |
| [docs/RLS_DESIGN.md](docs/RLS_DESIGN.md) | Row-Level Security 설계 |
| [docs/AIRGAP_READINESS.md](docs/AIRGAP_READINESS.md) | 에어갭 준비도·번들 검증 현황 |
| [CLAUDE.md](CLAUDE.md) | AI 에이전트 협업 가이드 + 현재 상태(Current Status) |
