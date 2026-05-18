# Dremio Community Edition — DataPond 통합 분석

**작성일**: 2026-05-18
**버전**: 1.0.0
**목적**: Dremio CE(Apache 2.0)를 DataPond 플랫폼에 통합하는 전략과 구현 계획

---

## 🔑 핵심 발견

| 항목 | 내용 |
|------|------|
| **라이선스** | Apache License 2.0 — 상업적 통합 제약 없음 |
| **Docker 이미지** | `dremio/dremio-oss:latest` |
| **CE에 포함된 것** | Reflections(수동), Virtual Datasets, Spaces, Arrow Flight, Iceberg, S3 호환, 직접 파일 쿼리, JDBC 커넥터 40+ |
| **CE에 없는 것** | Autonomous Reflections, Iceberg REST Catalog(Polaris), 고급 보안(RLS/컬럼마스킹), SSO/LDAP |
| **카탈로그** | **Nessie** 사용 — Polaris(REST Catalog)는 Enterprise only |

---

## ⚠️ 핵심 제약: Polaris → Nessie 전환 필요

Dremio CE는 Iceberg REST Catalog(현재 DataPond의 Polaris)를 지원하지 않는다.  
Dremio CE가 사용하는 카탈로그는 **Project Nessie** (Apache Foundation, Apache 2.0).

**좋은 소식**: Nessie는 Polaris보다 더 많은 기능을 제공한다.

| | Polaris (현재) | Nessie (전환 후) |
|---|---|---|
| Iceberg REST 스펙 | ✅ | ✅ |
| Trino 지원 | ✅ | ✅ |
| Spark 지원 | ✅ | ✅ |
| Dremio CE 지원 | ❌ | ✅ |
| Git-like 브랜치/태그 | ❌ | ✅ |
| 데이터 롤백 | ❌ | ✅ |
| 다중 엔진 공유 | ✅ | ✅ |

**결론**: Polaris → Nessie 전환 자체가 기능 향상이며, Dremio CE 통합의 전제조건이다.

---

## 🏗️ 통합 후 DataPond 아키텍처

```
분석가 (Analyst)          엔지니어 (Engineer)         데이터 사이언티스트
      ↓                          ↓                          ↓
 Dremio CE UI              DataPond UI                  JupyterLab
 - Virtual Datasets        - Airflow (파이프라인)        - DuckDB
 - Spaces (협업)           - Spark (배치 처리)           - MLflow
 - Reflections (가속)      - SQL Workbench (Trino)      - LiteLLM (AI)
 - 직접 파일 쿼리
      ↓                          ↓
   Arrow Flight            Trino / RisingWave
      ↓                          ↓
 ┌─────────────────────────────────────────┐
 │         Nessie (공유 Iceberg 카탈로그)   │
 │         Git-like 브랜치 + 태그 + 롤백    │
 └─────────────────────────────────────────┘
                    ↓
 ┌─────────────────────────────────────────┐
 │     SeaweedFS (S3 호환 오브젝트 스토리지) │
 │         Apache Iceberg 테이블 포맷        │
 └─────────────────────────────────────────┘
```

**핵심**: Dremio CE와 Trino가 **동일한 Nessie 카탈로그**를 바라보므로  
두 엔진에서 생성한 테이블을 서로 즉시 쿼리할 수 있다.

---

## 🎁 Dremio CE 통합으로 DataPond가 얻는 것

### 즉시 획득 (추가 개발 없음)

**1. Virtual Datasets (시맨틱 레이어)**
```sql
-- Dremio CE에서 분석가가 직접 생성
-- 복잡한 조인을 비즈니스 친화적 뷰로 추상화
CREATE VDS analytics.customer_revenue AS
SELECT
    c.customer_name,
    c.segment,
    SUM(s.revenue) as total_revenue,
    COUNT(s.id)    as order_count
FROM iceberg.raw.sales_fact s
JOIN iceberg.raw.customers c ON s.customer_id = c.id
GROUP BY 1, 2;

-- 분석가는 이렇게만 씀 (조인 모름)
SELECT segment, AVG(total_revenue) FROM analytics.customer_revenue GROUP BY 1;
```

