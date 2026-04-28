# RisingWave Integration Guide

**작성일**: 2026-04-29  
**버전**: 2.2.0  
**대상**: 개발자, 데이터 엔지니어, 아키텍트

---

## 📋 목차

1. [개요](#개요)
2. [RisingWave란?](#risingwave란)
3. [아키텍처](#아키텍처)
4. [설치 및 설정](#설치-및-설정)
5. [사용 방법](#사용-방법)
6. [실시간 스트리밍 예제](#실시간-스트리밍-예제)
7. [성능 최적화](#성능-최적화)
8. [문제 해결](#문제-해결)

---

## 개요

RisingWave는 DataPond의 **실시간 스트리밍 SQL 처리 엔진**으로 통합되었습니다.

### 주요 특징

```yaml
핵심 가치:
  - Kafka + Flink 대체 (단일 시스템)
  - PostgreSQL 호환 인터페이스
  - 운영 복잡도 50% 감소
  - 실시간 Materialized Views
  - 정확한 한 번 처리 (Exactly-Once)

기술 스펙:
  - 언어: Rust (고성능, 메모리 안전)
  - 라이선스: Apache 2.0
  - 프로토콜: PostgreSQL Wire Protocol
  - 상태 저장: S3 (SeaweedFS)
  - 메타데이터: PostgreSQL
```

### Kafka + Flink vs RisingWave

| 항목 | Kafka + Flink | RisingWave |
|------|--------------|------------|
| **설치 복잡도** | 높음 (2개 클러스터) | 낮음 (단일 시스템) |
| **운영 복잡도** | 높음 (ZooKeeper 필요) | 낮음 (Kubernetes 네이티브) |
| **SQL 지원** | Flink SQL (제한적) | PostgreSQL 호환 (완전) |
| **상태 관리** | RocksDB (로컬) | S3 (분산, 영구) |
| **리소스 사용** | 높음 | 중간 |
| **학습 곡선** | 가파름 | 완만함 (SQL 사용) |

---

## RisingWave란?

### 정의

RisingWave는 **Cloud-native Streaming Database**입니다:
- **스트리밍 처리**: Kafka 토픽을 SQL로 실시간 처리
- **Materialized Views**: 쿼리 결과를 자동으로 유지
- **PostgreSQL 호환**: psql, JDBC, Python psycopg2 사용 가능
- **S3 기반 스토리지**: SeaweedFS와 완벽 통합

### 사용 사례

```yaml
1. 실시간 대시보드:
   - 웹/앱 이벤트 실시간 집계
   - 초당 업데이트되는 KPI 대시보드
   - 예: "최근 1분간 페이지뷰 Top 10"

2. 실시간 추천:
   - 사용자 행동 기반 즉시 추천
   - 개인화 피드 생성
   - 예: "이 상품을 본 고객이 함께 본 상품"

3. 이상 탐지:
   - 실시간 이상 거래 감지
   - 시스템 메트릭 모니터링
   - 예: "5분내 로그인 실패 10회 이상"

4. ETL 파이프라인:
   - 데이터 정제 및 변환
   - 다중 소스 통합
   - 예: "Kafka → RisingWave → Iceberg"
```

---

## 아키텍처

### DataPond 내 RisingWave 위치

```
┌─────────────────────────────────────────────────────────┐
│                    Ingress (Traefik)                     │
└────────────────────┬────────────────────────────────────┘
                     │
     ┌───────────────┼───────────────┬──────────────┐
     │               │               │              │
┌────▼───┐    ┌──────▼──────┐   ┌───▼────┐   ┌────▼─────┐
│JupyterLab│  │  RisingWave  │   │ Trino  │   │  Spark   │
│          │  │  (Streaming) │   │ (OLAP) │   │  (Batch) │
└────┬─────┘  └──────┬───────┘   └───┬────┘   └────┬─────┘
     │               │               │              │
     └───────────────┼───────────────┴──────────────┘
                     │
          ┌──────────▼──────────┐
          │  SeaweedFS (S3)     │
          │  + Apache Iceberg   │
          └─────────────────────┘

데이터 흐름:
1. 실시간 이벤트 → RisingWave (Streaming SQL)
2. Materialized Views → Iceberg 테이블
3. Trino/Spark → Iceberg 분석
4. JupyterLab → 모든 시스템 쿼리
```

### RisingWave 컴포넌트

```yaml
Meta Node (메타데이터 관리):
  - 역할: 클러스터 조정, 스케줄링
  - Replicas: 1 (dev), 3 (prod)
  - 저장소: PostgreSQL
  - 포트: 5690 (service), 5691 (dashboard)

Frontend (SQL 진입점):
  - 역할: SQL 파싱, 쿼리 플래닝
  - Replicas: 2 (dev: 1, prod: 3)
  - 프로토콜: PostgreSQL Wire Protocol
  - 포트: 4566

Compute Node (스트림 처리):
  - 역할: 실제 데이터 처리
  - Replicas: 2 (dev: 1, prod: 5)
  - 상태 저장: SeaweedFS S3
  - 포트: 5688

Compactor (스토리지 최적화):
  - 역할: SSTable 압축, 정리
  - Replicas: 1 (dev: 1, prod: 2)
  - 포트: 6660
```

---

## 설치 및 설정

### Prerequisites

```bash
# 1. PostgreSQL 준비 (자동 생성됨)
# RisingWave 메타데이터용 DB: risingwave

# 2. SeaweedFS S3 준비 (자동 연결)
# Bucket: risingwave (자동 생성)

# 3. Helm values 확인
helm show values ./helm/datapond | grep -A 50 risingwave
```

### 배포

```bash
# 1. values.yaml에서 활성화 확인
cat helm/datapond/values.yaml | grep -A 5 "risingwave:"
# risingwave:
#   enabled: true

# 2. Helm으로 배포 (기본적으로 포함됨)
helm install datapond ./helm/datapond \
  -n datapond \
  --create-namespace

# 3. 배포 확인
kubectl get pods -n datapond | grep risingwave
# risingwave-meta-0          1/1  Running
# risingwave-frontend-xxx    1/1  Running
# risingwave-compute-0       1/1  Running
# risingwave-compactor-xxx   1/1  Running

# 4. 서비스 확인
kubectl get svc -n datapond | grep risingwave
# risingwave-meta       ClusterIP None      5690,5691
# risingwave-frontend   ClusterIP 10.x.x.x  4566
```

### 접속 방법

#### 1. 클러스터 내부에서 (다른 Pod)

```bash
# PostgreSQL 클라이언트로 연결
psql -h risingwave-frontend -p 4566 -U root

# Python에서
import psycopg2
conn = psycopg2.connect(
    host="risingwave-frontend",
    port=4566,
    user="root",
    database="dev"
)
```

#### 2. 로컬에서 (Port Forward)

```bash
# 포트 포워딩
kubectl port-forward -n datapond svc/risingwave-frontend 4566:4566

# 별도 터미널에서 연결
psql -h localhost -p 4566 -U root -d dev
```

#### 3. Ingress를 통해 (대시보드)

```bash
# 브라우저에서 접속
http://datapond.local/risingwave

# Meta Node 대시보드:
# - 클러스터 상태
# - Materialized Views 목록
# - 쿼리 실행 계획
```

---

## 사용 방법

### 1. 기본 SQL 쿼리

```sql
-- RisingWave 연결
\c dev

-- 테이블 목록
\dt

-- 간단한 쿼리
SELECT version();
```

### 2. 스트림 생성 (Source)

```sql
-- Kafka 토픽을 RisingWave 테이블로 매핑
CREATE SOURCE user_events (
    user_id INT,
    event_type VARCHAR,
    event_time TIMESTAMP
)
WITH (
    connector = 'kafka',
    topic = 'user_events',
    properties.bootstrap.server = 'kafka:9092',
    scan.startup.mode = 'earliest'
)
FORMAT PLAIN ENCODE JSON;

-- 데이터 확인
SELECT * FROM user_events LIMIT 10;
```

### 3. Materialized View 생성

```sql
-- 실시간 집계 뷰
CREATE MATERIALIZED VIEW hourly_events AS
SELECT
    DATE_TRUNC('hour', event_time) AS hour,
    event_type,
    COUNT(*) AS event_count,
    COUNT(DISTINCT user_id) AS unique_users
FROM user_events
GROUP BY DATE_TRUNC('hour', event_time), event_type;

-- 뷰는 자동으로 업데이트됨
SELECT * FROM hourly_events
ORDER BY hour DESC
LIMIT 24;
```

### 4. Sink로 Iceberg 테이블 연동

```sql
-- RisingWave 결과를 Iceberg로 내보내기
CREATE SINK iceberg_hourly_events
FROM hourly_events
WITH (
    connector = 'iceberg',
    type = 'append-only',
    force_append_only = 'true',
    s3.endpoint = 'http://seaweedfs-s3:8333',
    s3.region = 'us-east-1',
    s3.path.style.access = 'true',
    catalog.name = 'iceberg',
    catalog.type = 'rest',
    catalog.uri = 'http://polaris:8181/api/catalog/v1',
    database.name = 'analytics',
    table.name = 'hourly_events'
);

-- 이제 Trino/Spark에서 iceberg.analytics.hourly_events 쿼리 가능
```

---

## 실시간 스트리밍 예제

### Lab 8: 실시간 웹 이벤트 분석

```sql
-- 1. 웹 이벤트 스트림 생성
CREATE SOURCE web_events (
    session_id VARCHAR,
    user_id INT,
    page_url VARCHAR,
    action VARCHAR,
    timestamp TIMESTAMP
)
WITH (
    connector = 'kafka',
    topic = 'web_events',
    properties.bootstrap.server = 'kafka:9092'
)
FORMAT PLAIN ENCODE JSON;

-- 2. 실시간 페이지뷰 Top 10
CREATE MATERIALIZED VIEW top_pages_1min AS
SELECT
    page_url,
    COUNT(*) AS views,
    COUNT(DISTINCT user_id) AS unique_users,
    MAX(timestamp) AS last_view
FROM web_events
WHERE timestamp > NOW() - INTERVAL '1 minute'
GROUP BY page_url
ORDER BY views DESC
LIMIT 10;

-- 3. 실시간 조회 (항상 최신 데이터)
SELECT * FROM top_pages_1min;

-- 4. 이상 탐지: 5분내 동일 IP에서 100회 이상 요청
CREATE MATERIALIZED VIEW suspicious_activity AS
SELECT
    user_id,
    COUNT(*) AS request_count,
    ARRAY_AGG(page_url) AS accessed_pages,
    MIN(timestamp) AS first_seen,
    MAX(timestamp) AS last_seen
FROM web_events
WHERE timestamp > NOW() - INTERVAL '5 minutes'
GROUP BY user_id
HAVING COUNT(*) > 100;

-- 5. 알림: suspicious_activity에 새 행이 추가되면 알림
SELECT * FROM suspicious_activity;
```

### Python에서 RisingWave 사용

```python
import psycopg2
import time

# RisingWave 연결
conn = psycopg2.connect(
    host="risingwave-frontend",
    port=4566,
    user="root",
    database="dev"
)
cur = conn.cursor()

# 실시간 Top 10 페이지 (매초 업데이트)
while True:
    cur.execute("SELECT * FROM top_pages_1min")
    results = cur.fetchall()
    
    print(f"\n=== Top Pages at {time.strftime('%H:%M:%S')} ===")
    for row in results:
        print(f"{row[0]}: {row[1]} views ({row[2]} users)")
    
    time.sleep(1)  # 1초마다 조회

cur.close()
conn.close()
```

### JupyterLab에서 RisingWave 사용

```python
# Notebook 셀
import pandas as pd
import psycopg2

# RisingWave 연결
conn = psycopg2.connect(
    host="risingwave-frontend",
    port=4566,
    user="root",
    database="dev"
)

# Materialized View를 DataFrame으로
df = pd.read_sql_query(
    "SELECT * FROM hourly_events ORDER BY hour DESC LIMIT 100",
    conn
)

# 시각화
import matplotlib.pyplot as plt

df.pivot(index='hour', columns='event_type', values='event_count').plot(
    kind='line',
    figsize=(15, 6),
    title='Hourly Events by Type (Real-time)'
)
plt.show()

conn.close()
```

---

## 성능 최적화

### 1. Parallelism 조정

```yaml
# values.yaml
risingwave:
  compute:
    replicas: 5  # 더 많은 compute node = 더 높은 처리량
  
  # 각 compute node의 리소스 증가
  compute:
    resources:
      requests:
        cpu: 4000m      # 4 CPU
        memory: 8Gi     # 8GB RAM
```

### 2. Materialized View 최적화

```sql
-- BAD: 전체 히스토리 저장
CREATE MATERIALIZED VIEW all_events AS
SELECT * FROM web_events;  -- 무한정 증가

-- GOOD: 시간 윈도우 사용
CREATE MATERIALIZED VIEW recent_events AS
SELECT * FROM web_events
WHERE timestamp > NOW() - INTERVAL '1 hour';  -- 1시간만 유지

-- BETTER: 집계로 크기 축소
CREATE MATERIALIZED VIEW hourly_summary AS
SELECT
    DATE_TRUNC('hour', timestamp) AS hour,
    COUNT(*) AS count
FROM web_events
GROUP BY DATE_TRUNC('hour', timestamp);
```

### 3. Watermark 설정 (Late Data 처리)

```sql
-- Watermark: 늦게 도착한 데이터 허용 범위
CREATE SOURCE events_with_watermark (
    event_id INT,
    event_time TIMESTAMP,
    WATERMARK FOR event_time AS event_time - INTERVAL '5 minutes'
)
WITH (connector = 'kafka', ...);

-- 5분 이상 늦은 데이터는 무시됨
```

### 4. Index 생성 (빠른 조회)

```sql
-- Primary key 설정 (자동 인덱싱)
CREATE TABLE events (
    event_id INT PRIMARY KEY,
    user_id INT,
    timestamp TIMESTAMP
);

-- 자주 필터링하는 컬럼에 인덱스
CREATE INDEX idx_user_id ON events(user_id);
```

---

## 문제 해결

### 1. Pod가 시작 안 됨

```bash
# 로그 확인
kubectl logs -n datapond risingwave-meta-0
kubectl logs -n datapond risingwave-frontend-xxx

# 일반적인 원인:
# - PostgreSQL 미준비 → postgres pod 확인
# - SeaweedFS 미준비 → seaweedfs-s3 pod 확인
# - 메모리 부족 → values.yaml 리소스 감소
```

### 2. 연결 오류

```bash
# Frontend 서비스 확인
kubectl get svc -n datapond risingwave-frontend

# 포트 포워딩으로 직접 테스트
kubectl port-forward -n datapond svc/risingwave-frontend 4566:4566
psql -h localhost -p 4566 -U root -d dev

# Meta Node 확인
kubectl port-forward -n datapond risingwave-meta-0 5691:5691
# 브라우저: http://localhost:5691
```

### 3. 느린 쿼리

```sql
-- 쿼리 실행 계획 확인
EXPLAIN SELECT * FROM my_view;

-- Materialized View 상태 확인
SELECT * FROM rw_catalog.rw_materialized_views;

-- 통계 확인
SELECT * FROM rw_catalog.rw_table_stats;
```

### 4. 상태 저장소 문제

```bash
# S3 (SeaweedFS) 버킷 확인
kubectl exec -it -n datapond seaweedfs-master-0 -- /bin/sh
weed shell
s3.bucket.list

# RisingWave 버킷 수동 생성
s3.bucket.create -name risingwave

# Meta Node 로그에서 S3 연결 확인
kubectl logs -n datapond risingwave-meta-0 | grep -i s3
```

### 5. Meta Node 리더 선출 실패 (HA)

```bash
# Meta Node 상태 확인 (prod에서만 해당)
kubectl get pods -n datapond -l component=meta

# 리더 확인
kubectl logs -n datapond risingwave-meta-0 | grep -i leader

# 강제 재시작
kubectl delete pod -n datapond risingwave-meta-0
# StatefulSet이 자동으로 재생성
```

---

## 고급 기능

### 1. Temporal Join (시간 기반 조인)

```sql
-- 주문과 결제를 시간 기준으로 조인
CREATE MATERIALIZED VIEW order_with_payment AS
SELECT
    o.order_id,
    o.user_id,
    o.order_time,
    p.payment_id,
    p.payment_time,
    p.amount
FROM orders o
LEFT JOIN payments FOR SYSTEM_TIME AS OF o.order_time AS p
    ON o.order_id = p.order_id;
```

### 2. Window Function (이동 평균)

```sql
-- 1분 슬라이딩 윈도우로 평균 계산
CREATE MATERIALIZED VIEW moving_avg AS
SELECT
    user_id,
    AVG(value) OVER (
        PARTITION BY user_id
        ORDER BY timestamp
        ROWS BETWEEN 60 PRECEDING AND CURRENT ROW
    ) AS moving_avg_1min
FROM sensor_data;
```

### 3. CDC (Change Data Capture)

```sql
-- PostgreSQL 테이블 변경 스트리밍
CREATE SOURCE postgres_cdc (
    id INT,
    name VARCHAR,
    updated_at TIMESTAMP
)
WITH (
    connector = 'postgres-cdc',
    hostname = 'postgres',
    port = '5432',
    username = 'datapond',
    password = 'datapond_password',
    database.name = 'datapond',
    schema.name = 'public',
    table.name = 'users'
);

-- 변경 사항 자동 반영
SELECT * FROM postgres_cdc;
```

---

## 참고 자료

### 공식 문서
- [RisingWave 공식 사이트](https://risingwave.com)
- [GitHub Repository](https://github.com/risingwavelabs/risingwave)
- [SQL Reference](https://docs.risingwave.com/sql)

### DataPond 관련 문서
- [LAB_GUIDE.md](LAB_GUIDE.md) - Lab 8: RisingWave 실습
- [ARCHITECTURE.md](ARCHITECTURE.md) - 전체 아키텍처
- [STRATEGIC_COMPONENTS_INTEGRATION.md](STRATEGIC_COMPONENTS_INTEGRATION.md) - 통합 전략

### 커뮤니티
- [RisingWave Slack](https://risingwave.com/slack)
- [DataPond Discord](https://discord.gg/datapond)

---

## 요약

RisingWave는 DataPond에 **실시간 스트리밍 SQL** 기능을 추가하여:

✅ **Kafka + Flink를 단일 시스템으로 대체**  
✅ **PostgreSQL 호환 인터페이스로 학습 곡선 완화**  
✅ **SeaweedFS + Iceberg와 완벽 통합**  
✅ **운영 복잡도 50% 감소**

**다음 단계**: [LAB_GUIDE.md](LAB_GUIDE.md)의 Lab 8에서 실습을 시작하세요!

---

**작성**: DataPond Team  
**버전**: 2.2.0  
**최종 수정**: 2026-04-29
