# DataPond Kubernetes 아키텍처 문서

**버전**: 3.1.0-enterprise  
**작성일**: 2026-04-28  
**최종 수정**: 2026-05-11  
**대상**: 개발자, DevOps, 아키텍트

---

## 📋 목차

1. [시스템 개요](#시스템-개요)
2. [전체 아키텍처](#전체-아키텍처)
3. [전략적 컴포넌트](#전략적-컴포넌트)
4. [컴포넌트 구조](#컴포넌트-구조)
5. [네트워킹](#네트워킹)
6. [스토리지](#스토리지)
7. [보안](#보안)
8. [확장성](#확장성)
9. [고가용성](#고가용성)
10. [데이터 흐름](#데이터-흐름)
11. [기술 스택](#기술-스택)

---

## 시스템 개요

### 목적

DataPond는 **AI-Native Open Lakehouse Platform**으로, 배치/실시간 데이터 분석, ML 실험, 거버넌스를 통합 제공합니다. 데이터 주권 요구사항(금융, 공공, 의료, 제조)으로 인해 Databricks를 사용할 수 없는 환경에서 동급의 엔터프라이즈 기능을 온프레미스 또는 프라이빗 클라우드에서 실행합니다.

### 핵심 원칙

1. **Cloud Native**: Kubernetes 네이티브 설계
2. **Microservices**: 서비스별 독립 배포/스케일링
3. **Open Source First**: Apache 2.0/BSD 라이선스 (벤더 종속 없음)
4. **Enterprise-Ready**: 거버넌스, Lineage, RBAC 내장
5. **Real-time & Batch**: 통합 스트리밍 + 배치 처리
6. **Observable**: 통합 모니터링/로깅/Lineage
7. **Resilient**: 자동 복구 및 고가용성

### 전략적 차별화

```yaml
vs Databricks:
  포지셔닝: Databricks가 진입 불가한 데이터 주권 시장
  거버넌스: Polaris (Unity Catalog 대안)
  실시간: RisingWave (Spark Streaming 대체)
  관측성: OpenMetadata (자동 Lineage)
  AI: LiteLLM + Ollama (온프레미스 AI, Bedrock fallback)
  라이선스: 100% 오픈소스

vs Snowflake:
  배포: Self-hosted (데이터 주권, 에어갭 지원)
  확장성: Kubernetes Auto-scaling
  AI: Multi-model (Claude, GPT-4, Llama, Ollama)
  
vs Dremio:
  비용: $0 (Polaris 카탈로그)
  실시간: RisingWave 통합
  ML: MLflow + JupyterLab 내장
  AI: Text-to-SQL, Data Quality 자동화
```

### 멀티 환경 프로파일

| 환경 | Helm Values | RAM | 특징 |
|------|-------------|-----|------|
| **단일 노드 개발** | `values-quicktest.yaml` | 15 GB | LiteLLM/Ollama/Spark 비활성화 |
| **온프레미스 프로덕션** | `values-onprem.yaml` | 32 GB+ | 전체 스택 (LiteLLM + Ollama 포함) |
| **AWS EKS** | `values-aws.yaml` | — | S3 + Bedrock, SeaweedFS/Ollama/PG 비활성화 |

---

## 전체 아키텍처

### 엔터프라이즈 레이어 구조 (2026 v3.0)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Ingress Layer                                 │
│  Traefik/Nginx - TLS, Rate Limiting, Load Balancing                 │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
┌────────────────────────────┴─────────────────────────────────────────┐
│                     Application Layer                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │Frontend  │ │Backend   │ │Jupyter   │ │Airflow   │ │MLflow    │  │
│  │(Next.js) │ │(FastAPI) │ │Lab       │ │Webserver │ │          │  │
│  └──────────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│                    │          DuckDB         │            │         │
│                    │        (로컬 쿼리)       │            │         │
└────────────────────┼──────────┼──────────────┼────────────┼─────────┘
                     │          │              │            │
┌────────────────────┴──────────┴──────────────┴────────────┴─────────┐
│                  Data Processing Layer                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐        │
│  │  Trino   │  │  Spark   │  │RisingWave│  │ OpenMetadata │        │
│  │ (Query)  │  │ (Batch)  │  │(Stream)  │  │  (Lineage)   │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘        │
│       │             │             │                │                │
│       └─────────────┴─────────────┴────────────────┘                │
│                           │                                          │
└───────────────────────────┼──────────────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────────────┐
│              Catalog & Governance Layer (NEW!)                       │
│  ┌───────────────────────────────────────────────────────┐          │
│  │              Apache Polaris REST Catalog              │          │
│  │  - Iceberg 테이블 메타데이터 중앙 관리                 │          │
│  │  - RBAC (Role-Based Access Control)                  │          │
│  │  - 멀티테넌시 (Namespace isolation)                   │          │
│  │  - 감사 로그 (Audit logging)                          │          │
│  │  - 버전 관리 (Catalog versioning)                     │          │
│  └───────────────────┬───────────────────────────────────┘          │
└──────────────────────┼──────────────────────────────────────────────┘
                       │
┌──────────────────────┴───────────────────────────────────────────────┐
│                Storage Layer (Lakehouse)                             │
│  ┌─────────────────────────────────────────────────────┐            │
│  │         SeaweedFS (S3-compatible Object Storage)    │            │
│  │  ┌──────────────────────────────────────────────┐  │            │
│  │  │       Apache Iceberg Tables (ACID)           │  │            │
│  │  │  Bronze → Silver → Gold (Medallion)          │  │            │
│  │  │  - Parquet files (columnar storage)          │  │            │
│  │  │  - Time Travel (snapshot isolation)          │  │            │
│  │  │  - Schema Evolution (backward compatible)    │  │            │
│  │  │  - ACID transactions (optimistic locking)    │  │            │
│  │  │  - Partition pruning (query optimization)    │  │            │
│  │  └──────────────────────────────────────────────┘  │            │
│  └─────────────────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                  Metadata & State Layer                              │
│  ┌──────────┐  ┌──────────┐                                        │
│  │PostgreSQL│  │  Valkey  │                                        │
│  │(Primary) │  │(sessions)│                                        │
│  └──────────┘  └──────────┘                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### 데이터 흐름 (End-to-End)

```
[Real-time Path]
Kafka/Kinesis → RisingWave (PostgreSQL SQL) → Polaris → Iceberg → S3
              └─ Materialized Views (실시간 집계)

[Batch Path]
Airbyte → Polaris → Iceberg → S3
        └─ Schema inference, PII detection

[Analytics Path]
Trino → Polaris (권한 체크) → Iceberg → S3 → Result
     └─ Query optimization, Partition pruning

[ML/DS Path]
JupyterLab → DuckDB (로컬) → Iceberg → S3 (초고속)
           └─ Spark (대규모)

[Orchestration Path]
Airflow DAG → Spark Job → Polaris → Iceberg → S3

[Observability Path]
All Services → OpenMetadata (자동 수집)
             └─ Lineage graph, Data catalog
```

### 논리적 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                      Users                                  │
│  Data Engineers │ Data Scientists │ Analysts │ Business    │
└────────┬────────────────┬────────────┬────────────┬─────────┘
         │                │            │            │
┌────────▼────────────────▼────────────▼────────────▼─────────┐
│                    Ingress (datapond.local)                 │
└────────┬────────────────┬────────────┬────────────┬─────────┘
         │                │            │            │
   ┌─────▼─────┐    ┌────▼────┐  ┌───▼────┐  ┌────▼────┐
   │  Web UI   │    │Jupyter  │  │Airflow │  │ MLflow  │
   │(Next.js)  │    │  Lab    │  │   UI   │  │   UI    │
   └─────┬─────┘    └────┬────┘  └───┬────┘  └────┬────┘
         │               │           │            │
   ┌─────▼───────────────▼───────────▼────────────▼─────┐
   │              Backend API (FastAPI)                  │
   │  - Authentication (JWT)                             │
   │  - Authorization (RBAC via Polaris)                 │
   │  - Business logic                                   │
   └─────┬───────────────┬───────────┬────────────┬──────┘
         │               │           │            │
   ┌─────▼─────┐   ┌────▼────┐ ┌───▼─────┐ ┌────▼────┐
   │   Trino   │   │  Spark  │ │RisingWave│ │Polaris │
   │  (Query)  │   │ (Batch) │ │(Streaming│ │(Catalog)│
   └─────┬─────┘   └────┬────┘ └───┬─────┘ └────┬────┘
         │              │           │            │
         └──────────────┴───────────┴────────────┘
                        │
                 ┌──────▼───────┐
                 │   Iceberg    │
                 │   Tables     │
                 └──────┬───────┘
                        │
                 ┌──────▼───────┐
                 │  SeaweedFS   │
                 │  (S3 API)    │
                 └──────────────┘
```

---

## 전략적 컴포넌트

DataPond의 엔터프라이즈 경쟁력을 제공하는 4개 핵심 컴포넌트입니다.

### 1. Apache Polaris - Catalog & Governance Layer 🎯

**지위**: Apache Software Foundation Top-Level Project (2026년 2월 졸업)  
**출처**: Snowflake 기증 (3년 프로덕션 검증)  
**라이선스**: Apache 2.0

#### 역할
- Iceberg 테이블 메타데이터 중앙 관리
- 멀티 엔진 통합 (Trino, Spark, Flink 동일 카탈로그 사용)
- 세밀한 접근 제어 (Table/Namespace/Column 레벨)
- 카탈로그 버전 관리 및 감사 로깅

#### 가치 제안
```yaml
문제: JDBC Catalog의 한계
  - 동시성 제어 제한적
  - 권한 관리 없음
  - 멀티테넌트 불가
  - 감사 로그 없음

해결: Polaris REST Catalog
  - 분산 트랜잭션 지원
  - RBAC (Role-Based Access Control)
  - Namespace 격리
  - 모든 작업 감사 로그

경쟁력: Unity Catalog 대안
  - Databricks Unity Catalog: $$$
  - Apache Polaris: $0
  - 기능: 동등
```

#### 기술 스펙
```yaml
API: REST (Iceberg Catalog REST API 표준)
Port: 8181
Metastore: PostgreSQL
Warehouse: SeaweedFS (S3 API)
HA: 2+ replicas
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 1Gi (request) / 2Gi (limit)
```

#### 통합 방법
```properties
# Trino: iceberg.properties
iceberg.catalog.type=rest
iceberg.rest.uri=http://polaris:8181/api/catalog
iceberg.rest.credential=admin:password

# Spark: 환경변수
SPARK_SQL_CATALOG_ICEBERG_TYPE=rest
SPARK_SQL_CATALOG_ICEBERG_URI=http://polaris:8181/api/catalog
```

#### 엔터프라이즈 기능
1. **세밀한 권한 관리**
   - Namespace 레벨: CREATE, USE, DROP
   - Table 레벨: SELECT, INSERT, UPDATE, DELETE
   - Column 레벨: 민감 컬럼 마스킹 (향후)

2. **멀티테넌시**
   - Namespace 격리 (team1, team2 별도)
   - 리소스 쿼터 (테이블 수, 스토리지 제한)
   - 크로스 네임스페이스 쿼리 (권한 기반)

3. **감사 로그**
   - 모든 카탈로그 작업 추적
   - Who, What, When, Where
   - 규정 준수 (GDPR, HIPAA)

4. **버전 관리**
   - 카탈로그 스냅샷
   - Time Travel (특정 시점 복원)
   - Schema evolution 추적

---

### 2. RisingWave - Real-time Streaming Layer 🌊

**지위**: CNCF Sandbox → Incubating  
**비교**: Apache Flink 대안 (PostgreSQL 호환)  
**라이선스**: Apache 2.0

#### 역할
- 실시간 스트리밍 데이터 처리 (Kafka, Kinesis)
- PostgreSQL 호환 SQL (학습 곡선 제로)
- Materialized View (실시간 집계)
- Iceberg Sink (자동 Lakehouse 저장)

#### 가치 제안
```yaml
문제: Spark Streaming 복잡도
  - JVM 기반 (리소스 무거움)
  - Checkpoint 관리 복잡
  - Latency: 초-분 단위
  - 설정 복잡 (20+ 파라미터)

해결: RisingWave
  - PostgreSQL SQL (익숙함)
  - Stateful 자동 관리
  - Latency: 밀리초 단위
  - 설정 간단 (5줄)

단순화: Kafka + Spark Streaming → RisingWave
  - 컴포넌트: 2 → 1
  - 운영 복잡도: 50% 감소
  - 리소스 사용: 50% 감소
```

#### 기술 스펙
```yaml
Port: 4566 (PostgreSQL wire protocol)
Components:
  - Meta Server: 메타데이터 관리
  - Compute Node: SQL 처리 (2+ replicas)
  - Compactor: 데이터 압축
  - Frontend: SQL 인터페이스
Resources (Compute):
  CPU: 2000m (request) / 4000m (limit)
  Memory: 4Gi (request) / 8Gi (limit)
State Backend: SeaweedFS (S3)
```

#### 사용 예제
```sql
-- 1. Kafka 소스 정의
CREATE SOURCE events (
    user_id BIGINT,
    event_type VARCHAR,
    event_time TIMESTAMP,
    country VARCHAR
) WITH (
    connector = 'kafka',
    topic = 'events',
    properties.bootstrap.server = 'kafka:9092'
) FORMAT JSON;

-- 2. 실시간 Materialized View
CREATE MATERIALIZED VIEW hourly_stats AS
SELECT 
    date_trunc('hour', event_time) as hour,
    country,
    COUNT(*) as events,
    COUNT(DISTINCT user_id) as users
FROM events
GROUP BY hour, country;

-- 3. Iceberg Sink (자동 Lakehouse 저장)
CREATE SINK to_iceberg
FROM hourly_stats
WITH (
    connector = 'iceberg',
    catalog.uri = 'http://polaris:8181/api/catalog',
    table.name = 'analytics.realtime_hourly'
);

-- 4. 쿼리 (PostgreSQL 호환!)
SELECT * FROM hourly_stats WHERE hour >= NOW() - INTERVAL '1 day';
```

#### Use Case
- IoT 센서 데이터 실시간 모니터링
- 실시간 추천 시스템 (클릭스트림 → 즉시 반영)
- Fraud Detection (이상 거래 밀리초 탐지)
- CDC (MySQL → RisingWave → Iceberg 실시간 복제)

---

### 3. DuckDB - Lightweight Query Engine 🦆

**지위**: OLAP 데이터베이스 (in-process)  
**비교**: SQLite for Analytics  
**라이선스**: MIT

#### 역할
- JupyterLab 로컬 고성능 쿼리
- S3 Iceberg 테이블 직접 읽기 (클러스터 불필요)
- Pandas 연동 (df ↔ DuckDB 자유자재)
- Sub-second 쿼리 (GB급 데이터)

#### 가치 제안
```yaml
문제: 작은 분석에도 Spark 필요
  - Spark 세션 생성: 10-30초 대기
  - 클러스터 리소스: 2-4GB (오버킬)
  - 탐색적 분석 불편함

해결: DuckDB 로컬 쿼리
  - 즉시 시작 (0초)
  - 리소스: 0 (추가 클러스터 불필요)
  - 속도: Spark 대비 10배 빠름 (작은 데이터)

사용 패턴:
  - 작은 데이터 (< 10GB): DuckDB (초)
  - 중간 데이터 (10-100GB): DuckDB (분)
  - 큰 데이터 (> 100GB): Spark (필요시만)

Spark 사용률: 80% → 20% 감소
```

#### 기술 스펙
```yaml
배포: JupyterLab 내장 (pip install duckdb)
추가 리소스: 0 (로컬 실행)
지원 포맷:
  - Iceberg (네이티브)
  - Parquet, CSV, JSON
  - Pandas DataFrame
S3 연동: httpfs extension (내장)
```

#### 사용 예제
```python
# JupyterLab 노트북
import duckdb
from iceberg_helper import query_iceberg

# 1. Iceberg 테이블 직접 쿼리 (초고속!)
df = query_iceberg(
    'analytics/events',
    where="country = 'KR' AND date >= '2026-04-01'"
)
print(f"Rows: {len(df):,}")  # 1M rows in 2 seconds

# 2. 복잡한 집계 (DuckDB SQL)
conn = duckdb.connect()
result = conn.sql("""
    SELECT 
        country,
        COUNT(DISTINCT user_id) as users,
        AVG(session_duration) as avg_duration
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')
    WHERE date >= '2026-04-01'
    GROUP BY country
    ORDER BY users DESC
""").df()

# 3. Pandas 연동 (자유자재)
import pandas as pd
small_df = pd.read_csv('lookup.csv')

conn.execute("CREATE TEMP TABLE lookup AS SELECT * FROM small_df")
joined = conn.sql("""
    SELECT e.*, l.category
    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events') e
    JOIN lookup l ON e.user_id = l.user_id
""").df()

# 4. 시각화
import matplotlib.pyplot as plt
result.plot(kind='bar', x='country', y='users')
```

#### Data Scientist Workflow
```
Before (Spark 필수):
1. Spark 클러스터 시작 (10-30초)
2. DataFrame 로드 (느림)
3. 쿼리 실행 (Spark overhead)
4. 결과 Pandas로 변환
Total: 1-2분

After (DuckDB):
1. DuckDB 쿼리 (즉시)
2. 결과 Pandas DataFrame
Total: 1-5초 (10-20배 빠름)
```

---

### 4. OpenMetadata - Data Observability Platform 📊

**지위**: Linux Foundation 프로젝트  
**비교**: Collibra, Alation 대안  
**라이선스**: Apache 2.0

#### 역할
- 데이터 카탈로그 (메타데이터 중앙 저장소)
- 자동 Lineage (Airflow, Spark, Trino, MLflow)
- 데이터 검색 (풀텍스트, Elasticsearch)
- 데이터 품질 모니터링

#### 가치 제안
```yaml
문제: "이 데이터 어디서 왔어?"
  - Lineage 없음 → 추적 불가
  - 테이블 설명 없음 → 의미 모름
  - 데이터 오너 모름 → 누구한테 물어봐?

해결: OpenMetadata
  - 자동 Lineage (코드 수정 불필요)
  - 메타데이터 자동 수집
  - 검색 (Google for Data)

엔터프라이즈 세일즈:
  고객: "Lineage 지원하나요?"
  DataPond: "네! Airflow/Spark/Trino 자동 연동됩니다."
  고객: "데모 보여주세요" ✅
```

#### 기술 스펙
```yaml
Components:
  - Server: 메타데이터 API (2 replicas)
  - Elasticsearch: 검색 엔진
  - Ingestion: Connector 실행
Database: PostgreSQL (DataPond 재사용)
Port: 8585 (UI + API)
Resources (Server):
  CPU: 1000m (request) / 2000m (limit)
  Memory: 2Gi (request) / 4Gi (limit)
```

#### Connector 설정
```yaml
Airflow Connector:
  - DAG 목록, Task 의존성
  - 실행 히스토리
  - 자동 Lineage (DAG → Table)

Trino Connector:
  - 테이블/컬럼 메타데이터
  - 쿼리 히스토리
  - Lineage (Query → Tables)

Spark Connector:
  - Job 목록, Dataset
  - Lineage (Input → Output)

MLflow Connector:
  - Experiment, Model
  - 아티팩트 (model.pkl → 데이터셋)
  - ML Lineage (Data → Model)
```

#### Lineage 예제
```
OpenMetadata UI:

[PostgreSQL: raw.users]
       │
       ▼
[Airflow DAG: daily_etl] (매일 02:00 실행)
       │
       ▼
[Spark Job: transform_users] (Python 코드 링크)
       │
       ▼
[Iceberg: silver.users_enriched] (100M rows)
       │
       ▼
[Trino Query: user_analytics_daily] (5분 실행)
       │
       ▼
[Dashboard: User Insights] (Grafana 링크)

각 노드 클릭 시:
- 스키마 정보 (컬럼 타입, 설명)
- 샘플 데이터 (10 rows)
- 통계 (row count, size, last updated)
- 오너 정보 (Alice, Bob)
- 태그 (PII, sensitive)
- 데이터 품질 점수 (95/100)
```

#### 엔터프라이즈 기능
1. **Data Discovery**: "user email" 검색 → 20개 테이블 발견
2. **Data Governance**: PII 태그 자동 분류
3. **Data Quality**: Great Expectations 통합
4. **Glossary**: 용어 사전 (ARR, MRR 정의)

---

### 5. AI Layer (LiteLLM + Ollama) 🤖

**지위**: 2026-05-11 구현 완료  
**역할**: 온프레미스 AI 추론 + 외부 LLM fallback chain

#### 구성

```
[Query Lab 자연어 입력]
         │
         ▼
[Backend: POST /api/ai/sql]
         │
         ├─1. LiteLLM (내부, litellm:4000)
         │      └─ Ollama (qwen2.5-coder:7b) — on-prem only
         │
         ├─2. AWS Bedrock (us.anthropic.claude-haiku-4-5-20251001-v1:0)
         │      — AWS 환경 또는 API key 있을 때
         │
         ├─3. Anthropic API (claude-haiku-4-5)
         │      — 직접 API key 있을 때
         │
         └─4. Schema Template
               — 모든 외부 연결 실패 시 기본 SQL 템플릿 반환
```

#### LiteLLM 기술 스펙
```yaml
Port: 4000
ConfigMap: litellm-config (model_list YAML)
Helm: values-onprem.yaml → litellm.enabled: true
     values-quicktest.yaml → litellm.enabled: false  (RAM 부족)
Image: ghcr.io/berriai/litellm:main-latest
```

#### Ollama 기술 스펙
```yaml
Port: 11434
Type: StatefulSet
Model: qwen2.5-coder:7b (initContainer로 auto-pull)
PVC: 30Gi (모델 저장)
Helm: values-onprem.yaml → ollama.enabled: true
     values-quicktest.yaml → ollama.enabled: false
RAM 요구: 8GB+ (전용)
```

#### AI 설정 (Settings UI)
Settings → System → AI SQL Assistant 탭에서 설정 가능:
- Provider URL (LiteLLM endpoint)
- API Key (암호화 저장, CredentialVault)
- 설정은 `system_settings` 테이블에 저장 → 재시작 시 자동 복원

---

## 4개 컴포넌트 통합 효과

### Before (4개 없이)
```yaml
거버넌스: ❌ 없음
실시간: ❌ 제한적 (Spark Streaming만)
로컬 쿼리: ⚠️ Spark만 (무거움)
Lineage: ❌ 없음

경쟁력: "엔지니어용 플랫폼"
타겟: 데이터 엔지니어 only
```

### After (4개 통합)
```yaml
거버넌스: ✅ Polaris (Unity Catalog 수준)
실시간: ✅ RisingWave (Flink 대안)
로컬 쿼리: ✅ DuckDB (초고속)
Lineage: ✅ OpenMetadata (Collibra 대안)

경쟁력: "Complete Data Platform"
타겟: 전체 데이터 팀 (엔지니어 + 분석가 + 비즈니스)
```

### ROI 분석
```yaml
개발 투자: 3주 (Polaris 2일 + DuckDB 1일 + RisingWave 1주 + OpenMetadata 1주)
기능 가치: Databricks 수준
비용 절감: $0 (100% 오픈소스)
경쟁력: Databricks 대안으로 포지셔닝 가능
엔터프라이즈 세일즈: Lineage/거버넌스 objection 제거
```

---

## 컴포넌트 구조

### 1. Presentation Layer (프레젠테이션 계층)

#### Frontend (Next.js)

**역할**: 사용자 인터페이스

**기술 스택**:
- Next.js 14+ (React 18+)
- TypeScript
- Tailwind CSS
- React Query (TanStack Query)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 2 (dev) / 3 (prod)
Resources:
  CPU: 200m (request) / 500m (limit)
  Memory: 256Mi (request) / 512Mi (limit)
Autoscaling: HPA (70% CPU)
Port: 3000
```

**주요 기능**:
- 대시보드 (통계, 차트)
- 데이터 탐색 UI
- 노트북 관리
- ML 실험 관리
- 워크플로우 모니터링

**통신**:
- Backend API (REST)
- Embedded Services (iframe)

---

#### Backend (FastAPI)

**역할**: 비즈니스 로직 및 API 서버

**기술 스택**:
- FastAPI (Python 3.11+)
- SQLAlchemy (ORM)
- Pydantic (Validation)
- asyncio (비동기 처리)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 2 (dev) / 3 (prod)
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 512Mi (request) / 1Gi (limit)
Autoscaling: HPA (70% CPU)
Port: 8000
```

**주요 기능**:
- RESTful API 제공
- 데이터베이스 CRUD
- 인증/인가
- 외부 서비스 연동 (MLflow, Airflow)
- 비즈니스 로직 처리

**통신**:
- PostgreSQL (데이터 영속성)
- Redis (캐싱, 세션)
- MLflow (실험 추적)
- SeaweedFS (파일 스토리지)

**API 엔드포인트**:
```
/api/health              - Health check
/api/v1/projects         - 프로젝트 관리
/api/v1/datasets         - 데이터셋 관리
/api/v1/notebooks        - 노트북 관리
/api/v1/experiments      - ML 실험 관리
/api/v1/workflows        - 워크플로우 관리
/api/v1/users            - 사용자 관리
```

---

### 2. Service Layer (서비스 계층)

#### JupyterLab

**역할**: 대화형 노트북 개발 환경

**기술 스택**:
- JupyterLab
- Python 3.11+
- scipy-notebook 기반
- 데이터 분석 라이브러리 (pandas, numpy, scikit-learn)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1
Resources:
  CPU: 1000m (request) / 2000m (limit)
  Memory: 2Gi (request) / 4Gi (limit)
Port: 8888
Persistence: 20Gi (PVC)
```

**주요 기능**:
- Python/R 노트북 실행
- 데이터 탐색
- 모델 개발
- 시각화

**접속**:
- URL: `/jupyter`
- Token: 설정 가능 (기본: `jupyter`)

---

#### MLflow

**역할**: ML 실험 추적 및 모델 관리

**기술 스택**:
- MLflow 2.10+
- PostgreSQL (backend store)
- SeaweedFS (artifact store)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 1Gi (request) / 2Gi (limit)
Port: 5000
Persistence: 20Gi (PVC)
```

**주요 기능**:
- 실험 추적 (metrics, parameters)
- 모델 버전 관리
- 모델 레지스트리
- Artifact 저장

**접속**:
- URL: `/mlflow`

**데이터 스토리지**:
- **Backend Store**: PostgreSQL (메타데이터)
- **Artifact Store**: SeaweedFS S3 (모델, 로그)

---

#### Airflow

**역할**: 워크플로우 오케스트레이션

**기술 스택**:
- Apache Airflow 2.8+
- PostgreSQL (metadata DB)
- LocalExecutor (dev) / CeleryExecutor (prod)

**배포 구성**:
```yaml
Components:
  - Webserver (UI):
      Replicas: 1 (dev) / 3 (prod)
      CPU: 200m / 500m
      Memory: 512Mi / 1Gi
      Port: 8080
  
  - Scheduler (Task 관리):
      Replicas: 1 (dev) / 2 (prod)
      CPU: 200m / 500m
      Memory: 512Mi / 1Gi
  
  - Workers (Task 실행, prod only):
      Replicas: 0 (dev) / 4 (prod)
      CPU: 1000m / 2000m
      Memory: 2Gi / 4Gi

Persistence:
  - DAGs: 10Gi (PVC)
  - Logs: 10Gi (PVC)
```

**주요 기능**:
- DAG (Directed Acyclic Graph) 정의
- 스케줄링
- 의존성 관리
- 실행 모니터링

**접속**:
- URL: `/airflow`
- 계정: admin / admin (변경 필요)

---

#### Spark

**역할**: 분산 데이터 처리

**기술 스택**:
- Apache Spark 3.5
- Bitnami Spark 이미지

**배포 구성**:
```yaml
Components:
  - Master:
      Type: StatefulSet
      Replicas: 1
      CPU: 1000m / 2000m
      Memory: 2Gi / 4Gi
      Ports:
        - Spark: 7077
        - Web UI: 8080
  
  - Workers:
      Type: StatefulSet
      Replicas: 1 (dev) / 5 (prod)
      CPU: 500m / 1000m (dev) | 4000m / 8000m (prod)
      Memory: 1Gi / 2Gi (dev) | 8Gi / 16Gi (prod)
      Env:
        SPARK_WORKER_CORES: 1 (dev) / 4 (prod)
        SPARK_WORKER_MEMORY: 1G (dev) / 8G (prod)
```

**주요 기능**:
- 대용량 데이터 처리
- 분산 ML 학습
- ETL 작업
- 스트리밍 처리

**접속**:
- URL: `/spark`
- Master: `spark://spark-master:7077`

---

#### SeaweedFS

**역할**: S3 호환 객체 스토리지

**기술 스택**:
- SeaweedFS (S3 API)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1
Resources:
  CPU: 500m (request) / 1000m (limit)
  Memory: 1Gi (request) / 2Gi (limit)
Ports:
  - API: 9000
  - Console: 9001
Persistence: 100Gi (PVC)
```

**주요 기능**:
- MLflow artifacts 저장
- 파일 업로드/다운로드
- 버킷 관리
- S3 API 호환

**접속**:
- Console: `/seaweedfs-console`
- API: `http://seaweedfs:9000`

**버킷 구조**:
```
mlflow-artifacts/        # MLflow 실험 결과
  ├── 0/                 # Experiment ID
  │   └── <run-id>/
  │       ├── artifacts/
  │       └── metrics/
  └── models/            # 등록된 모델
```

---

#### Trino (SQL Analytics with Iceberg)

**역할**: 분산 SQL 쿼리 엔진 및 Apache Iceberg 테이블 관리

**기술 스택**:
- Trino (formerly PrestoSQL)
- Apache Iceberg 1.4+ (Table Format)
- PostgreSQL JDBC Catalog
- S3-compatible storage (SeaweedFS)

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1 (coordinator)
Resources:
  CPU: 1000m (request) / 2000m (limit)
  Memory: 2Gi (request) / 4Gi (limit)
Port: 8080
Persistence: 50Gi (Iceberg warehouse)
```

**주요 기능**:
- Apache Iceberg 테이블 생성/관리
- ACID 트랜잭션 지원
- Time Travel 쿼리
- 스키마 진화 (Schema Evolution)
- 파티션 관리
- 페더레이션 쿼리 (PostgreSQL + Iceberg)

**Iceberg Catalog 구성**:
```yaml
Catalog Type: JDBC (PostgreSQL)
Database: iceberg_catalog
Warehouse Location: s3a://iceberg/warehouse
Storage: SeaweedFS S3 API
```

**접속**:
- Web UI: `/trino`
- CLI: `trino --server http://trino:8080`

**Iceberg 테이블 구조 예시**:
```sql
-- 테이블 생성
CREATE TABLE iceberg.analytics.events (
    event_id BIGINT,
    user_id VARCHAR,
    event_type VARCHAR,
    timestamp TIMESTAMP,
    properties JSON
) WITH (
    format = 'PARQUET',
    partitioning = ARRAY['day(timestamp)']
);

-- Time Travel 쿼리
SELECT * FROM iceberg.analytics.events 
FOR VERSION AS OF 12345;

-- 스키마 진화
ALTER TABLE iceberg.analytics.events 
ADD COLUMN user_agent VARCHAR;
```

**통신**:
- PostgreSQL (Iceberg catalog metadata)
- SeaweedFS S3 (데이터 파일 저장)
- Spark (Iceberg 테이블 읽기/쓰기)
- JupyterLab (Iceberg 데이터 분석)

**Iceberg Lakehouse 아키텍처**:
```
┌─────────────────────────────────────────┐
│         Trino (SQL Interface)           │
│     - Query Engine                      │
│     - Table Management                  │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│    Apache Iceberg Table Format          │
│  ┌────────────────────────────────┐    │
│  │  Metadata Layer                │    │
│  │  - Schema                      │    │
│  │  - Partitioning                │    │
│  │  - Snapshots (Time Travel)     │    │
│  └──────────────┬─────────────────┘    │
│                 │                       │
│  ┌──────────────▼─────────────────┐    │
│  │  Data Layer (Parquet/ORC)      │    │
│  │  - Columnar Storage            │    │
│  │  - Compression                 │    │
│  └────────────────────────────────┘    │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      SeaweedFS S3 Storage               │
│  s3://iceberg/warehouse/                │
│    ├── analytics/                       │
│    │   └── events/                      │
│    │       ├── data/ (Parquet files)    │
│    │       └── metadata/ (snapshots)    │
│    └── staging/                         │
└─────────────────────────────────────────┘
```

**Iceberg + Spark 통합**:
- Spark는 Iceberg 테이블에 직접 읽기/쓰기 가능
- JupyterLab에서 PySpark를 통한 Iceberg 데이터 분석
- MLflow 실험 결과를 Iceberg 테이블로 저장

**사용 사례**:
1. **데이터 레이크하우스**: 구조화/반구조화 데이터 통합 저장
2. **Time Travel**: 과거 시점 데이터 조회 및 롤백
3. **스키마 진화**: 무중단 스키마 변경
4. **대용량 분석**: 페타바이트급 데이터 분산 쿼리
5. **데이터 버전 관리**: Git-like 데이터 스냅샷 관리

---

### 3. Data Layer (데이터 계층)

#### PostgreSQL

**역할**: 주 데이터베이스 (OLTP)

**기술 스택**:
- PostgreSQL 16
- Alpine 기반

**배포 구성**:
```yaml
Type: StatefulSet
Replicas: 1 (dev) / 2 (prod, with replication)
Resources:
  CPU: 1000m / 2000m (dev) | 2000m / 4000m (prod)
  Memory: 2Gi / 4Gi (dev) | 4Gi / 8Gi (prod)
Port: 5432
Persistence: 50Gi (dev) / 200Gi (prod)
StorageClass: local-path
```

**데이터베이스 구조**:
```
├── datapond           # 메인 애플리케이션 DB
│   ├── users                     # 사용자
│   ├── connectors                # 데이터 커넥터
│   ├── connector_tables          # 테이블별 sync 설정
│   ├── connector_sync_jobs       # Sync 이력
│   ├── connector_quality_checks  # Data Quality 결과 (신규)
│   ├── saved_transforms          # ELT Transform 정의 (신규)
│   ├── system_settings           # 시스템 설정 / AI 키 (신규)
│   └── notebooks                 # 노트북 메타데이터
├── mlflow             # MLflow 메타데이터
│   ├── experiments
│   ├── runs
│   └── metrics
├── airflow            # Airflow 메타데이터
│   ├── dags
│   ├── dag_run
│   └── task_instance
├── iceberg_catalog    # Apache Polaris metastore
├── polaris_catalog    # Polaris 카탈로그
└── openmetadata_catalog  # OpenMetadata 메타데이터
```

**고가용성** (프로덕션):
- Streaming Replication (1 Primary + 1 Standby)
- Automatic Failover (pg_auto_failover 또는 Patroni)
- WAL Archiving

**백업 전략**:
- Full Backup: 매일
- WAL Archiving: 연속
- Point-in-Time Recovery (PITR) 지원

---

#### Redis

**역할**: 캐싱 및 세션 스토어

**기술 스택**:
- Redis 7
- Alpine 기반

**배포 구성**:
```yaml
Type: Deployment
Replicas: 1 (dev) / 3 (prod, with Sentinel)
Resources:
  CPU: 200m / 500m (dev) | 500m / 1000m (prod)
  Memory: 256Mi / 512Mi (dev) | 512Mi / 1Gi (prod)
Port: 6379
Persistence: 5Gi (dev) / 20Gi (prod)
```

**사용 목적**:
- API 응답 캐싱
- 세션 관리
- Rate limiting
- 임시 데이터 저장
- Celery broker (Airflow, prod)

**고가용성** (프로덕션):
- Redis Sentinel (3 replicas)
- Automatic Failover
- Read Replicas

---

## 네트워킹

### Ingress 라우팅

#### Path-based Routing

```yaml
Ingress: datapond.local

Routes:
  / (Root)                    → frontend:3000
  /api/*                      → backend:8000
  /jupyter/*                  → jupyter:8888
  /mlflow/*                   → mlflow:5000
  /airflow/*                  → airflow:8080
  /spark/*                    → spark-master:8080
  /seaweedfs-console/*            → seaweedfs:9001
```

#### Ingress 구성

**개발 환경**:
```yaml
IngressClass: traefik (K3s 기본)
TLS: disabled
Annotations:
  - traefik.ingress.kubernetes.io/router.middlewares: strip-prefix
```

**프로덕션**:
```yaml
IngressClass: nginx
TLS: enabled (cert-manager + Let's Encrypt)
Annotations:
  - cert-manager.io/cluster-issuer: letsencrypt-prod
  - nginx.ingress.kubernetes.io/ssl-redirect: "true"
  - nginx.ingress.kubernetes.io/rate-limit: "100"
```

---

### Service Mesh (내부 통신)

#### Service Discovery

모든 서비스는 Kubernetes Service를 통해 발견됩니다:

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
litellm.datapond.svc.cluster.local:4000    (AI proxy — disabled on quicktest)
ollama.datapond.svc.cluster.local:11434    (LLM runtime — disabled on quicktest)
mlflow.datapond.svc.cluster.local:5000
```

#### 통신 패턴

```
Frontend → Backend:
  - HTTP/REST API
  - JSON payload
  
Backend → PostgreSQL:
  - PostgreSQL protocol
  - Connection pooling (SQLAlchemy)
  
Backend → Redis:
  - Redis protocol
  - Connection pooling (redis-py)
  
Backend → MLflow:
  - HTTP/REST API
  - MLflow tracking API
  
MLflow → PostgreSQL:
  - Backend store (메타데이터)
  
MLflow → SeaweedFS:
  - S3 API
  - Artifact storage
  
Airflow → PostgreSQL:
  - Metadata store
  
Spark Worker → Spark Master:
  - Spark RPC protocol
```

---

### Network Policies (선택사항)

프로덕션 환경에서 네트워크 격리:

```yaml
# Backend만 PostgreSQL 접근 허용
PostgreSQL:
  Ingress:
    - From: backend
    - From: mlflow
    - From: airflow
  Egress: deny (default)

# Frontend는 Backend만 접근
Frontend:
  Ingress:
    - From: ingress
  Egress:
    - To: backend

# Backend 접근 제어
Backend:
  Ingress:
    - From: frontend
    - From: ingress
  Egress:
    - To: postgres
    - To: redis
    - To: mlflow
    - To: seaweedfs
```

---

## 스토리지

### 스토리지 계층

```
┌─────────────────────────────────────────────┐
│         Kubernetes Persistent Volume        │
│              (local-path / NFS)             │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐  ┌──────▼───┐  ┌──────▼────┐
│ Block  │  │   File   │  │  Object   │
│Storage │  │ Storage  │  │  Storage  │
│(PVC)   │  │  (PVC)   │  │  (SeaweedFS)  │
└────────┘  └──────────┘  └───────────┘
```

### PersistentVolume Claims

| Service | Size (dev) | Size (prod) | Access Mode | 용도 |
|---------|------------|-------------|-------------|------|
| **PostgreSQL** | 20Gi | 200Gi | ReadWriteOnce | 데이터베이스 |
| **Redis** | 2Gi | 20Gi | ReadWriteOnce | 캐시 영속화 |
| **JupyterLab** | 10Gi | 100Gi | ReadWriteOnce | 노트북 저장 |
| **MLflow** | 5Gi | 100Gi | ReadWriteOnce | 메타데이터 |
| **SeaweedFS** | 20Gi | 500Gi | ReadWriteOnce | 객체 스토리지 |
| **Airflow DAGs** | 5Gi | 50Gi | ReadWriteMany | DAG 파일 |
| **Airflow Logs** | 5Gi | 100Gi | ReadWriteMany | 실행 로그 |

**총 스토리지**: ~70Gi (dev) / ~1070Gi (prod)

---

### StorageClass

#### 개발 환경 (K3s)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
```

**특징**:
- Local node storage
- Dynamic provisioning
- 빠른 I/O
- 단일 노드 제한

#### 프로덕션 환경

**옵션 1: NFS**
```yaml
provisioner: nfs.csi.k8s.io
reclaimPolicy: Retain
volumeBindingMode: Immediate
```

**옵션 2: Ceph/Rook**
```yaml
provisioner: rook-ceph.rbd.csi.ceph.com
reclaimPolicy: Retain
```

**옵션 3: Cloud Provider**
- AWS: EBS (gp3)
- GCP: Persistent Disk (SSD)
- Azure: Azure Disk (Premium SSD)

---

### 백업 전략

#### PostgreSQL

```bash
# Full Backup (매일 새벽 2시)
pg_dump -h postgres -U datapond datapond > backup.sql

# WAL Archiving (연속)
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'

# PITR (Point-in-Time Recovery)
pg_basebackup + WAL replay
```

#### PVC Snapshots

```yaml
# VolumeSnapshot (Kubernetes)
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-snapshot-20260428
spec:
  volumeSnapshotClassName: csi-snapclass
  source:
    persistentVolumeClaimName: postgres-pvc
```

#### SeaweedFS

```bash
# mc mirror (SeaweedFS Client)
mc mirror --watch datapond/mlflow-artifacts /backup/seaweedfs/
```

---

## 보안

### 1. 인증 및 인가

#### Secrets Management

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: datapond-secrets
type: Opaque
data:
  POSTGRES_PASSWORD: <base64>
  JWT_SECRET: <base64>
  SEAWEEDFS_S3_PASSWORD: <base64>
  JUPYTER_TOKEN: <base64>
```

**보안 원칙**:
- ❌ values.yaml에 평문 비밀번호 저장 금지
- ✅ Kubernetes Secrets 사용
- ✅ 프로덕션: 외부 secret store (Vault, AWS Secrets Manager)
- ✅ Sealed Secrets (GitOps 시)

---

#### RBAC (Role-Based Access Control)

```yaml
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: datapond-backend
  namespace: datapond

---
# Role
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: datapond-app-role
  namespace: datapond
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]

---
# RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: datapond-app-binding
  namespace: datapond
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: datapond-app-role
subjects:
- kind: ServiceAccount
  name: datapond-backend
  namespace: datapond
```

---

### 2. Network Security

#### TLS/SSL

**Ingress TLS** (프로덕션):
```yaml
spec:
  tls:
  - hosts:
    - datapond.yourdomain.com
    secretName: datapond-tls
```

**cert-manager** (Let's Encrypt):
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: datapond-cert
spec:
  secretName: datapond-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - datapond.yourdomain.com
```

---

#### Network Policies

```yaml
# PostgreSQL 접근 제한
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-network-policy
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend
    - podSelector:
        matchLabels:
          app: mlflow
    - podSelector:
        matchLabels:
          app: airflow
    ports:
    - protocol: TCP
      port: 5432
```

---

### 3. Pod Security

#### Security Context

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: true
```

#### Resource Limits

```yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
    ephemeral-storage: 1Gi
```

---

### 4. 이미지 보안

```yaml
# 신뢰할 수 있는 레지스트리만 사용
image: docker.io/postgres:16-alpine

# 취약점 스캔 (Trivy)
$ trivy image postgres:16-alpine

# 이미지 서명 확인 (Notary/Cosign)
$ cosign verify <image>
```

---

## 확장성

### 1. Horizontal Scaling

#### HPA (Horizontal Pod Autoscaler)

**Frontend**:
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

**Backend**:
```yaml
minReplicas: 2
maxReplicas: 20
targetCPUUtilizationPercentage: 70
```

**스케일링 동작**:
```
트래픽 증가 → CPU 사용률 > 70% → Pod 증가
트래픽 감소 → CPU 사용률 < 70% → Pod 감소 (5분 쿨다운)
```

---

#### Cluster Autoscaler

멀티 노드 환경에서 노드 자동 증감:

```yaml
# AWS EKS
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler
data:
  min-nodes: "3"
  max-nodes: "10"
  scale-down-delay: "10m"
```

---

### 2. Vertical Scaling

#### VPA (Vertical Pod Autoscaler)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: backend-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  updatePolicy:
    updateMode: "Auto"  # 또는 "Recreate"
```

---

### 3. 데이터베이스 스케일링

#### PostgreSQL

**Read Replicas**:
```
Primary (Write) → Replica 1 (Read)
               → Replica 2 (Read)
               → Replica 3 (Read)
```

**Connection Pooling**:
```yaml
# PgBouncer
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pgbouncer
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: pgbouncer
        image: pgbouncer/pgbouncer
        env:
        - name: MAX_CLIENT_CONN
          value: "1000"
        - name: DEFAULT_POOL_SIZE
          value: "25"
```

#### Redis

**Redis Cluster** (프로덕션):
```
Master 1 → Replica 1
Master 2 → Replica 2
Master 3 → Replica 3
```

---

### 4. 스토리지 스케일링

**PVC 확장**:
```bash
# PVC 크기 증가
kubectl patch pvc postgres-pvc -p '{"spec":{"resources":{"requests":{"storage":"100Gi"}}}}'

# StatefulSet 재시작
kubectl rollout restart statefulset postgres
```

---

## 고가용성

### 1. 복제본 전략

| Component | Dev | Prod | Strategy |
|-----------|-----|------|----------|
| Frontend | 1-2 | 3-5 | Active-Active |
| Backend | 1-2 | 3-10 | Active-Active |
| PostgreSQL | 1 | 2-3 | Primary-Standby |
| Redis | 1 | 3 | Sentinel |
| Airflow Web | 1 | 3 | Active-Active |
| Airflow Scheduler | 1 | 2 | Active-Standby |
| Spark Master | 1 | 1 | Single (HA via checkpoint) |
| Spark Workers | 1 | 5+ | Active-Active |

---

### 2. 헬스 체크

```yaml
# Liveness Probe (컨테이너 생존 확인)
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

# Readiness Probe (트래픽 수신 준비 확인)
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 3
```

**동작**:
- Liveness 실패 → Pod 재시작
- Readiness 실패 → Service에서 제거 (트래픽 차단)

---

### 3. 롤링 업데이트

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 1      # 최대 1개 Pod까지 unavailable
    maxSurge: 1            # 최대 1개 추가 Pod 생성 가능
```

**업데이트 프로세스**:
```
1. 새 Pod 1개 생성
2. 새 Pod Ready 확인
3. 기존 Pod 1개 종료
4. 반복 (모든 Pod 교체)
```

**제로 다운타임 보장**.

---

### 4. Pod Disruption Budget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: backend-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: backend
```

**효과**:
- 노드 드레인 시 최소 2개 Pod 유지
- 자발적 중단 제어

---

### 5. 멀티 AZ/Region (프로덕션)

```yaml
# Node Affinity (다른 AZ에 배포)
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchExpressions:
        - key: app
          operator: In
          values:
          - backend
      topologyKey: topology.kubernetes.io/zone
```

---

## 데이터 흐름

### 1. 사용자 요청 흐름

```
User Browser
    │
    ▼
Ingress (datapond.local)
    │
    ├─────▶ Frontend (/) ───────────────┐
    │                                   │
    └─────▶ Backend (/api) ────────┐   │
                │                   │   │
                ├─▶ PostgreSQL      │   │
                │   (데이터 조회)    │   │
                │                   │   │
                ├─▶ Redis           │   │
                │   (캐시 확인)      │   │
                │                   │   │
                └─▶ Response ◀──────┴───┘
```

---

### 2. ML 실험 흐름

```
JupyterLab
    │ (모델 학습)
    ▼
MLflow Tracking API
    │
    ├─▶ PostgreSQL (메타데이터 저장)
    │   - Experiment name
    │   - Run ID
    │   - Parameters
    │   - Metrics
    │
    └─▶ SeaweedFS (artifacts 저장)
        - Model files
        - Plots
        - Logs
```

---

### 3. Airflow 워크플로우

```
Airflow Webserver (사용자)
    │ (DAG 정의/트리거)
    ▼
Airflow Scheduler
    │ (작업 스케줄링)
    ▼
Airflow Workers (LocalExecutor/CeleryExecutor)
    │
    ├─▶ Spark Job 실행
    │   (데이터 처리)
    │
    ├─▶ PostgreSQL
    │   (메타데이터 저장)
    │
    └─▶ Backend API 호출
        (결과 알림)
```

---

### 4. Spark 작업 흐름

```
Client (Jupyter/Airflow)
    │ (spark-submit)
    ▼
Spark Master
    │ (작업 분배)
    ├─▶ Worker 1 (Task 실행)
    ├─▶ Worker 2 (Task 실행)
    └─▶ Worker N (Task 실행)
        │
        ▼
    Result Aggregation
        │
        ▼
    SeaweedFS (결과 저장)
```

---

## 기술 스택

### Infrastructure

| 계층 | 기술 | 버전 |
|------|------|------|
| **Container Runtime** | Containerd | 1.7+ |
| **Orchestration** | Kubernetes | 1.25+ |
| **K8s Distribution** | K3s | 1.28+ |
| **Package Manager** | Helm | 3.12+ |
| **Ingress** | Traefik / Nginx | 2.10+ / 1.8+ |
| **Storage** | local-path / NFS | - |
| **Monitoring** | Prometheus + Grafana | 2.45+ / 10.0+ |

---

### Application Stack

| 서비스 | 기술 | 버전 |
|--------|------|------|
| **Frontend** | Next.js | 14+ |
| **Backend** | FastAPI | 0.104+ |
| **Database** | PostgreSQL | 16 |
| **Cache** | Redis | 7 |
| **Notebook** | JupyterLab | latest |
| **ML Tracking** | MLflow | 2.10+ |
| **Object Storage** | SeaweedFS | latest |
| **Workflow** | Apache Airflow | 2.8+ |
| **Processing** | Apache Spark | 3.5 |

---

### Development Stack

| 영역 | 기술 |
|------|------|
| **Language** | Python 3.11+, TypeScript |
| **ORM** | SQLAlchemy |
| **Validation** | Pydantic |
| **API Docs** | OpenAPI (Swagger) |
| **Testing** | pytest, Jest |
| **Linting** | Black, ESLint |
| **Type Check** | mypy, TypeScript |

---

## 확장 로드맵

### Phase 1: 단일 노드 (현재)

```
[ K3s Node ]
  - 모든 서비스 실행
  - Local storage
  - 개발/테스트 환경
```

**목표**: 빠른 개발, 프로토타입

---

### Phase 2: 3-노드 클러스터 (3-6개월)

```
[ Master Node ]          [ Worker 1 ]        [ Worker 2 ]
  - Control Plane          - Apps              - Apps
  - etcd                   - Data Services     - Data Services
  - Light workloads
```

**목표**: 고가용성, 운영 환경

---

### Phase 3: 관리형 Kubernetes (6-12개월)

```
Cloud Provider (AWS EKS / GKE / AKS)
  - 멀티 AZ
  - 관리형 Control Plane
  - Auto-scaling
  - Managed Add-ons
```

**목표**: 엔터프라이즈, 글로벌 서비스

---

### Phase 4: 멀티 클러스터 (12+ 개월)

```
[ Region 1 - Prod ]    [ Region 2 - DR ]    [ Dev Cluster ]
      ▲                       ▲                     │
      └───── Cluster Mesh ────┘                     │
                  │                                  │
            [ Service Mesh (Istio) ]                │
                  │                                  │
            [ GitOps (ArgoCD) ] ◀──────────────────┘
```

**목표**: 글로벌 HA, DR, 멀티 리전

---

## 참고 자료

### Kubernetes 공식 문서
- [Kubernetes Docs](https://kubernetes.io/docs/)
- [Helm Docs](https://helm.sh/docs/)

### 프로젝트 문서
- [README.md](../README.md)
- [QUICKSTART.md](../QUICKSTART.md)
- [INSTALLATION.md](INSTALLATION.md)
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**문서 버전**: 1.0  
**최종 수정**: 2026-04-28  
**작성자**: DataPond Team