**2. Reflections (쿼리 자동 가속)**
```
[Dremio CE UI에서 클릭 한 번]
"Create Reflection for: analytics.customer_revenue"

종류 선택:
  ○ Raw Reflection    (원본 데이터 물리적 캐시)
  ● Aggregation Reflection (집계 결과 캐시)
    - 집계 키: segment, order_date
    - 측정값: SUM(revenue), COUNT(id)

→ 동일 쿼리 재실행 시 0.1초 응답 (원본 30초)
→ 분석가 / DBA가 CLI 없이 UI로 관리
```

**3. Spaces (팀 협업)**
```
My Space (개인 실험 공간)
├── draft_revenue_analysis.sql
├── customer_churn_vds
└── temp_experiments/

Analytics Team (공유 공간)
├── official_kpi_vds/          ← 공식 지표 (변경 이력 추적)
├── monthly_reports/           ← 팀 공유 쿼리
└── bi_dashboards/             ← Tableau/Power BI 연결용

Finance (공유 공간)
└── cfo_metrics_vds/
```

**4. 직접 파일 쿼리 (ETL 없이)**
```sql
-- SeaweedFS에 올라온 원본 CSV/JSON/Parquet 즉시 쿼리
-- ETL 없음, 스키마 자동 추론
SELECT * FROM s3."datapond-raw"."uploads/2026/05/orders.csv" LIMIT 100;

-- 폴더 전체 (파티션 자동 인식)
SELECT region, SUM(amount)
FROM s3."datapond-raw"."transactions/"
WHERE year = 2026
GROUP BY region;
```

**5. Arrow Flight (BI 도구 고속 연결)**
```
Tableau → Dremio CE (Arrow Flight, port 32010) → Nessie → SeaweedFS
Power BI → Dremio CE (Arrow Flight) → Nessie → SeaweedFS

→ JDBC 대비 5-10배 빠른 데이터 전송
→ Dremio Tableau/Power BI 공식 커넥터 사용 가능
```

**6. 40+ 외부 데이터 소스 커넥터**
```
[Dremio CE가 기본 제공하는 커넥터]
데이터베이스: Oracle, SQL Server, MySQL, PostgreSQL,
             MongoDB, Elasticsearch, Cassandra
클라우드:    S3, ADLS, GCS, MinIO
파일:        Parquet, ORC, JSON, CSV, Excel, Arrow
레거시:      HDFS, Hive, HBase

→ DataPond의 Trino 커넥터와 중복되지만,
  Dremio CE는 UI에서 클릭 몇 번으로 연결 가능
  (Trino는 ConfigMap 직접 편집 필요)
```

---

## 🛠️ 구현 계획

### Phase 1: Polaris → Nessie 전환 (2주)

**1-1. Nessie Helm 템플릿 추가**

```yaml
# helm/datapond/templates/nessie-deployment.yaml
{{- if .Values.nessie.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nessie
  namespace: {{ .Values.namespace }}
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: nessie
  template:
    spec:
      containers:
      - name: nessie
        image: "{{ .Values.nessie.image.repository }}:{{ .Values.nessie.image.tag }}"
        ports:
        - containerPort: 19120  # REST API + UI
        env:
        - name: QUARKUS_DATASOURCE_JDBC_URL
          value: "jdbc:postgresql://postgres:5432/nessie_catalog"
        - name: QUARKUS_DATASOURCE_USERNAME
          value: "{{ .Values.postgres.auth.username }}"
        - name: QUARKUS_DATASOURCE_PASSWORD
          value: "{{ .Values.postgres.auth.password }}"
        - name: NESSIE_VERSION_STORE_TYPE
          value: "JDBC"
        resources:
          requests:
            memory: 512Mi
            cpu: 250m
          limits:
            memory: 1Gi
            cpu: 500m
---
apiVersion: v1
kind: Service
metadata:
  name: nessie
  namespace: {{ .Values.namespace }}
spec:
  ports:
  - port: 19120
    targetPort: 19120
    name: api
  selector:
    app: nessie
{{- end }}
```

**1-2. Trino 카탈로그 → Nessie로 전환**

