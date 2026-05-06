# DataPond 제품 로드맵 및 기획 방향

**버전**: 1.0.0  
**작성일**: 2026-05-07  
**목적**: Lakehouse 완성도 기준의 개발 우선순위 및 기획 방향 정비

---

## 1. 기획 원칙 재정립

### 핵심 포지셔닝 (변경 불가)

> **"Databricks가 진입할 수 없는 온프렘·에어갭·주권 인프라를 위한 AI-Native Lakehouse"**

DataPond는 "저렴한 Databricks 대안"이 아니다.  
**Databricks 자체가 선택지가 될 수 없는 시장**을 타겟으로 한다.

### 기획의 기준선: "작동하는 Lakehouse"

현재 DataPond는 **Lakehouse 외관**은 갖췄지만 **Lakehouse 본질**이 빠져 있다.

```
현재 상태: 껍데기 Lakehouse
  ✅ Trino, Polaris, SeaweedFS, RisingWave 모두 실행됨
  ✅ UI, API, 커넥터 UI 존재
  ❌ 데이터를 실제로 Iceberg에 쓰지 않음
  ❌ Trino로 수집 데이터를 조회할 수 없음
  ❌ 파이프라인이 있어도 데이터가 흐르지 않음

목표 상태: 진짜 Lakehouse
  → 커넥터로 수집한 데이터가 실제로 Iceberg 테이블에 저장됨
  → Trino SQL로 그 데이터를 조회할 수 있음
  → 데이터가 Bronze → Silver → Gold 레이어로 변환됨
```

---

## 2. 개발 단계별 로드맵

### Phase 0: Lakehouse 파이프라인 완성 (현재 - 즉시)

**목표: 데이터가 실제로 흐르는 Lakehouse**

#### P0-1: Iceberg 실제 적재 구현 ← **지금 당장 해야 할 것**

```
작업: backend/app/connectors/database.py sync_to_iceberg() 완성
방법: pandas → pyarrow → SeaweedFS S3 Parquet → Trino CREATE/INSERT
패키지: pyarrow(✅설치됨), boto3(✅설치됨), trino(✅설치됨)
예상 공수: 1-2일
```

#### P0-2: Medallion 네임스페이스 생성

```
작업: Polaris에 raw / refined / serving 네임스페이스 자동 생성
방법: 백엔드 시작 시 Polaris API 호출로 초기화
예상 공수: 0.5일
```

#### P0-3: 수집 검증 E2E 테스트

```
작업: Connector Sync → Trino SELECT로 데이터 확인까지 자동화
방법: Backend에 /api/connectors/{id}/verify 엔드포인트 추가
예상 공수: 0.5일
```

---

### Phase 1: 엔터프라이즈 필수 기능 (1-2개월)

#### 1-1: Incremental / CDC 동기화
- 마지막 sync 포인트(watermark) 추적
- `WHERE updated_at > last_value` 기반 증분 로드
- Iceberg MERGE INTO로 upsert 지원

#### 1-2: 스케줄 기반 자동 Sync
- 커넥터에 sync_schedule (cron) 필드 추가
- Airflow DAG 자동 생성 및 등록
- 실패 시 알림

#### 1-3: 스키마 자동 진화
- 소스 테이블 컬럼 추가/변경 감지
- Iceberg ALTER TABLE로 자동 반영
- 스키마 변경 이력 OpenMetadata 등록

#### 1-4: RisingWave → Iceberg Sink 완성
- Kafka 소스 → RisingWave → Iceberg sink 설정 자동화
- UI에서 스트리밍 파이프라인 생성 지원

#### 1-5: 보안 하드닝
- TLS 전 서비스 간 통신
- LDAP/Active Directory 인증
- 커넥터 자격증명 Vault 완전 통합

---

### Phase 2: 분석 & 거버넌스 강화 (3-4개월)

#### 2-1: Declarative Pipeline (Delta Live Tables 대응)
- `@pipeline.table` 데코레이터로 변환 정의
- Bronze → Silver → Gold 자동 오케스트레이션
- 데이터 품질 규칙 인라인 정의

#### 2-2: OpenMetadata 완전 통합
- 모든 Connector Sync 이벤트 → 리니지 자동 등록
- 컬럼 레벨 리니지 추적
- 데이터 품질 스코어 자동화

#### 2-3: SQL Lab 강화
- Trino 쿼리 히스토리 & 저장
- 쿼리 성능 프로파일링
- 결과를 Iceberg 테이블로 저장 (CTAS)

#### 2-4: 에어갭 배포 패키지
- 모든 컨테이너 이미지 오프라인 번들
- Helm chart tar.gz 자체 포함 배포
- 내부 레지스트리(Harbor) 연동 가이드

---

### Phase 3: AI-Native 차별화 (5-6개월)

#### 3-1: AI SQL 어시스턴트
- LiteLLM 기반 자연어 → SQL 변환
- 내부 LLM 지원 (외부 API 호출 없음)
- 쿼리 설명, 최적화 제안

#### 3-2: 자동 데이터 프로파일링
- 수집 시 통계 자동 계산 (null rate, cardinality, 분포)
- PII 감지 (온프렘 모델)
- 이상 감지 알림

