# DataPond 전략적 컴포넌트 통합 가이드

**작성일**: 2026-04-28  
**버전**: 1.0.0  
**대상**: 개발자, DevOps, 아키텍트

---

## 📋 목차

1. [개요](#개요)
2. [Apache Polaris 통합](#apache-polaris-통합)
3. [DuckDB 통합](#duckdb-통합)
4. [RisingWave 통합](#risingwave-통합)
5. [OpenMetadata 통합](#openmetadata-통합)
6. [통합 우선순위](#통합-우선순위)
7. [End-to-End 테스트](#end-to-end-테스트)

---

## 개요

### 통합 목적

DataPond를 Databricks Unity Catalog 수준의 엔터프라이즈 플랫폼으로 발전시키기 위해 4개 전략적 컴포넌트를 통합합니다.

### 4개 컴포넌트

```yaml
1. Apache Polaris:
   - 역할: Iceberg Catalog & Governance
   - 가치: Unity Catalog 대안 ($0)
   - 우선순위: P0 (즉시 통합)
   - 소요 시간: 2일

2. DuckDB:
   - 역할: JupyterLab 로컬 고성능 쿼리
   - 가치: 분석 속도 10배, Spark 사용 80% 감소
   - 우선순위: P0 (즉시 통합)
   - 소요 시간: 1일

3. RisingWave:
   - 역할: 실시간 스트리밍 SQL 처리
   - 가치: Kafka + Flink 대체, 운영 복잡도 50% 감소
   - 우선순위: P1 (Phase 2)
   - 소요 시간: 1주

4. OpenMetadata:
   - 역할: 데이터 카탈로그 + 자동 Lineage
   - 가치: 엔터프라이즈 필수 기능, 세일즈 활성화
   - 우선순위: P1 (Phase 2)
   - 소요 시간: 1주
```

### 통합 효과

```yaml
Before (통합 전):
  거버넌스: ❌ 없음
  실시간: ❌ 제한적 (Spark Streaming만)
  로컬 쿼리: ⚠️ Spark만 (무거움)
  Lineage: ❌ 없음
  포지셔닝: "엔지니어용 플랫폼"

After (통합 후):
  거버넌스: ✅ Polaris (Unity Catalog 수준)
  실시간: ✅ RisingWave (Flink 대안)
  로컬 쿼리: ✅ DuckDB (초고속)
  Lineage: ✅ OpenMetadata (Collibra 대안)
  포지셔닝: "Complete Data Platform"
```

---

## Apache Polaris 통합

### 개요

Apache Polaris는 Snowflake가 3년간 프로덕션 검증 후 Apache Foundation에 기증한 Iceberg REST Catalog입니다. Unity Catalog와 동등한 수준의 거버넌스 기능을 제공합니다.

### 기술 스펙

```yaml
프로젝트: Apache Polaris
라이선스: Apache 2.0
상태: Top-Level Project (2026년 2월 졸업)
프로덕션 사용: Netflix, Apple, Salesforce
API: REST (Iceberg Catalog REST API 표준)
Port: 8181
Metastore Backend: PostgreSQL
Warehouse: SeaweedFS (S3 API)
```

### 통합 가치

```yaml
현재 문제 (JDBC Catalog):
  - 동시성 제어 제한적
  - 권한 관리 없음
  - 멀티테넌트 불가
  - 감사 로그 없음

Polaris 해결:
  - 분산 트랜잭션 지원
  - RBAC (Role-Based Access Control)
  - Namespace 격리 (멀티테넌시)
  - 모든 작업 감사 로그
  - 카탈로그 버전 관리

경쟁력:
  - Databricks Unity Catalog: $$$$ (DBU 비용)
  - Apache Polaris: $0
  - 기능: 동등
```

### Step 1: Helm Chart 업데이트

**파일**: `/home/luke/datapond-k8s/helm/datapond/Chart.yaml`

```yaml
dependencies:
  - name: polaris
    version: 0.1.0
    repository: https://polaris-catalog.github.io/polaris-helm-charts
    condition: polaris.enabled
```

**파일**: `/home/luke/datapond-k8s/helm/datapond/values.yaml`

```yaml
# Apache Polaris (Iceberg REST Catalog)
polaris:
  enabled: true
  name: polaris
  replicas: 2  # HA
  
  image:
    repository: apache/polaris
    tag: latest
    pullPolicy: IfNotPresent
  
  service:
    type: ClusterIP
    port: 8181
  
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi
  
  # PostgreSQL backend (DataPond의 PostgreSQL 재사용)
  metastore:
    type: postgres
    host: {{ .Values.postgres.name }}
    port: 5432
    database: polaris_catalog
    username: {{ .Values.postgres.username }}
    password: {{ .Values.postgres.password }}
  
  # S3 warehouse (SeaweedFS)
  warehouse:
    type: s3
    endpoint: http://{{ .Values.seaweedfs.s3.name }}:{{ .Values.seaweedfs.s3.port }}
    bucket: iceberg
    path: warehouse
    accessKey: {{ .Values.seaweedfs.s3.accessKey }}
    secretKey: {{ .Values.seaweedfs.s3.secretKey }}
  
  # RBAC 설정
  security:
    enabled: true
    adminUser: admin
    adminPassword: changeme  # Secret으로 관리 권장
  
  # 감사 로그
  audit:
    enabled: true
    logLevel: INFO
```

### Step 2: Polaris Deployment 생성

**파일**: `/home/luke/datapond-k8s/helm/datapond/templates/polaris-deployment.yaml`

```yaml
{{- if .Values.polaris.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.polaris.name }}
  namespace: {{ .Values.namespace }}
  labels:
    app: {{ .Values.polaris.name }}
spec:
  replicas: {{ .Values.polaris.replicas }}
  selector:
    matchLabels:
      app: {{ .Values.polaris.name }}
  template:
    metadata:
      labels:
        app: {{ .Values.polaris.name }}
    spec:
      containers:
      - name: polaris
        image: {{ .Values.polaris.image.repository }}:{{ .Values.polaris.image.tag }}
        imagePullPolicy: {{ .Values.polaris.image.pullPolicy }}
        
        env:
        # PostgreSQL metastore
        - name: POLARIS_METASTORE_TYPE
          value: "postgres"
        - name: POLARIS_METASTORE_HOST
          value: "{{ .Values.polaris.metastore.host }}"
        - name: POLARIS_METASTORE_PORT
          value: "{{ .Values.polaris.metastore.port }}"
        - name: POLARIS_METASTORE_DATABASE
          value: "{{ .Values.polaris.metastore.database }}"
        - name: POLARIS_METASTORE_USERNAME
          value: "{{ .Values.polaris.metastore.username }}"
        - name: POLARIS_METASTORE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        
        # S3 warehouse (SeaweedFS)
        - name: POLARIS_WAREHOUSE_TYPE
          value: "{{ .Values.polaris.warehouse.type }}"
        - name: POLARIS_WAREHOUSE_ENDPOINT
          value: "{{ .Values.polaris.warehouse.endpoint }}"
        - name: POLARIS_WAREHOUSE_BUCKET
          value: "{{ .Values.polaris.warehouse.bucket }}"
        - name: POLARIS_WAREHOUSE_PATH
          value: "{{ .Values.polaris.warehouse.path }}"
        - name: AWS_ACCESS_KEY_ID
          value: "{{ .Values.polaris.warehouse.accessKey }}"
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: seaweedfs-s3-secret
              key: secretKey
        
        # Security
        - name: POLARIS_SECURITY_ENABLED
          value: "{{ .Values.polaris.security.enabled }}"
        - name: POLARIS_ADMIN_USER
          value: "{{ .Values.polaris.security.adminUser }}"
        - name: POLARIS_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: polaris-admin-secret
              key: password
        
        # Audit
        - name: POLARIS_AUDIT_ENABLED
          value: "{{ .Values.polaris.audit.enabled }}"
        - name: POLARIS_AUDIT_LOG_LEVEL
          value: "{{ .Values.polaris.audit.logLevel }}"
        
        ports:
        - name: http
          containerPort: 8181
          protocol: TCP
        
        livenessProbe:
          httpGet:
            path: /api/v1/config
            port: 8181
          initialDelaySeconds: 30
          periodSeconds: 10
        
        readinessProbe:
          httpGet:
            path: /api/v1/config
            port: 8181
          initialDelaySeconds: 10
          periodSeconds: 5
        
        resources:
          requests:
            cpu: {{ .Values.polaris.resources.requests.cpu }}
            memory: {{ .Values.polaris.resources.requests.memory }}
          limits:
            cpu: {{ .Values.polaris.resources.limits.cpu }}
            memory: {{ .Values.polaris.resources.limits.memory }}

---
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.polaris.name }}
  namespace: {{ .Values.namespace }}
spec:
  type: {{ .Values.polaris.service.type }}
  ports:
  - port: {{ .Values.polaris.service.port }}
    targetPort: 8181
    protocol: TCP
    name: http
  selector:
    app: {{ .Values.polaris.name }}

---
apiVersion: v1
kind: Secret
metadata:
  name: polaris-admin-secret
  namespace: {{ .Values.namespace }}
type: Opaque
stringData:
  password: {{ .Values.polaris.security.adminPassword | quote }}
{{- end }}
```

### Step 3: Trino 설정 변경

**파일**: `/home/luke/datapond-k8s/helm/datapond/templates/trino-configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: trino-catalog
  namespace: {{ .Values.namespace }}
data:
  iceberg.properties: |
    connector.name=iceberg
    
    {{- if .Values.polaris.enabled }}
    # ✅ Polaris REST Catalog
    iceberg.catalog.type=rest
    iceberg.rest.uri=http://{{ .Values.polaris.name }}:{{ .Values.polaris.service.port }}/api/catalog
    iceberg.rest.credential={{ .Values.polaris.security.adminUser }}:{{ .Values.polaris.security.adminPassword }}
    iceberg.rest.warehouse=iceberg-warehouse
    {{- else }}
    # ❌ Fallback: JDBC Catalog (deprecated)
    iceberg.catalog.type=jdbc
    iceberg.jdbc-catalog.driver-class=org.postgresql.Driver
    iceberg.jdbc-catalog.connection-url=jdbc:postgresql://{{ .Values.postgres.name }}:5432/iceberg_catalog
    iceberg.jdbc-catalog.connection-user={{ .Values.postgres.username }}
    iceberg.jdbc-catalog.connection-password={{ .Values.postgres.password }}
    {{- end }}
    
    # S3 설정 (SeaweedFS)
    fs.native-s3.enabled=true
    s3.endpoint=http://{{ .Values.seaweedfs.s3.name }}:{{ .Values.seaweedfs.s3.port }}
    s3.path-style-access=true
    s3.region=us-east-1
```

### Step 4: Spark 설정 변경

**파일**: `/home/luke/datapond-k8s/helm/datapond/templates/spark-statefulset.yaml`

Spark Master/Worker 환경변수 추가:

```yaml
env:
{{- if .Values.polaris.enabled }}
# ✅ Polaris REST Catalog
- name: SPARK_SQL_CATALOG_ICEBERG
  value: "org.apache.iceberg.spark.SparkCatalog"
- name: SPARK_SQL_CATALOG_ICEBERG_CATALOG_IMPL
  value: "org.apache.iceberg.rest.RESTCatalog"
- name: SPARK_SQL_CATALOG_ICEBERG_URI
  value: "http://{{ .Values.polaris.name }}:{{ .Values.polaris.service.port }}/api/catalog"
- name: SPARK_SQL_CATALOG_ICEBERG_CREDENTIAL
  value: "{{ .Values.polaris.security.adminUser }}:{{ .Values.polaris.security.adminPassword }}"
- name: SPARK_SQL_CATALOG_ICEBERG_WAREHOUSE
  value: "iceberg-warehouse"
{{- else }}
# ❌ Fallback: Hadoop Catalog (deprecated)
- name: SPARK_SQL_CATALOG_ICEBERG
  value: "org.apache.iceberg.spark.SparkCatalog"
- name: SPARK_SQL_CATALOG_ICEBERG_TYPE
  value: "hadoop"
- name: SPARK_SQL_CATALOG_ICEBERG_WAREHOUSE
  value: "s3a://iceberg/warehouse"
{{- end }}

# S3 설정 (SeaweedFS)
- name: SPARK_HADOOP_FS_S3A_ENDPOINT
  value: "http://{{ .Values.seaweedfs.s3.name }}:{{ .Values.seaweedfs.s3.port }}"
- name: SPARK_HADOOP_FS_S3A_ACCESS_KEY
  value: "{{ .Values.seaweedfs.s3.accessKey }}"
- name: SPARK_HADOOP_FS_S3A_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: seaweedfs-s3-secret
      key: secretKey
- name: SPARK_HADOOP_FS_S3A_PATH_STYLE_ACCESS
  value: "true"
```

### Step 5: 마이그레이션 스크립트

**파일**: `/home/luke/datapond-k8s/scripts/migrate_to_polaris.py`

```python
#!/usr/bin/env python3
"""
JDBC Catalog → Polaris REST Catalog 마이그레이션

Usage:
  python migrate_to_polaris.py
"""

from pyspark.sql import SparkSession
import sys

def main():
    print("🚀 Starting migration: JDBC Catalog → Polaris REST Catalog")
    
    # Spark 세션 생성 (JDBC catalog 연결)
    spark_old = SparkSession.builder \
        .appName("Polaris-Migration") \
        .config("spark.sql.catalog.iceberg_old", "org.apache.iceberg.spark.SparkCatalog") \
        .config("spark.sql.catalog.iceberg_old.type", "jdbc") \
        .config("spark.sql.catalog.iceberg_old.uri", "jdbc:postgresql://postgres:5432/iceberg_catalog") \
        .config("spark.sql.catalog.iceberg_old.jdbc.user", "datapond") \
        .config("spark.sql.catalog.iceberg_old.jdbc.password", "datapond_password") \
        .getOrCreate()
    
    # Polaris catalog 연결
    spark_old.conf.set("spark.sql.catalog.iceberg_new", "org.apache.iceberg.spark.SparkCatalog")
    spark_old.conf.set("spark.sql.catalog.iceberg_new.catalog-impl", "org.apache.iceberg.rest.RESTCatalog")
    spark_old.conf.set("spark.sql.catalog.iceberg_new.uri", "http://polaris:8181/api/catalog")
    spark_old.conf.set("spark.sql.catalog.iceberg_new.credential", "admin:changeme")
    spark_old.conf.set("spark.sql.catalog.iceberg_new.warehouse", "iceberg-warehouse")
    
    # 기존 JDBC catalog 테이블 목록
    print("📋 Listing tables in JDBC catalog...")
    namespaces = spark_old.sql("SHOW NAMESPACES IN iceberg_old").collect()
    
    total_tables = 0
    migrated_tables = 0
    
    for ns_row in namespaces:
        namespace = ns_row['namespace']
        print(f"\n📁 Namespace: {namespace}")
        
        tables = spark_old.sql(f"SHOW TABLES IN iceberg_old.{namespace}").collect()
        
        for table_row in tables:
            table_name = table_row['tableName']
            full_table = f"{namespace}.{table_name}"
            total_tables += 1
            
            try:
                print(f"  ⏳ Migrating: {full_table}")
                
                # 1. 기존 테이블 읽기
                df = spark_old.table(f"iceberg_old.{full_table}")
                row_count = df.count()
                
                # 2. Polaris catalog에 쓰기 (메타데이터 + 데이터)
                df.writeTo(f"iceberg_new.{full_table}") \
                    .using("iceberg") \
                    .createOrReplace()
                
                print(f"  ✅ Migrated: {full_table} ({row_count:,} rows)")
                migrated_tables += 1
                
            except Exception as e:
                print(f"  ❌ Failed: {full_table} - {str(e)}")
                continue
    
    print(f"\n📊 Migration Summary:")
    print(f"  Total tables: {total_tables}")
    print(f"  Migrated: {migrated_tables}")
    print(f"  Failed: {total_tables - migrated_tables}")
    
    spark_old.stop()
    
    if migrated_tables == total_tables:
        print("\n🎉 Migration completed successfully!")
        return 0
    else:
        print("\n⚠️  Migration completed with errors.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

### Step 6: 배포 및 테스트

```bash
# 1. Helm dependency 업데이트
cd /home/luke/datapond-k8s/helm/datapond
helm dependency update

# 2. 배포
helm upgrade --install datapond . \
  -n datapond \
  --create-namespace \
  --set polaris.enabled=true

# 3. Polaris 상태 확인
kubectl get pods -n datapond -l app=polaris
kubectl logs -n datapond -l app=polaris

# 4. Polaris API 테스트
kubectl port-forward -n datapond svc/polaris 8181:8181
curl http://localhost:8181/api/v1/config

# 5. Trino 테스트
kubectl exec -it <trino-coordinator-pod> -n datapond -- trino
> SHOW CATALOGS;
> SHOW NAMESPACES IN iceberg;
> SHOW TABLES IN iceberg.analytics;

# 6. Spark 테스트
kubectl exec -it spark-master-0 -n datapond -- pyspark
>>> spark.sql("SHOW NAMESPACES IN iceberg").show()
>>> spark.sql("CREATE NAMESPACE IF NOT EXISTS iceberg.test")
>>> spark.sql("CREATE TABLE iceberg.test.users (id BIGINT, name STRING) USING iceberg")
>>> spark.sql("INSERT INTO iceberg.test.users VALUES (1, 'Alice'), (2, 'Bob')")
>>> spark.sql("SELECT * FROM iceberg.test.users").show()

# 7. 마이그레이션 (기존 JDBC → Polaris)
kubectl cp scripts/migrate_to_polaris.py datapond/spark-master-0:/tmp/
kubectl exec -it spark-master-0 -n datapond -- python /tmp/migrate_to_polaris.py
```

### 롤백 계획

Polaris에 문제가 발생하면 JDBC Catalog로 롤백:

```bash
# values.yaml 수정
polaris:
  enabled: false

# 재배포
helm upgrade datapond . -n datapond
```

---

## DuckDB 통합

### 개요

DuckDB는 JupyterLab 노트북에서 S3 Iceberg 테이블을 로컬에서 초고속 쿼리할 수 있게 합니다. Spark 클러스터 없이 작은~중간 규모 분석이 가능합니다.

### 기술 스펙

```yaml
프로젝트: DuckDB
라이선스: MIT
버전: 0.10.0+
특징: In-process OLAP database
Iceberg 지원: 네이티브 (iceberg extension)
S3 지원: 네이티브 (httpfs extension)
성능: GB급 데이터 sub-second 쿼리
```

### 통합 가치

```yaml
현재 문제:
  - 작은 데이터도 Spark 클러스터 필요
  - Spark 세션 생성 대기 (10-30초)
  - 탐색적 분석 불편
  - 클러스터 리소스 낭비

DuckDB 해결:
  - 로컬 실행 (클러스터 불필요)
  - 즉시 시작 (0초)
  - 초고속 쿼리 (Spark 대비 10배)
  - Pandas 완벽 연동

사용 패턴:
  - < 10GB: DuckDB (초 단위)
  - 10-100GB: DuckDB (분 단위)
  - > 100GB: Spark (필요시만)

효과:
  - Spark 사용률: 80% → 20%
  - 분석 속도: 10배 향상
  - 리소스 비용: 절감
```

### Step 1: JupyterLab Docker 이미지

**파일**: `/home/luke/datapond-k8s/docker/jupyter/Dockerfile`

```dockerfile
FROM jupyter/scipy-notebook:latest

USER root

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# Python packages
RUN pip install --no-cache-dir \
    duckdb==0.10.0 \
    pyiceberg==0.5.0 \
    boto3==1.34.0 \
    pandas==2.2.0 \
    matplotlib==3.8.0 \
    seaborn==0.13.0

# Iceberg helper script
COPY iceberg_helper.py /usr/local/lib/python3.11/site-packages/

# Example notebooks
COPY notebooks/ /home/${NB_USER}/work/examples/

USER ${NB_UID}
WORKDIR /home/${NB_USER}
```

### Step 2: Iceberg Helper 스크립트

**파일**: `/home/luke/datapond-k8s/docker/jupyter/iceberg_helper.py`

```python
"""
DataPond Iceberg Helper for DuckDB

Quick access to Iceberg tables from JupyterLab using DuckDB.
"""

import duckdb
import os
from typing import Optional
import pandas as pd


def connect_duckdb_iceberg(
    s3_endpoint: Optional[str] = None,
    s3_access_key: Optional[str] = None,
    s3_secret_key: Optional[str] = None
) -> duckdb.DuckDBPyConnection:
    """
    Create DuckDB connection with Iceberg + S3 support.
    
    Args:
        s3_endpoint: S3 endpoint URL (default: from env SEAWEEDFS_S3_ENDPOINT)
        s3_access_key: S3 access key (default: from env SEAWEEDFS_S3_ACCESS_KEY)
        s3_secret_key: S3 secret key (default: from env SEAWEEDFS_S3_SECRET_KEY)
    
    Returns:
        DuckDB connection ready for Iceberg queries
    
    Example:
        >>> conn = connect_duckdb_iceberg()
        >>> df = conn.sql("SELECT * FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')").df()
    """
    
    # Get config from environment
    s3_endpoint = s3_endpoint or os.getenv('SEAWEEDFS_S3_ENDPOINT', 'http://seaweedfs-s3:8333')
    s3_access_key = s3_access_key or os.getenv('SEAWEEDFS_S3_ACCESS_KEY', 'datapond')
    s3_secret_key = s3_secret_key or os.getenv('SEAWEEDFS_S3_SECRET_KEY', 'datapond_s3_password')
    
    # Create connection
    conn = duckdb.connect()
    
    # Install extensions
    conn.execute("INSTALL httpfs;")
    conn.execute("LOAD httpfs;")
    conn.execute("INSTALL iceberg;")
    conn.execute("LOAD iceberg;")
    
    # Configure S3
    conn.execute(f"SET s3_endpoint='{s3_endpoint}';")
    conn.execute(f"SET s3_access_key_id='{s3_access_key}';")
    conn.execute(f"SET s3_secret_access_key='{s3_secret_key}';")
    conn.execute("SET s3_use_ssl=false;")
    conn.execute("SET s3_url_style='path';")
    conn.execute("SET s3_region='us-east-1';")
    
    return conn


def query_iceberg(
    table_path: str,
    where: Optional[str] = None,
    limit: Optional[int] = None,
    columns: Optional[list] = None
) -> pd.DataFrame:
    """
    Quick Iceberg table query.
    
    Args:
        table_path: Iceberg table path (e.g., 'analytics/events')
        where: WHERE clause (optional)
        limit: LIMIT rows (optional)
        columns: SELECT columns (optional, default: *)
    
    Returns:
        Pandas DataFrame
    
    Example:
        >>> df = query_iceberg(
        ...     'analytics/events',
        ...     where="country = 'KR' AND date >= '2026-04-01'",
        ...     limit=1000
        ... )
    """
    
    conn = connect_duckdb_iceberg()
    
    # Build SQL
    cols = ', '.join(columns) if columns else '*'
    sql = f"SELECT {cols} FROM iceberg_scan('s3://iceberg/warehouse/{table_path}')"
    
    if where:
        sql += f" WHERE {where}"
    
    if limit:
        sql += f" LIMIT {limit}"
    
    return conn.sql(sql).df()


def list_iceberg_tables() -> pd.DataFrame:
    """
    List all Iceberg tables in warehouse.
    
    Returns:
        DataFrame with columns: namespace, table_name, location
    
    Example:
        >>> tables = list_iceberg_tables()
        >>> print(tables)
    """
    
    # This would require parsing Polaris catalog
    # For now, return placeholder
    print("💡 Tip: Use Polaris API to list tables:")
    print("  curl http://polaris:8181/api/catalog/v1/namespaces")
    return pd.DataFrame()


# Convenience functions
def q(table: str, where: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
    """
    Ultra-short query function.
    
    Example:
        >>> df = q('analytics/events', where="country = 'KR'", limit=1000)
    """
    return query_iceberg(table, where=where, limit=limit)


# Auto-initialize on import
print("🦆 DuckDB + Iceberg ready!")
print("📖 Quick start:")
print("  from iceberg_helper import q")
print("  df = q('analytics/events', where=\"country = 'KR'\", limit=1000)")
```

### Step 3: 예제 노트북

**파일**: `/home/luke/datapond-k8s/docker/jupyter/notebooks/01_DuckDB_QuickStart.ipynb`

```json
{
  "cells": [
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "# DuckDB + Iceberg Quick Start\n",
        "\n",
        "This notebook shows how to query Iceberg tables using DuckDB (no Spark cluster needed!)."
      ]
    },
    {
      "cell_type": "code",
      "metadata": {},
      "source": [
        "# Import helper\n",
        "from iceberg_helper import connect_duckdb_iceberg, query_iceberg, q\n",
        "import pandas as pd"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "## Method 1: Ultra-short query (recommended)"
      ]
    },
    {
      "cell_type": "code",
      "metadata": {},
      "source": [
        "# Query Iceberg table (sub-second!)\n",
        "df = q('analytics/events', where=\"country = 'KR' AND date >= '2026-04-01'\", limit=1000)\n",
        "print(f\"Rows: {len(df):,}\")\n",
        "df.head()"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "## Method 2: Full SQL query"
      ]
    },
    {
      "cell_type": "code",
      "metadata": {},
      "source": [
        "# DuckDB connection\n",
        "conn = connect_duckdb_iceberg()\n",
        "\n",
        "# Complex aggregation\n",
        "result = conn.sql(\"\"\"\n",
        "    SELECT \n",
        "        country,\n",
        "        COUNT(DISTINCT user_id) as unique_users,\n",
        "        COUNT(*) as total_events,\n",
        "        AVG(session_duration) as avg_duration\n",
        "    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events')\n",
        "    WHERE date >= '2026-04-01'\n",
        "    GROUP BY country\n",
        "    ORDER BY total_events DESC\n",
        "\"\"\").df()\n",
        "\n",
        "result"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "## Method 3: Pandas integration"
      ]
    },
    {
      "cell_type": "code",
      "metadata": {},
      "source": [
        "# Small lookup table (Pandas)\n",
        "lookup = pd.read_csv('/home/jovyan/work/country_lookup.csv')\n",
        "\n",
        "# Create temp table in DuckDB\n",
        "conn.execute(\"CREATE TEMP TABLE lookup AS SELECT * FROM lookup\")\n",
        "\n",
        "# Join with Iceberg table\n",
        "joined = conn.sql(\"\"\"\n",
        "    SELECT \n",
        "        e.user_id,\n",
        "        e.event_type,\n",
        "        l.country_name,\n",
        "        l.region\n",
        "    FROM iceberg_scan('s3://iceberg/warehouse/analytics/events') e\n",
        "    JOIN lookup l ON e.country = l.country_code\n",
        "    WHERE e.date >= '2026-04-01'\n",
        "    LIMIT 1000\n",
        "\"\"\").df()\n",
        "\n",
        "joined"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "## Visualization"
      ]
    },
    {
      "cell_type": "code",
      "metadata": {},
      "source": [
        "import matplotlib.pyplot as plt\n",
        "\n",
        "# Plot\n",
        "result.plot(kind='bar', x='country', y='unique_users', figsize=(12, 6))\n",
        "plt.title('Unique Users by Country')\n",
        "plt.ylabel('Users')\n",
        "plt.show()"
      ]
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "## Performance Comparison\n",
        "\n",
        "```python\n",
        "# Spark (before)\n",
        "spark = SparkSession.builder.getOrCreate()  # 10-30 seconds\n",
        "df = spark.sql(\"SELECT * FROM iceberg.analytics.events WHERE country = 'KR'\")\n",
        "df.toPandas()  # Slow\n",
        "\n",
        "# DuckDB (after)\n",
        "df = q('analytics/events', where=\"country = 'KR'\")  # 1-5 seconds\n",
        "```\n",
        "\n",
        "**Result**: 10-20x faster for small-medium queries!"
      ]
    }
  ]
}
```

### Step 4: Helm 설정 업데이트

**파일**: `/home/luke/datapond-k8s/helm/datapond/values.yaml`

```yaml
jupyter:
  enabled: true
  name: jupyter
  replicas: 1
  
  image:
    repository: datapond/jupyter-duckdb  # Custom image
    tag: latest
    pullPolicy: IfNotPresent
  
  # 환경변수 (S3 설정)
  env:
    - name: SEAWEEDFS_S3_ENDPOINT
      value: "http://{{ .Values.seaweedfs.s3.name }}:{{ .Values.seaweedfs.s3.port }}"
    - name: SEAWEEDFS_S3_ACCESS_KEY
      value: "{{ .Values.seaweedfs.s3.accessKey }}"
    - name: SEAWEEDFS_S3_SECRET_KEY
      valueFrom:
        secretKeyRef:
          name: seaweedfs-s3-secret
          key: secretKey
  
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi
```

### Step 5: 빌드 및 배포

```bash
# 1. Docker 이미지 빌드
cd /home/luke/datapond-k8s/docker/jupyter
docker build -t datapond/jupyter-duckdb:latest .

# 2. K3s로 이미지 로드
docker save datapond/jupyter-duckdb:latest | sudo k3s ctr images import -

# 3. Helm 배포
cd /home/luke/datapond-k8s/helm/datapond
helm upgrade --install datapond . -n datapond

# 4. 테스트
kubectl exec -it jupyter-<pod-id> -n datapond -- jupyter notebook list
# 브라우저에서 JupyterLab 열기
# 01_DuckDB_QuickStart.ipynb 실행
```

---

## RisingWave 통합

*(상세 내용은 Phase 2 시작 시 작성)*

### 개요

RisingWave는 Kafka/Kinesis 실시간 스트림을 PostgreSQL 호환 SQL로 처리하고 Iceberg에 자동 저장합니다.

### 통합 우선순위: P1 (Phase 2, Week 3-4)

---

## OpenMetadata 통합

*(상세 내용은 Phase 2 시작 시 작성)*

### 개요

OpenMetadata는 Airflow, Spark, Trino, MLflow에서 메타데이터를 자동 수집하여 Lineage 그래프를 생성합니다.

### 통합 우선순위: P1 (Phase 2, Week 3-4)

---

## 통합 우선순위

### Sprint Timeline

```yaml
Week 1-2 (현재 MVP Sprint):
  P0 - 즉시 통합:
    - Apache Polaris (2일)
      * Helm chart 추가
      * Trino/Spark 설정 변경
      * 마이그레이션 스크립트
      * 테스트 및 문서화
    
    - DuckDB (1일)
      * Dockerfile 작성
      * Helper 스크립트
      * 예제 노트북
      * 이미지 빌드 및 배포
  
  산출물:
    - Polaris 기반 거버넌스 활성화
    - DuckDB 통합 JupyterLab
    - 마이그레이션 가이드

Week 3-4 (Phase 2):
  P1 - Phase 2 통합:
    - RisingWave (1주)
      * Helm chart 추가
      * Kafka 연동
      * Iceberg sink 설정
      * 예제 Materialized View
    
    - OpenMetadata (1주)
      * Helm chart 추가
      * Connector 설정
      * Lineage 검증
      * UI 커스터마이징
  
  산출물:
    - 실시간 스트리밍 파이프라인
    - 자동 Lineage + 데이터 카탈로그
    - Lab 8: 실시간 분석 가이드
```

---

## End-to-End 테스트

### Polaris 거버넌스 테스트

```sql
-- 1. Namespace 생성 (팀별 격리)
CREATE NAMESPACE iceberg.team_data_engineering;
CREATE NAMESPACE iceberg.team_data_science;

-- 2. 테이블 생성
CREATE TABLE iceberg.team_data_engineering.users (
    id BIGINT,
    email STRING,
    created_at TIMESTAMP
) USING iceberg;

-- 3. 권한 부여 (Polaris API)
-- POST /api/catalog/v1/principals/alice/grants
{
  "namespace": "team_data_engineering",
  "privilege": "SELECT"
}

-- 4. 권한 확인 (alice로 로그인)
SELECT * FROM iceberg.team_data_engineering.users;  -- ✅ OK
SELECT * FROM iceberg.team_data_science.experiments;  -- ❌ Forbidden
```

### DuckDB 성능 테스트

```python
import time
from iceberg_helper import q

# 테스트: 1M rows 쿼리
start = time.time()
df = q('analytics/events', where="country = 'KR'", limit=1000000)
duration = time.time() - start

print(f"Rows: {len(df):,}")
print(f"Duration: {duration:.2f}s")
print(f"Throughput: {len(df) / duration:,.0f} rows/sec")

# Expected: < 5 seconds for 1M rows
```

---

## 다음 단계

1. **Week 1-2**: Polaris + DuckDB 통합
2. **Week 3**: RisingWave 통합 문서 완성
3. **Week 4**: OpenMetadata 통합 문서 완성
4. **Week 5+**: 프로덕션 최적화

---

**작성자**: DataPond Architecture Team  
**문의**: GitHub Issues
