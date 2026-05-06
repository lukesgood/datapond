# DataPond 데이터 파이프라인 전체 흐름

**버전**: 1.0.0  
**작성일**: 2026-05-07  
**목적**: Lakehouse 관점의 데이터 파이프라인 전체 흐름 및 각 컴포넌트 역할 정의

---

## 1. 전체 아키텍처 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA SOURCES                                      │
│  PostgreSQL · MySQL · Oracle · REST API · S3 · Kafka · Custom Python        │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │ INGESTION LAYER               │
              │  Batch          Streaming     │
              │  (Connectors)   (RisingWave)  │
              └───────────────┬───────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────────────┐
│                        LAKEHOUSE CORE                                       │
│                                                                             │
│  ┌──────────────────────┐    ┌──────────────────────────────────────────┐   │
│  │   Apache Polaris     │    │           SeaweedFS S3                   │   │
│  │   (REST Catalog)     │◄───│   s3a://iceberg/warehouse/               │   │
│  │   포트: 8181          │    │   포트: 8333                             │   │
│  │   메타데이터 중앙 관리 │    │   실제 데이터 파일 저장 (Parquet)         │   │
│  └──────────────────────┘    └──────────────────────────────────────────┘   │
│                                        │                                    │
│                              Apache Iceberg (테이블 포맷)                    │
│                              - ACID 트랜잭션                                 │
│                              - 스키마 진화                                   │
│                              - Time Travel                                  │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │ QUERY / COMPUTE LAYER         │
              │  Trino    Spark    DuckDB     │
              │  (OLAP)  (Batch)  (노트북)    │
              └───────────────┬───────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────────────┐
│                         CONSUMERS                                           │
│  Frontend SQL Lab · JupyterLab · MLflow · Airflow · OpenMetadata · BI Tools │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 각 컴포넌트 역할 정의

### 2.1 Ingestion Layer (데이터 수집)

#### Connector (배치 수집)
| 항목 | 내용 |
|------|------|
| **역할** | 외부 데이터 소스에서 Iceberg 테이블로 데이터를 주기적으로 복사 |
| **대상 소스** | PostgreSQL, MySQL, REST API, S3, Custom Python |
| **출력** | Iceberg 테이블 (`iceberg.default.{table_name}`) |
| **현재 상태** | ❌ pandas로 읽기만 하고 Iceberg 적재 미구현 |
| **목표 상태** | ✅ Source → pandas → pyarrow → Parquet → SeaweedFS → Trino INSERT |
| **동기화 모드** | FULL (전체 교체), INCREMENTAL (증분 추가), CDC (변경 감지) |

**현재 구현 (문제):**
```python
# database.py - sync_to_iceberg()
df = pd.read_sql(query, engine)   # ✅ 읽기
rows_processed = len(df)
# TODO: Write to Iceberg           # ❌ 여기서 멈춤
return SyncJobStatus(SUCCESS)      # ❌ 거짓 성공
```

**목표 구현:**
```python
# 1. Source에서 읽기
df = pd.read_sql(query, engine)

# 2. SeaweedFS S3에 Parquet 저장
table = pa.Table.from_pandas(df)
s3_path = f"s3://iceberg/warehouse/default/{table_name}/"
pq.write_to_dataset(table, root_path=s3_path, filesystem=s3_fs)

# 3. Trino로 Iceberg 테이블 등록
trino_conn.execute(f"""
    CREATE TABLE IF NOT EXISTS iceberg.default.{table_name}
    ({schema_ddl})
    WITH (format='PARQUET', location='{s3_path}')
""")
# FULL 모드: DELETE FROM + INSERT
# INCREMENTAL 모드: INSERT INTO (append)
```

#### RisingWave (실시간 스트리밍)
| 항목 | 내용 |
|------|------|
| **역할** | Kafka/Kinesis 등 스트림 소스에서 실시간으로 Iceberg 테이블에 데이터 적재 |
| **포트** | 4566 (PostgreSQL 호환 wire protocol) |
| **특징** | SQL만으로 스트리밍 파이프라인 정의 (Spark Streaming 대체) |
| **출력** | Iceberg sink → Polaris 카탈로그 등록 |
| **현재 상태** | ✅ 서비스 실행 중, 🚧 Iceberg sink 설정 필요 |