```properties
# helm/datapond/templates/configmap.yaml (trino-catalog 부분)
iceberg.properties: |
  connector.name=iceberg
  iceberg.catalog.type=nessie
  iceberg.nessie.uri=http://nessie:19120/api/v1
  iceberg.nessie.default-reference.name=main
  fs.native-s3.enabled=true
  s3.endpoint=http://seaweedfs-s3:8333
  s3.path-style-access=true
  s3.aws-access-key={{ .Values.seaweedfs.accessKey }}
  s3.aws-secret-key={{ .Values.seaweedfs.secretKey }}
```

**1-3. postgres-init에 nessie_catalog DB 추가**

```bash
# helm/datapond/templates/postgres-init-configmap.yaml 에 추가
{{- if .Values.nessie.enabled }}
create_db "nessie_catalog"
{{- end }}
```

---

### Phase 2: Dremio CE 추가 (1주)

**2-1. Dremio CE Helm 템플릿**

```yaml
# helm/datapond/templates/dremio-deployment.yaml
{{- if .Values.dremio.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dremio
  namespace: {{ .Values.namespace }}
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: dremio
  template:
    spec:
      containers:
      - name: dremio
        image: "{{ .Values.dremio.image.repository }}:{{ .Values.dremio.image.tag }}"
        ports:
        - containerPort: 9047   # Web UI
          name: ui
        - containerPort: 31010  # JDBC
          name: jdbc
        - containerPort: 32010  # Arrow Flight
          name: flight
        env:
        - name: DREMIO_MAX_MEMORY_SIZE_MB
          value: "{{ .Values.dremio.memoryMb | default 8192 }}"
        volumeMounts:
        - name: dremio-data
          mountPath: /opt/dremio/data
        - name: dremio-config
          mountPath: /opt/dremio/conf
        resources:
          requests:
            memory: "{{ .Values.dremio.resources.requests.memory }}"
            cpu: "{{ .Values.dremio.resources.requests.cpu }}"
          limits:
            memory: "{{ .Values.dremio.resources.limits.memory }}"
            cpu: "{{ .Values.dremio.resources.limits.cpu }}"
      volumes:
      - name: dremio-data
        emptyDir: {}
      - name: dremio-config
        configMap:
          name: dremio-config
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: dremio-config
  namespace: {{ .Values.namespace }}
data:
  dremio.conf: |
    paths: {
      local: "/opt/dremio/data"
      dist: "dremioS3:///dremio-spill"
    }
    services: {
      coordinator.enabled: true,
      coordinator.master.enabled: true,
      executor.enabled: true
    }
  core-site.xml: |
    <configuration>
      <!-- SeaweedFS S3 연결 -->
      <property>
        <name>fs.s3a.endpoint</name>
        <value>http://seaweedfs-s3:8333</value>
      </property>
      <property>
        <name>fs.s3a.path.style.access</name>
        <value>true</value>
      </property>
      <property>
        <name>fs.s3a.access.key</name>
        <value>{{ .Values.seaweedfs.accessKey }}</value>
      </property>
      <property>
        <name>fs.s3a.secret.key</name>
        <value>{{ .Values.seaweedfs.secretKey }}</value>
      </property>
    </configuration>
---
apiVersion: v1
kind: Service
metadata:
  name: dremio
  namespace: {{ .Values.namespace }}
spec:
  ports:
  - port: 9047
    targetPort: 9047
    name: ui
  - port: 31010
    targetPort: 31010
    name: jdbc
  - port: 32010
    targetPort: 32010
    name: flight
  selector:
    app: dremio
{{- end }}
```

**2-2. Ingress에 Dremio CE 추가**

```yaml
# ingress.yaml에 추가
- path: /dremio
  pathType: Prefix
  backend:
    service:
      name: dremio
      port:
        number: 9047
```

**2-3. values.yaml에 Dremio CE 설정 추가**

```yaml
# helm/datapond/values.yaml
nessie:
  enabled: true
  image:
    repository: ghcr.io/projectnessie/nessie
    tag: "0.76.3"

dremio:
  enabled: false  # 기본 비활성화 (리소스 집약적)
  image:
    repository: dremio/dremio-oss
    tag: "latest"
  memoryMb: 8192
  resources:
    requests:
      memory: 8Gi
      cpu: 2000m
    limits:
      memory: 16Gi
      cpu: 4000m
```