#### 3-3: AI 기반 파이프라인 생성
- "이 DB 테이블을 일별로 집계해줘" → Airflow DAG 자동 생성
- 스키마 변경 자동 대응 코드 생성

---

## 3. Data Engineering 역할별 기능 매핑

### 역할 1: Data Engineer (파이프라인 구축)

**주요 작업**: 소스 시스템 연결, ETL 파이프라인 구축, 스케줄링

```
DataPond에서 제공해야 할 것:
  ✅ Connector 생성 및 관리 (UI)
  ❌ 실제 Iceberg 적재 (P0 - 미구현)
  🚧 Airflow 파이프라인 UI (부분)
  📋 Incremental sync / CDC
  📋 스키마 진화 자동화
  📋 파이프라인 의존성 시각화
```

**DataPond의 차별점**:  
Airflow DAG 직접 작성 없이 UI에서 커넥터 → 변환 → 스케줄을 선언적으로 정의

---

### 역할 2: Analytics Engineer (데이터 모델링)

**주요 작업**: raw 데이터를 분석 가능한 형태로 변환, 지표 정의

```
DataPond에서 제공해야 할 것:
  ✅ Trino SQL Lab
  🚧 Medallion 레이어 구조 (네임스페이스 분리 필요)
  📋 CTAS (CREATE TABLE AS SELECT) UI
  📋 dbt 통합 또는 동등 기능
  📋 데이터 계약 (schema 검증)
```

**DataPond의 차별점**:  
Trino + Iceberg + Polaris로 기업 내부에서 dbt 없이 변환 레이어 관리

---

### 역할 3: Data Scientist (탐색 & 모델링)

**주요 작업**: EDA, 피처 엔지니어링, 모델 학습

```
DataPond에서 제공해야 할 것:
  ✅ JupyterLab
  ✅ MLflow 실험 추적
  🚧 DuckDB → Iceberg 직접 읽기 (설정 가이드 필요)
  📋 피처 스토어 (장기)
  📋 모델 서빙 (장기)
```

**DataPond의 차별점**:  
내부망에서 Claude/GPT-4/Llama 모두 사용 가능 (LiteLLM), 외부 API 호출 없음

---

### 역할 4: Data Platform Engineer (인프라 운영)

**주요 작업**: 플랫폼 배포, 모니터링, 성능 튜닝

```
DataPond에서 제공해야 할 것:
  ✅ Helm 기반 K8s 배포
  ✅ Services 모니터링 UI
  🚧 메트릭 (Prometheus/Grafana 미연동)
  📋 에어갭 배포 번들
  📋 LDAP/SSO 인증
  📋 자동 스케일링 정책
```

**DataPond의 차별점**:  
단일 Helm chart로 전체 스택 배포. 온프렘에서 단일 운영팀이 전체 플랫폼 관리 가능

---

### 역할 5: Data Governance Officer (거버넌스)

**주요 작업**: 데이터 카탈로그, 리니지, 접근 제어, 감사

```
DataPond에서 제공해야 할 것:
  ✅ OpenMetadata (카탈로그, 리니지)
  ✅ Apache Polaris (RBAC)
  🚧 자동 리니지 수집 (Connector 이벤트 연동 필요)
  📋 컬럼 레벨 마스킹
  📋 감사 로그 완전 통합
  📋 규정 준수 리포트 (ISMS-P, GDPR)
```

---

## 4. 즉시 실행 가능한 작업 목록

### 이번 주 (P0 — Lakehouse 기능 완성)

1. **`sync_to_iceberg()` 실제 구현** — pyarrow → S3 → Trino
2. **Polaris namespace 초기화** — raw/refined/serving 자동 생성
3. **E2E 검증 엔드포인트** — sync 후 Trino로 row count 확인

### 다음 주 (P1 — 운영 가능성)

4. **Incremental sync watermark** 추적
5. **Connector 스케줄 필드** 추가 + Airflow 자동 DAG 생성
6. **DuckDB ↔ Iceberg** JupyterLab 연결 가이드 및 설정

### 이번 달 (P1 — 엔터프라이즈 준비)

7. **스키마 자동 진화** (컬럼 추가 감지 → Iceberg ALTER TABLE)
8. **에어갭 번들** scripts/bundle-airgap.sh 완성
9. **LDAP 인증** 기본 구현

---

## 5. "작동하는 Lakehouse" 체크리스트

엔터프라이즈 고객에게 데모할 수 있는 최소 기준:

```
[ ] PostgreSQL 테이블을 UI에서 클릭 한 번으로 Iceberg에 적재
[ ] Trino SQL Lab에서 수집된 데이터 조회
[ ] 동일 데이터를 JupyterLab DuckDB에서도 조회
[ ] Airflow에서 스케줄 기반 자동 sync
[ ] OpenMetadata에서 데이터 리니지 확인
[ ] 전체 플로우가 외부 인터넷 연결 없이 동작
```

현재 이 체크리스트에서 **첫 번째 항목조차 미완성**이다.  
P0 구현 완료가 모든 것의 선행 조건이다.