**사용 패턴:**
```sql
-- RisingWave에서 실행
CREATE SOURCE kafka_events (
    user_id INT,
    event_type VARCHAR,
    event_time TIMESTAMPTZ
) WITH (
    connector = 'kafka',
    topic = 'user_events',
    properties.bootstrap.server = 'kafka:9092'
);

CREATE SINK iceberg_sink FROM kafka_events
WITH (
    connector = 'iceberg',
    type = 'append-only',
    catalog.type = 'storage',
    warehouse.path = 's3a://iceberg/warehouse',
    s3.endpoint = 'http://seaweedfs-s3:8333'
);
```

---

### 2.2 Lakehouse Core

#### Apache Polaris (카탈로그)
| 항목 | 내용 |
|------|------|
| **역할** | 모든 Iceberg 테이블의 메타데이터 중앙 관리 (Unity Catalog 대응) |
| **포트** | 8181 (REST), 8182 (Admin) |
| **저장소** | PostgreSQL (`iceberg_catalog` DB) |
| **연결 엔진** | Trino, Spark, RisingWave, DuckDB 모두 Polaris를 통해 테이블 접근 |
| **현재 상태** | ✅ 실행 중, `iceberg` 카탈로그에 `default` 스키마 존재 |
| **핵심 기능** | RBAC (테이블별 권한), Namespace 관리, 테이블 스냅샷 |

**역할 구조:**
```
Polaris
  └── Catalog: iceberg
        ├── Namespace: default      (일반 데이터)
        ├── Namespace: raw          (원본 수집 데이터 - Bronze)
        ├── Namespace: refined      (정제 데이터 - Silver)  [계획]
        └── Namespace: serving      (분석용 집계 - Gold)    [계획]
```

#### SeaweedFS S3 (스토리지)
| 항목 | 내용 |
|------|------|
| **역할** | 실제 데이터 파일(Parquet) 저장소. HDFS/S3 대체 |
| **포트** | 8333 (S3 API), 8888 (Filer), 9333 (Master) |
| **버킷** | `iceberg` (Iceberg 데이터), `mlflow` (ML 아티팩트) |
| **인증** | accessKey: `datapond`, secretKey: `datapond_dev` |
| **현재 상태** | ✅ 실행 중, S3 API 정상 |

**파일 레이아웃:**
```
s3://iceberg/
  warehouse/
    default/
      {table_name}/
        metadata/
          v1.metadata.json      ← Iceberg 메타데이터
          snap-{id}.avro        ← 스냅샷 매니페스트
        data/
          {partition}/
            {uuid}.parquet      ← 실제 데이터
```

#### Apache Iceberg (테이블 포맷)
| 항목 | 내용 |
|------|------|
| **역할** | 데이터 파일에 ACID, 스키마 진화, Time Travel 기능을 부여하는 오픈 테이블 포맷 |
| **파일 포맷** | Parquet (기본), ORC, Avro |
| **핵심 기능** | ACID 트랜잭션, 파티션 프루닝, 히든 파티셔닝, 시간 여행 쿼리 |
| **메타데이터** | Polaris(카탈로그) + SeaweedFS(실제 파일) 분리 저장 |

---

### 2.3 Query / Compute Layer

#### Trino (OLAP 쿼리 엔진)
| 항목 | 내용 |
|------|------|
| **역할** | Iceberg 테이블에 대한 대화형 SQL 분석. Frontend SQL Lab의 실행 엔진 |
| **포트** | 8080 |
| **카탈로그** | `iceberg` (Polaris 연결), `postgres` (메타DB 직접 쿼리) |
| **현재 상태** | ✅ 실행 중, iceberg.default.t1 테이블 존재 |
| **주요 용도** | Ad-hoc 쿼리, BI 연동, 크로스 테이블 JOIN |

**쿼리 흐름:**
```
Frontend SQL Lab
    → POST /api/queries/execute
    → Backend → Trino HTTP API (port 8080)
    → Trino → Polaris (메타데이터)
    → Trino → SeaweedFS S3 (Parquet 파일 읽기)
    → 결과 반환
```