---

### Phase 3: Dremio CE 초기 설정 자동화 (1주)

Dremio CE 최초 배포 시 Nessie + SeaweedFS 소스를 자동으로 구성하는 Job:

```yaml
# helm/datapond/templates/dremio-bootstrap-job.yaml
{{- if .Values.dremio.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: dremio-bootstrap
  namespace: {{ .Values.namespace }}
spec:
  template:
    spec:
      restartPolicy: OnFailure
      initContainers:
      - name: wait-dremio
        image: curlimages/curl:latest
        command: ['sh', '-c',
          'until curl -sf http://dremio:9047/apiv2/info; do sleep 5; done']
      containers:
      - name: bootstrap
        image: curlimages/curl:latest
        command:
        - sh
        - -c
        - |
          # 1. Dremio 첫 사용자 설정
          curl -X PUT http://dremio:9047/apiv2/bootstrap/firstuser \
            -H "Content-Type: application/json" \
            -d '{
              "userName": "admin",
              "firstName": "DataPond",
              "lastName": "Admin",
              "email": "admin@datapond.local",
              "createdAt": 0,
              "password": "{{ .Values.dremio.adminPassword | default "changeme" }}"
            }'

          # 2. 로그인 토큰 획득
          TOKEN=$(curl -s -X POST http://dremio:9047/apiv2/login \
            -H "Content-Type: application/json" \
            -d '{"userName":"admin","password":"{{ .Values.dremio.adminPassword | default "changeme" }}"}' \
            | grep -o '"token":"[^"]*"' | cut -d'"' -f4)

          # 3. Nessie 카탈로그 소스 등록
          curl -X POST http://dremio:9047/apiv2/source/nessie_iceberg \
            -H "Authorization: _dremio$TOKEN" \
            -H "Content-Type: application/json" \
            -d '{
              "name": "nessie_iceberg",
              "type": "NESSIE",
              "config": {
                "nessieEndpoint": "http://nessie:19120/api/v1",
                "nessieAuthType": "NONE",
                "awsAccessKey": "{{ .Values.seaweedfs.accessKey }}",
                "awsAccessSecret": "{{ .Values.seaweedfs.secretKey }}",
                "awsRootPath": "s3a://iceberg-warehouse",
                "propertyList": [
                  {"name": "fs.s3a.endpoint", "value": "http://seaweedfs-s3:8333"},
                  {"name": "fs.s3a.path.style.access", "value": "true"}
                ]
              }
            }'

          # 4. DataPond Analytics 공유 Space 생성
          curl -X POST http://dremio:9047/apiv2/space/datapond_analytics \
            -H "Authorization: _dremio$TOKEN" \
            -H "Content-Type: application/json" \
            -d '{"name": "DataPond Analytics", "description": "Official DataPond metrics and reports"}'

          echo "Dremio CE bootstrap complete"
{{- end }}
```

---

## 📊 통합 전후 비교

### DataPond 기능 매트릭스 (통합 후)

| 기능 | 통합 전 | 통합 후 | 제공 방식 |
|------|---------|---------|-----------|
| **분석가 셀프서비스 SQL** | ❌ | ✅ | Dremio CE |
| **Virtual Datasets** | ❌ | ✅ | Dremio CE |
| **Spaces (협업)** | ❌ | ✅ | Dremio CE |
| **Reflections (쿼리 가속)** | ❌ | ✅ | Dremio CE |
| **Arrow Flight BI 연결** | ❌ | ✅ | Dremio CE |
| **직접 파일 쿼리** | ❌ | ✅ | Dremio CE |
| **Git-like 데이터 브랜치** | ❌ | ✅ | Nessie |
| **데이터 롤백** | ❌ | ✅ | Nessie |
| **실시간 스트리밍** | ✅ | ✅ | RisingWave |
| **배치 파이프라인** | ✅ | ✅ | Airflow + Spark |
| **ML 실험 추적** | ✅ | ✅ | MLflow |
| **내부망 AI** | ✅ | ✅ | LiteLLM |
| **에어갭 스토리지** | ✅ | ✅ | SeaweedFS |
| **데이터 리니지** | ✅ | ✅ | OpenMetadata |

