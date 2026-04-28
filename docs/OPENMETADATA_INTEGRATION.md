# OpenMetadata Integration Guide

**작성일**: 2026-04-29  
**버전**: 2.3.0  
**대상**: 데이터 엔지니어, 데이터 거버넌스 담당자, 아키텍트

---

## 📋 목차

1. [개요](#개요)
2. [OpenMetadata란?](#openmetadata란)
3. [아키텍처](#아키텍처)
4. [설치 및 설정](#설치-및-설정)
5. [데이터 소스 연결](#데이터-소스-연결)
6. [데이터 Lineage 추적](#데이터-lineage-추적)
7. [데이터 품질 관리](#데이터-품질-관리)
8. [거버넌스 및 정책](#거버넌스-및-정책)
9. [문제 해결](#문제-해결)

---

## 개요

OpenMetadata는 DataPond의 **중앙집중식 데이터 카탈로그 및 거버넌스 플랫폼**으로 통합되었습니다.

### 주요 특징

```yaml
핵심 가치:
  - 자동 데이터 디스커버리 (Trino, Spark, Airflow, PostgreSQL)
  - End-to-End 데이터 Lineage 추적
  - 데이터 품질 모니터링 및 알림
  - 거버넌스 정책 및 접근 제어
  - 협업을 위한 메타데이터 주석

기술 스펙:
  - 언어: Java (Spring Boot)
  - 라이선스: Apache 2.0
  - 검색: Elasticsearch
  - 메타데이터 저장: PostgreSQL
  - API: RESTful + GraphQL
```

### 경쟁 제품 비교

| 항목 | Collibra | Alation | OpenMetadata (DataPond) |
|------|-----------|---------|------------------------|
| **라이선스** | 상용 (비공개) | 상용 (비공개) | 오픈소스 (Apache 2.0) |
| **연간 비용** | $50K-$200K+ | $30K-$100K+ | $0 (자체 호스팅) |
| **데이터 Lineage** | ✅ (수동 + 자동) | ✅ (수동 + 자동) | ✅ (자동, 실시간) |
| **데이터 품질** | ✅ 고급 | ✅ 고급 | ✅ 기본 + 확장 가능 |
| **API 접근** | 제한적 | 제한적 | 완전 오픈 (REST + GraphQL) |
| **커스터마이징** | 제한적 | 제한적 | 완전 자유 (오픈소스) |
| **배포** | SaaS Only | SaaS + On-prem | K8s (On-prem, Cloud) |

---

## OpenMetadata란?

### 정의

OpenMetadata는 **오픈소스 메타데이터 플랫폼**으로:
- **데이터 카탈로그**: 모든 데이터 자산을 한 곳에서 검색
- **데이터 Lineage**: 데이터 흐름을 시각적으로 추적
- **데이터 품질**: 자동 품질 검사 및 알림
- **협업**: 팀간 메타데이터 공유 및 문서화

### 사용 사례

```yaml
1. 데이터 디스커버리:
   - "고객 이메일 주소를 포함하는 모든 테이블 찾기"
   - "최근 30일간 업데이트되지 않은 테이블 찾기"
   - "민감한 PII 데이터를 포함하는 컬럼 찾기"

2. 영향 분석 (Impact Analysis):
   - "이 테이블을 삭제하면 어떤 대시보드가 영향을 받는가?"
   - "이 컬럼을 변경하면 어떤 ML 모델이 영향을 받는가?"
   - "이 Airflow DAG가 생성하는 테이블은?"

3. 데이터 품질 모니터링:
   - "테이블 행 수가 갑자기 줄어들면 알림"
   - "NULL 값이 10% 이상이면 경고"
   - "중복 데이터가 발견되면 Slack 알림"

4. 규정 준수 (Compliance):
   - "GDPR 대상 개인 정보 자동 태깅"
   - "민감한 데이터 접근 로그 감사"
   - "데이터 보유 정책 자동 적용"
```

---

## 아키텍처

### DataPond 내 OpenMetadata 위치

```
┌─────────────────────────────────────────────────────────┐
│                    Ingress (Traefik)                     │
└────────────────────┬────────────────────────────────────┘
                     │
     ┌───────────────┼─────────────────────────┐
     │               │                         │
┌────▼────────┐ ┌───▼──────────┐    ┌────────▼─────────┐
│ OpenMetadata│ │  JupyterLab   │    │  Airflow (DAGs)  │
│  (Catalog)  │ │  RisingWave   │    │  MLflow (Models) │
└────┬────────┘ │  Trino, Spark │    └────────┬─────────┘
     │          └───┬───────────┘             │
     │              │                         │
     └──────────────┼─────────────────────────┘
                    │
         ┌──────────▼──────────┐
         │  SeaweedFS (S3)     │
         │  + Apache Iceberg   │
         │  + PostgreSQL       │
         └─────────────────────┘

메타데이터 흐름:
1. OpenMetadata → 자동 메타데이터 수집
2. Trino/Spark 쿼리 → Lineage 추적
3. Airflow DAG 실행 → 파이프라인 추적
4. 데이터 품질 검사 → 알림 발송
```

### OpenMetadata 컴포넌트

```yaml
OpenMetadata Server:
  - 역할: 메인 애플리케이션, API 서버
  - Replicas: 1 (dev), 2 (prod)
  - 저장소: PostgreSQL (메타데이터)
  - 포트: 8585 (UI + API), 8586 (Admin)

Elasticsearch:
  - 역할: 검색 인덱스, 전문 검색
  - Replicas: 1 (dev), 3 (prod)
  - 포트: 9200 (HTTP), 9300 (Transport)
  - 저장소: PersistentVolume

Connectors (Ingestion):
  - Trino: Iceberg 테이블 메타데이터
  - PostgreSQL: 관계형 테이블
  - Airflow: DAG 및 파이프라인
  - Spark: 데이터 처리 작업
```

---

## 설치 및 설정

### Prerequisites

```bash
# 1. PostgreSQL 준비 (자동 생성됨)
# OpenMetadata 메타데이터용 DB: openmetadata_catalog

# 2. Elasticsearch 준비 (자동 배포)
# 검색 인덱스 저장소

# 3. Helm values 확인
helm show values ./helm/datapond | grep -A 80 openmetadata
```

### 배포

```bash
# 1. values.yaml에서 활성화 확인
cat helm/datapond/values.yaml | grep -A 5 "openmetadata:"
# openmetadata:
#   enabled: true

# 2. Helm으로 배포 (기본적으로 포함됨)
helm install datapond ./helm/datapond \
  -n datapond \
  --create-namespace

# 3. 배포 확인
kubectl get pods -n datapond | grep openmetadata
# openmetadata-server-xxx        1/1  Running
# openmetadata-elasticsearch-0   1/1  Running

# 4. 서비스 확인
kubectl get svc -n datapond | grep openmetadata
# openmetadata-server        ClusterIP  10.x.x.x  8585,8586
# openmetadata-elasticsearch ClusterIP  None      9200,9300
```

### 접속 방법

#### 1. Ingress를 통해 (권장)

```bash
# 브라우저에서 접속
http://datapond.local/openmetadata

# 로그인 (no-auth 모드)
# 바로 접속 가능 (프로덕션에서는 SSO 사용)
```

#### 2. 로컬에서 (Port Forward)

```bash
# 포트 포워딩
kubectl port-forward -n datapond svc/openmetadata-server 8585:8585

# 별도 터미널에서 브라우저 열기
open http://localhost:8585
```

#### 3. API 사용

```bash
# RESTful API
curl http://datapond.local/openmetadata/api/v1/tables

# Python SDK
pip install openmetadata-ingestion
```

---

## 데이터 소스 연결

### 1. Trino 연결 (Iceberg 테이블)

OpenMetadata UI에서:

```
1. Settings → Services → Add Database Service
2. Service Type: Trino
3. 설정:
   - Name: datapond-trino
   - Host: trino
   - Port: 8080
   - Catalog: iceberg
   - Schema: analytics
4. Test Connection → Save
5. Add Ingestion → Schedule (매일 2AM)
```

또는 kubectl로 자동화:

```bash
kubectl exec -it -n datapond <openmetadata-server-pod> -- bash

# Trino 커넥터 등록
curl -X POST http://localhost:8585/api/v1/services/databaseServices \
  -H 'Content-Type: application/json' \
  -d @/opt/openmetadata/conf/trino-connector.json

# 메타데이터 수집 즉시 실행
curl -X POST http://localhost:8585/api/v1/services/ingestionPipelines/trigger/trino-ingestion
```

### 2. PostgreSQL 연결

```
1. Add Database Service
2. Service Type: Postgres
3. 설정:
   - Name: datapond-postgres
   - Host: postgres
   - Port: 5432
   - Database: datapond
   - Username: datapond
   - Password: ***
   - Schema Filter: public
4. Test Connection → Save
5. Add Ingestion (매일)
```

### 3. Airflow 연결

```
1. Add Pipeline Service
2. Service Type: Airflow
3. 설정:
   - Name: datapond-airflow
   - Host: http://airflow:8080
   - Username: admin
   - Password: admin
4. Test Connection → Save
5. Add Ingestion (매시간)
```

### 4. 자동 메타데이터 수집 확인

```bash
# UI에서 확인
http://datapond.local/openmetadata/explore/tables

# API로 확인
curl http://datapond.local/openmetadata/api/v1/tables?limit=100

# 테이블 수 카운트
curl http://datapond.local/openmetadata/api/v1/tables?limit=1 | jq '.paging.total'
```

---

## 데이터 Lineage 추적

### 자동 Lineage 생성

OpenMetadata는 다음에서 자동으로 Lineage를 추적합니다:

```yaml
Trino 쿼리:
  - CREATE TABLE ... AS SELECT ...
  - INSERT INTO ... SELECT ...
  - 자동으로 소스/타겟 테이블 연결

Spark 작업:
  - DataFrame 변환
  - Iceberg writeTo/readFrom
  - 자동 Lineage 그래프 생성

Airflow DAG:
  - Task 간 의존성
  - XCom 데이터 전달
  - 파이프라인 시각화
```

### Lineage 조회 예제

#### UI에서 조회

```
1. Explore → Tables → 테이블 선택
2. Lineage 탭 클릭
3. 상위/하위 테이블 시각화 확인
4. 확대/축소로 전체 흐름 파악
```

#### API로 조회

```bash
# 특정 테이블의 Lineage 조회
curl http://datapond.local/openmetadata/api/v1/lineage/table/fqn/iceberg.analytics.users \
  | jq '.upstreamEdges, .downstreamEdges'

# Python SDK
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.generated.schema.entity.data.table import Table

server_config = OpenMetadataConnection(hostPort="http://localhost:8585")
metadata = OpenMetadata(server_config)

# 테이블 FQN (Fully Qualified Name)
table_fqn = "datapond-trino.iceberg.analytics.users"

# Lineage 조회
lineage = metadata.get_lineage_by_name(
    entity=Table,
    fqn=table_fqn,
    up_depth=3,  # 상위 3단계
    down_depth=3  # 하위 3단계
)

print("Upstream:", lineage.upstreamEdges)
print("Downstream:", lineage.downstreamEdges)
```

### 수동 Lineage 추가

자동 추적이 안 되는 경우 수동으로 추가:

```python
from metadata.generated.schema.api.lineage.addLineage import AddLineageRequest
from metadata.generated.schema.type.entityReference import EntityReference

# 소스 테이블
source = EntityReference(
    id="source-table-uuid",
    type="table"
)

# 타겟 테이블
target = EntityReference(
    id="target-table-uuid",
    type="table"
)

# Lineage 추가
lineage_request = AddLineageRequest(
    edge={"fromEntity": source, "toEntity": target}
)

metadata.add_lineage(lineage_request)
```

---

## 데이터 품질 관리

### 데이터 품질 테스트 정의

#### UI에서 설정

```
1. Explore → Tables → 테이블 선택
2. Profiler & Data Quality 탭
3. Add Test 클릭
4. 테스트 유형 선택:
   - Table Row Count (행 수)
   - Column Values Not Null (NULL 체크)
   - Column Values Unique (중복 체크)
   - Column Values in Range (범위 체크)
   - Custom SQL Query (커스텀 쿼리)
5. 임계값 설정
6. 알림 설정 (Slack, Email)
```

#### YAML로 정의

```yaml
# data-quality-tests.yaml
tests:
  - table: iceberg.analytics.users
    tests:
      - name: "user_count_minimum"
        testType: "tableRowCountToBeBetween"
        params:
          minValue: 1000
          maxValue: 10000000
        severity: "critical"
        
      - name: "email_not_null"
        column: "email"
        testType: "columnValuesToBeNotNull"
        severity: "critical"
        
      - name: "age_in_range"
        column: "age"
        testType: "columnValuesToBeBetween"
        params:
          minValue: 0
          maxValue: 120
        severity: "warning"
        
      - name: "country_code_valid"
        column: "country"
        testType: "columnValuesToBeInSet"
        params:
          allowedValues: ["KR", "US", "JP", "CN", "UK", "DE"]
        severity: "error"
```

#### API로 테스트 생성

```bash
curl -X POST http://datapond.local/openmetadata/api/v1/dataQuality/testCases \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "user_email_not_null",
    "entityLink": "<#E::table::iceberg.analytics.users>",
    "testDefinition": "columnValuesToBeNotNull",
    "parameterValues": [
      {"name": "columnName", "value": "email"}
    ],
    "testSuite": "users_table_test_suite"
  }'
```

### 테스트 실행 및 모니터링

```bash
# 즉시 실행
curl -X POST http://datapond.local/openmetadata/api/v1/dataQuality/testSuites/users_table_test_suite/execute

# 결과 조회
curl http://datapond.local/openmetadata/api/v1/dataQuality/testCases/results?testCaseId=<test-case-id>

# 실패한 테스트만 조회
curl "http://datapond.local/openmetadata/api/v1/dataQuality/testCases/results?testResult=Failed&limit=50"
```

### 알림 설정

```yaml
# Slack 알림
webhooks:
  slack:
    name: "datapond-alerts"
    webhookUrl: "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    filters:
      - eventType: "testCaseResult"
        condition: "testCaseFailed"
      - eventType: "testCaseResult"
        condition: "testCaseAborted"

# Email 알림
webhooks:
  email:
    name: "data-quality-alerts"
    endpoint: "smtp.gmail.com:587"
    username: "alerts@datapond.io"
    receivers: ["team@datapond.io", "data-eng@datapond.io"]
```

---

## 거버넌스 및 정책

### 1. 데이터 분류 (Classification)

```yaml
# PII 데이터 자동 태깅
classification:
  - name: "PII"
    description: "Personally Identifiable Information"
    tags:
      - "PII.Sensitive"
      - "PII.Email"
      - "PII.Phone"
      - "PII.SSN"
      - "PII.Address"

# 민감도 레벨
classification:
  - name: "DataSensitivity"
    tags:
      - "Public"
      - "Internal"
      - "Confidential"
      - "Restricted"
```

UI에서 자동 분류:

```
1. Settings → Classification
2. Add Classification → PII
3. Add Tags (PII.Email, PII.Phone, ...)
4. Settings → Profiler
5. Enable PII Detection
6. 스캔 실행 → 자동으로 PII 태그 부착
```

### 2. 용어집 (Glossary)

```yaml
# glossary.yaml
glossary:
  - name: "Business Glossary"
    terms:
      - name: "Customer"
        description: "Any individual or organization that purchases products"
        synonyms: ["Client", "Buyer"]
        relatedTerms: ["Order", "Purchase"]
        
      - name: "Active User"
        description: "User who logged in within the last 30 days"
        synonyms: ["MAU"]
        
      - name: "Churn Rate"
        description: "Percentage of customers who stopped using service"
        formula: "(Churned Customers / Total Customers) * 100"
```

### 3. 데이터 소유권 (Data Ownership)

```
1. Explore → Tables → 테이블 선택
2. Overview 탭
3. Add Owner:
   - Type: User 또는 Team
   - Name: data-engineering-team
4. Save
```

### 4. 정책 및 규칙

```yaml
# 접근 정책
policies:
  - name: "pii-access-policy"
    description: "PII 데이터 접근은 승인 필요"
    rules:
      - resource: "table"
        tagFilter: "PII.*"
        operations: ["ViewAll", "EditAll"]
        effect: "deny"
        condition: "!hasRole('data-privacy-officer')"

  - name: "production-write-policy"
    description: "프로덕션 데이터 쓰기는 제한"
    rules:
      - resource: "database"
        nameFilter: "iceberg.production.*"
        operations: ["EditAll", "Delete"]
        effect: "deny"
        condition: "!hasRole('admin')"
```

---

## 문제 해결

### 1. Pod가 시작 안 됨

```bash
# 로그 확인
kubectl logs -n datapond openmetadata-server-xxx
kubectl logs -n datapond openmetadata-elasticsearch-0

# 일반적인 원인:
# - PostgreSQL 미준비 → postgres pod 확인
# - Elasticsearch 메모리 부족 → 리소스 증가
# - vm.max_map_count 설정 필요
```

### 2. Elasticsearch vm.max_map_count 오류

```bash
# 호스트에서 설정 (영구적)
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf

# 또는 init container가 자동으로 설정 (일시적)
# (이미 Helm 템플릿에 포함됨)
```

### 3. 메타데이터 수집 실패

```bash
# OpenMetadata 로그 확인
kubectl logs -n datapond openmetadata-server-xxx | grep -i ingestion

# 커넥터 테스트
curl -X POST http://datapond.local/openmetadata/api/v1/services/testConnection \
  -H 'Content-Type: application/json' \
  -d '{"serviceName": "datapond-trino"}'

# 수동으로 재실행
curl -X POST http://datapond.local/openmetadata/api/v1/services/ingestionPipelines/trigger/trino-ingestion
```

### 4. 검색이 느림

```bash
# Elasticsearch 상태 확인
kubectl exec -it -n datapond openmetadata-elasticsearch-0 -- curl localhost:9200/_cluster/health?pretty

# 인덱스 재구축
curl -X POST http://datapond.local/openmetadata/api/v1/search/reindex

# 샤드 최적화
kubectl exec -it -n datapond openmetadata-elasticsearch-0 -- \
  curl -X POST "localhost:9200/_forcemerge?max_num_segments=1"
```

### 5. UI 접속 안 됨

```bash
# Ingress 확인
kubectl get ingress -n datapond datapond-ingress -o yaml | grep -A 5 openmetadata

# Service 확인
kubectl get svc -n datapond openmetadata-server

# 포트 포워딩으로 직접 테스트
kubectl port-forward -n datapond svc/openmetadata-server 8585:8585
# http://localhost:8585
```

---

## 고급 기능

### 1. 커스텀 Connector 개발

```python
# custom_connector.py
from metadata.ingestion.api.source import Source
from metadata.generated.schema.entity.data.table import Table

class CustomDataSource(Source):
    def __init__(self, config, metadata_config):
        super().__init__()
        self.config = config
        self.metadata = OpenMetadata(metadata_config)
    
    def prepare(self):
        # 데이터 소스 연결
        pass
    
    def next_record(self):
        # 메타데이터 수집
        for table in self.get_tables():
            yield Table(
                name=table.name,
                columns=table.columns,
                tableType="Regular"
            )
    
    def get_status(self):
        return SourceStatus()
    
    def close(self):
        pass
```

### 2. GraphQL API 사용

```graphql
# 테이블 검색
query {
  search(
    query: "users"
    index: "table_search_index"
  ) {
    hits {
      id
      name
      description
      columns {
        name
        dataType
      }
    }
  }
}

# Lineage 조회
query {
  getLineage(
    fqn: "datapond-trino.iceberg.analytics.users"
    upstreamDepth: 3
    downstreamDepth: 3
  ) {
    upstreamEdges {
      fromEntity
      toEntity
    }
    downstreamEdges {
      fromEntity
      toEntity
    }
  }
}
```

### 3. Webhook 통합

```yaml
# webhook-config.yaml
webhooks:
  - name: "metadata-change-webhook"
    endpoint: "http://your-service/webhook"
    eventFilters:
      - "entityCreated"
      - "entityUpdated"
      - "entityDeleted"
    entityFilters:
      - "table"
      - "dashboard"
    headers:
      Authorization: "Bearer YOUR_TOKEN"
    batchSize: 10
    timeout: 5000
```

---

## 참고 자료

### 공식 문서
- [OpenMetadata 공식 사이트](https://open-metadata.org)
- [GitHub Repository](https://github.com/open-metadata/OpenMetadata)
- [API Documentation](https://docs.open-metadata.org/sdk/python)

### DataPond 관련 문서
- [LAB_GUIDE.md](LAB_GUIDE.md) - Lab 9: OpenMetadata 실습
- [ARCHITECTURE.md](ARCHITECTURE.md) - 전체 아키텍처
- [STRATEGIC_COMPONENTS_INTEGRATION.md](STRATEGIC_COMPONENTS_INTEGRATION.md) - 통합 전략

### 커뮤니티
- [OpenMetadata Slack](https://slack.open-metadata.org)
- [DataPond Discord](https://discord.gg/datapond)

---

## 요약

OpenMetadata는 DataPond에 **엔터프라이즈급 데이터 거버넌스** 기능을 추가하여:

✅ **자동 데이터 디스커버리** (Trino, Spark, Airflow, PostgreSQL)  
✅ **End-to-End Lineage 추적** (실시간 시각화)  
✅ **데이터 품질 모니터링** (자동 테스트 + 알림)  
✅ **거버넌스 정책 적용** (PII 보호, 접근 제어)  
✅ **협업 강화** (메타데이터 공유, 문서화)

**다음 단계**: [LAB_GUIDE.md](LAB_GUIDE.md)의 Lab 9에서 실습을 시작하세요!

---

**작성**: DataPond Team  
**버전**: 2.3.0  
**최종 수정**: 2026-04-29