#### Spark (배치 처리)
| 항목 | 내용 |
|------|------|
| **역할** | 대용량 배치 변환, ML 피처 엔지니어링, 복잡한 ETL |
| **현재 상태** | ⚠️ `values-quicktest.yaml`에서 비활성화 (메모리 이슈) |
| **활성화 조건** | 32GB+ RAM 환경에서 프로덕션 배포 시 |
| **연결** | Polaris REST Catalog를 통해 Iceberg 테이블 접근 |

#### DuckDB (임베디드 분석)
| 항목 | 내용 |
|------|------|
| **역할** | JupyterLab 내부에서 실행되는 임베디드 OLAP 엔진. 별도 서버 없음 |
| **특징** | ~100GB 이하 데이터에서 Spark 없이 직접 Parquet/Iceberg 읽기 |
| **접근 방식** | SeaweedFS S3에서 직접 Parquet 파일 읽기 (Polaris 경유 없음) |
| **용도** | 데이터 사이언티스트 탐색적 분석(EDA), 빠른 프로토타이핑 |

```python
# JupyterLab에서 사용
import duckdb
conn = duckdb.connect()
conn.execute("""
    INSTALL httpfs; LOAD httpfs;
    SET s3_endpoint='seaweedfs-s3:8333';
    SET s3_access_key_id='datapond';
    SET s3_secret_access_key='datapond_dev';
""")
df = conn.execute("""
    SELECT * FROM read_parquet('s3://iceberg/warehouse/default/users/**/*.parquet')
""").df()
```

---

### 2.4 Orchestration & Governance

#### Airflow (워크플로우 오케스트레이션)
| 항목 | 내용 |
|------|------|
| **역할** | 배치 파이프라인 스케줄링 및 의존성 관리 |
| **포트** | 내부 `/airflow` (Ingress 경유) |
| **인증** | airflow / airflow |
| **DataPond 연동** | Backend API를 통해 DAG 트리거 및 상태 조회 |
| **현재 상태** | ✅ 실행 중 |

**파이프라인 패턴:**
```
[Airflow DAG]
  Task 1: Connector Sync (source → Iceberg raw layer)
  Task 2: Trino SQL Transform (raw → refined layer)
  Task 3: Trino SQL Aggregate (refined → serving layer)
  Task 4: OpenMetadata 리니지 업데이트
```

#### OpenMetadata (거버넌스 & 리니지)
| 항목 | 내용 |
|------|------|
| **역할** | 데이터 카탈로그, 컬럼 레벨 리니지, 데이터 품질 관리 |
| **포트** | 8585 |
| **자동 수집** | Trino, Airflow, MLflow에서 메타데이터 자동 크롤링 |
| **현재 상태** | ✅ 실행 중 |

---

### 2.5 Application Layer

#### JupyterLab (데이터 사이언스 환경)
| 항목 | 내용 |
|------|------|
| **역할** | 데이터 탐색, ML 모델 개발, Iceberg 테이블 직접 쿼리 |
| **내장 도구** | DuckDB, pandas, pyarrow, scikit-learn |
| **Iceberg 접근** | DuckDB → S3 직접 읽기 또는 Trino 연결 |

#### MLflow (ML 실험 관리)
| 항목 | 내용 |
|------|------|
| **역할** | 모델 학습 실험 추적, 아티팩트 저장, 모델 레지스트리 |
| **스토리지** | SeaweedFS S3 (`mlflow` 버킷)에 아티팩트 저장 |
| **DB** | PostgreSQL (`mlflow` DB) |

---

## 3. 데이터 경로별 상세 흐름

### Path A: Batch Ingestion (Connector → Iceberg)

```
[현재 - 미완성]
User clicks "Sync Now"
    → POST /api/connectors/{id}/sync
    → trigger_sync() in connectors.py
    → connector.sync_to_iceberg()
    → pandas.read_sql()  ← 여기까지만
    → 데이터 버림
    → "success" 반환  ← 거짓

[목표 - 완성]
User clicks "Sync Now"
    → POST /api/connectors/{id}/sync
    → trigger_sync()
    → connector.sync_to_iceberg()
        ├── pandas.read_sql()                          # 1. Source 읽기
        ├── pa.Table.from_pandas(df)                   # 2. Arrow 변환
        ├── pq.write_to_dataset(s3://iceberg/...)      # 3. S3 Parquet 저장
        ├── trino.execute("CREATE TABLE IF NOT EXISTS") # 4. Iceberg 테이블 생성
        └── trino.execute("INSERT INTO ...")           # 5. 데이터 등록
    → connector_sync_jobs 테이블 업데이트
    → "success" 반환 (진짜)
```