---

## ⚠️ 한계 및 고려사항

### Dremio CE의 한계 (Enterprise 기능 없음)

| 기능 | 상황 | 대안 |
|------|------|------|
| Autonomous Reflections | ❌ CE 없음 | 수동 Reflection + MV 추천 시스템 자체 개발 |
| 컬럼 마스킹 | ❌ CE 없음 | Trino system access control로 구현 |
| 행 수준 보안(RLS) | ❌ CE 없음 | Trino system access control로 구현 |
| LDAP/SSO 통합 | ❌ CE 없음 | Trino + DataPond 자체 LDAP 연동 |

→ **거버넌스 기능은 Trino 레이어에서 구현해야 함** (Dremio CE를 통하지 않는 경로)

### 리소스 요구사항

```yaml
# Dremio CE 최소 요건 (단일 노드 기준)
RAM: 8GB (최소), 16GB+ (권장)
CPU: 4코어 (권장)
Storage: 50GB+ (spill, data)

# DataPond 전체 스택 (Dremio CE 추가 후)
총 RAM: 최소 40GB+ (dev 환경)
         권장 64GB+ (안정적 운영)

→ values-quicktest.yaml에서는 dremio.enabled: false 유지
→ values-prod.yaml에서 활성화
```

### 인증 이중화 문제

```
현재:  DataPond 사용자 (JWT)
추가:  Dremio CE 사용자 (별도 관리)

단기:  두 시스템 별도 계정 (허용 가능)
중기:  DataPond LDAP → Dremio CE LDAP 연동
       (단, LDAP 연동은 Dremio Enterprise 기능)
장기:  Dremio CE에 OAuth2 프록시 추가
       (oauth2-proxy 컨테이너로 DataPond 인증 적용)
```

---

## 🎯 최종 통합 포지셔닝

### DataPond + Dremio CE + Nessie = 완전한 플랫폼

```
[분석가 UX]                    [엔지니어 UX]            [데이터 사이언티스트]
Dremio CE Sonar                DataPond UI               JupyterLab
  Virtual Datasets               Airflow DAG              DuckDB + Iceberg
  Spaces + 협업                  Spark 배치               MLflow 실험
  Reflections UI                 RisingWave 실시간        LiteLLM AI
  Arrow Flight                   Trino SQL
  직접 파일 쿼리
         ↓                          ↓
    동일한 Nessie 카탈로그에 접근 (브랜치/롤백/태그)
         ↓
    SeaweedFS Iceberg 테이블 (에어갭 완전 내재화)
```

### 세일즈 메시지

**기존**: "Databricks가 못 들어가는 곳의 대안"

**통합 후**: "Dremio + Databricks를 에어갭에서 하나로"

> 분석가는 Dremio CE로 셀프서비스 분석을,  
> 엔지니어는 Spark + Airflow로 파이프라인을,  
> 데이터 사이언티스트는 MLflow + JupyterLab으로 모델을,  
> 모두가 동일한 Nessie Iceberg 카탈로그 위에서.  
> 인터넷 없이, 규제 환경 안에서.

---

## 📋 구현 우선순위

| 단계 | 작업 | 기간 | 선행 조건 |
|------|------|------|----------|
| **1** | Nessie Helm 템플릿 추가 | 3일 | 없음 |
| **2** | postgres-init에 nessie_catalog 추가 | 1일 | Step 1 |
| **3** | Trino 카탈로그 → Nessie 전환 | 2일 | Step 1 |
| **4** | Spark → Nessie 전환 | 2일 | Step 1 |
| **5** | Dremio CE Helm 템플릿 | 3일 | Step 1 |
| **6** | Dremio bootstrap Job (자동 설정) | 2일 | Step 5 |
| **7** | Ingress /dremio 경로 추가 | 1일 | Step 5 |
| **8** | values-prod.yaml에 dremio 활성화 | 1일 | Step 7 |
| **총** | **~2.5주 (엔지니어 1명)** | | |