### Path B: Streaming (RisingWave → Iceberg)

```
Kafka/Event Source
    → RisingWave Source (SQL CREATE SOURCE)
    → RisingWave 실시간 처리 (SQL 변환)
    → RisingWave Sink → Iceberg (Parquet 파일)
    → Polaris 카탈로그 자동 업데이트
    → Trino에서 즉시 쿼리 가능
```

### Path C: Analytics (사용자 쿼리)

```
User → Frontend SQL Lab
    → POST /api/queries/execute {"query": "SELECT ..."}
    → Backend → Trino REST API
    → Trino → Polaris (테이블 위치 조회)
    → Trino → SeaweedFS S3 (Parquet 읽기)
    → 결과 → Backend → Frontend
```

### Path D: ML Workflow

```
JupyterLab Notebook
    → DuckDB (S3 직접) 또는 Trino (대용량)
    → 피처 엔지니어링
    → MLflow.start_run()
    → 모델 학습
    → MLflow.log_metrics() / log_artifacts()
    → 아티팩트 → SeaweedFS S3 (mlflow 버킷)
```

### Path E: Orchestrated Pipeline (Airflow)

```
Airflow Scheduler (cron)
    → DAG 실행
    → Task 1: POST /api/connectors/{id}/sync  (수집)
    → Task 2: Trino SQL (Bronze → Silver 변환)
    → Task 3: Trino SQL (Silver → Gold 집계)
    → Task 4: OpenMetadata API (리니지 등록)
```

---

## 4. 데이터 레이어 구조 (Medallion Architecture)

```
Bronze (raw)      → 원본 그대로 수집. 변환 없음. 재처리 기준선.
    iceberg.raw.{source}_{table}

Silver (refined)  → 정제, 타입 변환, 중복 제거, 검증 완료 데이터
    iceberg.refined.{domain}_{entity}

Gold (serving)    → 집계, 비즈니스 지표, BI/ML 소비용
    iceberg.serving.{metric}_{granularity}
```

**현재:** `iceberg.default` 단일 네임스페이스만 사용  
**목표:** Polaris에서 raw / refined / serving 네임스페이스 분리 생성

---

## 5. 구현 현황 Gap 분석

| 기능 | 상태 | 누락 내용 | 우선순위 |
|------|------|-----------|----------|
| Connector 연결 테스트 | ✅ 완료 | — | — |
| Connector CRUD | ✅ 완료 | — | — |
| Source 데이터 읽기 (pandas) | ✅ 완료 | — | — |
| **Iceberg 실제 적재** | ❌ 미구현 | pyarrow→S3→Trino 경로 | **P0** |
| Medallion 네임스페이스 | ❌ 미구현 | Polaris namespace 생성 | P1 |
| Incremental/CDC 동기화 | 🚧 부분 | 마지막 값 추적 로직 | P1 |
| 스키마 자동 진화 | ❌ 미구현 | 컬럼 추가/변경 대응 | P1 |
| 스케줄 기반 자동 Sync | ❌ 미구현 | Airflow DAG 자동 생성 | P2 |
| RisingWave → Iceberg Sink | 🚧 부분 | Sink connector 설정 | P1 |
| OpenMetadata 자동 리니지 | 🚧 부분 | Connector 이벤트 연동 | P2 |
| DuckDB Iceberg 읽기 | 📋 계획 | JupyterLab 설정 가이드 | P2 |

---

## 6. 환경 설정 (Backend Pod 기준)

```bash
# 백엔드에서 사용 가능한 환경변수
S3_ENDPOINT=seaweedfs-s3:8333
S3_ACCESS_KEY=datapond
S3_SECRET_KEY=datapond_dev
ICEBERG_WAREHOUSE=s3a://iceberg/warehouse
POLARIS_HOST=polaris.datapond.svc.cluster.local
POLARIS_PORT=8181
TRINO_SERVICE_HOST=<cluster-ip>
TRINO_SERVICE_PORT=8080

# 사용 가능한 패키지
pyarrow==15.0.2
boto3==1.34.0
trino==0.328.0
pandas==2.1.4
```
