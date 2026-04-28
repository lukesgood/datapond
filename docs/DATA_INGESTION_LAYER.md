# DataPond Data Ingestion Layer

**작성일**: 2026-04-28  
**버전**: 1.0.0  
**목적**: AI-Powered 데이터 수집 레이어 설계

---

## 📋 Executive Summary

현재 DataPond의 가장 큰 **Gap: 데이터 수집(Data Ingestion)**

### 문제
```yaml
현재 상황:
  - 사용자가 수동으로 데이터를 Lakehouse에 적재
  - Airflow DAG를 직접 작성해야 함
  - 각 데이터 소스마다 커스텀 코드 필요
  - 스키마 변경 대응 어려움

경쟁사:
  - Airbyte: 350+ 소스 커넥터
  - Fivetran: 400+ 커넥터, 자동 스키마 진화
  - Databricks Auto Loader: 클라우드 스토리지 자동 수집
```

### 해결책: AI-Powered Smart Ingestion

```yaml
핵심 기능:
  1. Universal Connector
     - 350+ 데이터 소스 (Airbyte 기반)
     - API, DB, SaaS, Files, Streaming
  
  2. AI Metadata Analysis
     - 자동 스키마 추론
     - 데이터 프로파일링 (통계, 품질)
     - 민감 데이터 탐지 (PII)
  
  3. Smart Data Import
     - AI 추천: "이 테이블을 Iceberg로 수집할까요?"
     - 원클릭 수집 (No-code)
     - 증분 로드 자동화
  
  4. Schema Evolution
     - 스키마 변경 자동 감지
     - Iceberg 스키마 진화 자동 적용
     - 알림 (Discord/Slack)
```

---

## 🏗️ Architecture

### Overall Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Sources                             │
│  📊 DB: PostgreSQL, MySQL, MongoDB, Oracle, SQL Server      │
│  ☁️ SaaS: Salesforce, HubSpot, Stripe, Google Analytics    │
│  📂 Files: S3, GCS, Azure Blob, SFTP, Local                │
│  🌊 Streaming: Kafka, Kinesis, Pub/Sub                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              DataPond Ingestion Layer                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          1. Source Discovery & Profiling             │  │
│  │  - Connection test                                   │  │
│  │  - Schema extraction                                 │  │
│  │  - AI metadata analysis                              │  │
│  │  - Data preview (sample 1000 rows)                   │  │
│  └─────────────────────┬────────────────────────────────┘  │
│                        │                                    │
│  ┌─────────────────────▼───────────────────────────────┐   │
│  │          2. AI-Powered Recommendations              │   │
│  │  - Target table suggestion                          │   │
│  │  - Partitioning strategy                            │   │
│  │  - Data type mapping                                │   │
│  │  - PII masking rules                                │   │
│  └─────────────────────┬────────────────────────────────┘  │
│                        │                                    │
│  ┌─────────────────────▼───────────────────────────────┐   │
│  │          3. Airbyte Connector Engine                │   │
│  │  - 350+ pre-built connectors                        │   │
│  │  - Incremental sync                                 │   │
│  │  - CDC (Change Data Capture)                        │   │
│  │  - Error handling & retry                           │   │
│  └─────────────────────┬────────────────────────────────┘  │
│                        │                                    │
│  ┌─────────────────────▼───────────────────────────────┐   │
│  │          4. Data Quality & Transformation           │   │
│  │  - AI validation rules                              │   │
│  │  - PII redaction                                    │   │
│  │  - Type conversion                                  │   │
│  │  - Deduplication                                    │   │
│  └─────────────────────┬────────────────────────────────┘  │
└────────────────────────┼────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│              SeaweedFS + Apache Iceberg                     │
│  - Bronze (Raw): 원본 그대로                                 │
│  - Silver (Cleaned): 검증 + 변환                            │
│  - Gold (Aggregated): 비즈니스 로직 적용                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔌 Component 1: Airbyte Integration

### Why Airbyte?

```yaml
장점:
  - ✅ 350+ 커넥터 (오픈소스)
  - ✅ Apache 2.0 라이센스 (안전)
  - ✅ Kubernetes 네이티브
  - ✅ Iceberg 지원 (destination)
  - ✅ CDC 지원 (실시간 변경 추적)
  - ✅ 활발한 커뮤니티

대안:
  - Fivetran: 상용 (비싸고 종속)
  - Apache NiFi: 무거움 (리소스 많이 필요)
  - Singer: 구식 (deprecated)

결정: Airbyte 통합
```

### Kubernetes Deployment

```yaml
# helm/datapond/templates/airbyte-deployment.yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: airbyte
  labels:
    app.kubernetes.io/part-of: datapond

---
# Airbyte는 자체 Helm Chart 사용
# DataPond는 dependency로 추가
# helm/datapond/Chart.yaml
dependencies:
  - name: airbyte
    version: 0.50.0
    repository: https://airbytehq.github.io/helm-charts
    condition: airbyte.enabled

---
# helm/datapond/values.yaml
airbyte:
  enabled: true
  
  # Airbyte Server (UI)
  webapp:
    enabled: true
    service:
      type: ClusterIP
      port: 80
    resources:
      requests:
        cpu: 500m
        memory: 1Gi
      limits:
        cpu: 1000m
        memory: 2Gi
  
  # Airbyte API Server
  server:
    enabled: true
    resources:
      requests:
        cpu: 500m
        memory: 1Gi
  
  # Airbyte Worker (connector 실행)
  worker:
    enabled: true
    replicas: 2
    resources:
      requests:
        cpu: 1000m
        memory: 2Gi
      limits:
        cpu: 2000m
        memory: 4Gi
  
  # Temporal (워크플로우 엔진)
  temporal:
    enabled: true
  
  # Database (PostgreSQL 재사용)
  postgresql:
    enabled: false  # DataPond의 PostgreSQL 사용
  
  # Logs (SeaweedFS S3 사용)
  logs:
    storage:
      type: S3
      s3:
        endpoint: http://seaweedfs-s3:8333
        bucket: airbyte-logs
        accessKey: ${SEAWEEDFS_S3_USER}
        secretKey: ${SEAWEEDFS_S3_PASSWORD}
  
  # Destination: Iceberg
  destinations:
    iceberg:
      enabled: true
      catalog:
        type: jdbc
        uri: jdbc:postgresql://postgres:5432/iceberg_catalog
      warehouse: s3a://iceberg/warehouse
      s3:
        endpoint: http://seaweedfs-s3:8333
        accessKey: ${SEAWEEDFS_S3_USER}
        secretKey: ${SEAWEEDFS_S3_PASSWORD}
```

### Ingress 통합

```yaml
# helm/datapond/templates/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: datapond-ingress
spec:
  rules:
  - host: {{ .Values.global.domain }}
    http:
      paths:
      # 기존 경로들...
      
      # Airbyte UI 추가
      - path: /airbyte
        pathType: Prefix
        backend:
          service:
            name: airbyte-webapp-svc
            port:
              number: 80
```

---

## 🤖 Component 2: AI Metadata Analyzer

### 기능

```yaml
1. Schema Analysis:
   - 자동 타입 추론 (int, float, string, datetime, json)
   - Nullable 여부
   - Primary Key 추천
   - Foreign Key 관계 추론

2. Data Profiling:
   - 통계: min, max, avg, median, stddev
   - Cardinality: distinct count, unique ratio
   - Missing values: null count, null ratio
   - Distribution: histogram, percentiles

3. PII Detection:
   - 민감 데이터 자동 탐지 (email, phone, SSN, credit card)
   - GDPR/HIPAA 규정 준수 체크
   - 마스킹 규칙 자동 제안

4. Quality Checks:
   - 데이터 이상 탐지 (outliers)
   - 중복 데이터 감지
   - 참조 무결성 체크
```

### Implementation

```python
# backend/app/services/metadata_analyzer.py
from typing import Dict, Any, List
import pandas as pd
from pydantic import BaseModel

class ColumnProfile(BaseModel):
    name: str
    type: str  # inferred type
    nullable: bool
    distinct_count: int
    null_count: int
    null_ratio: float
    sample_values: List[Any]
    
    # Statistics (for numeric)
    min: float = None
    max: float = None
    mean: float = None
    median: float = None
    stddev: float = None
    
    # PII detection
    is_pii: bool = False
    pii_type: str = None  # email, phone, ssn, etc.
    masking_rule: str = None

class TableProfile(BaseModel):
    source_name: str
    table_name: str
    row_count: int
    columns: List[ColumnProfile]
    primary_key_candidates: List[str]
    
    # AI Recommendations
    recommended_partition_by: List[str] = []
    recommended_cluster_by: List[str] = []
    data_quality_score: float = 0.0  # 0-100

class MetadataAnalyzer:
    """AI-Powered Metadata Analysis"""
    
    def __init__(self, litellm_client):
        self.llm = litellm_client
    
    async def analyze_source(
        self,
        connection_params: Dict[str, Any],
        sample_size: int = 1000
    ) -> TableProfile:
        """데이터 소스 분석"""
        
        # 1. 데이터 샘플링
        df = await self._sample_data(connection_params, sample_size)
        
        # 2. 기본 프로파일링
        profile = self._basic_profiling(df)
        
        # 3. AI 기반 고급 분석
        profile = await self._ai_analysis(df, profile)
        
        return profile
    
    async def _sample_data(self, params: Dict, size: int) -> pd.DataFrame:
        """데이터 샘플 추출"""
        source_type = params["type"]
        
        if source_type == "postgresql":
            import psycopg2
            conn = psycopg2.connect(**params["connection"])
            query = f"SELECT * FROM {params['table']} LIMIT {size}"
            df = pd.read_sql(query, conn)
            conn.close()
            return df
        
        elif source_type == "mysql":
            import pymysql
            conn = pymysql.connect(**params["connection"])
            query = f"SELECT * FROM {params['table']} LIMIT {size}"
            df = pd.read_sql(query, conn)
            conn.close()
            return df
        
        elif source_type == "s3":
            # S3에서 파일 샘플링
            import boto3
            s3 = boto3.client('s3')
            obj = s3.get_object(Bucket=params['bucket'], Key=params['key'])
            df = pd.read_csv(obj['Body'], nrows=size)
            return df
        
        # ... 다른 소스 타입들
    
    def _basic_profiling(self, df: pd.DataFrame) -> TableProfile:
        """기본 프로파일링"""
        columns = []
        
        for col in df.columns:
            profile = ColumnProfile(
                name=col,
                type=self._infer_type(df[col]),
                nullable=df[col].isnull().any(),
                distinct_count=df[col].nunique(),
                null_count=df[col].isnull().sum(),
                null_ratio=df[col].isnull().sum() / len(df),
                sample_values=df[col].dropna().head(5).tolist()
            )
            
            # Numeric statistics
            if pd.api.types.is_numeric_dtype(df[col]):
                profile.min = float(df[col].min())
                profile.max = float(df[col].max())
                profile.mean = float(df[col].mean())
                profile.median = float(df[col].median())
                profile.stddev = float(df[col].std())
            
            # PII detection
            profile.is_pii, profile.pii_type = self._detect_pii(df[col])
            if profile.is_pii:
                profile.masking_rule = self._suggest_masking(profile.pii_type)
            
            columns.append(profile)
        
        return TableProfile(
            source_name="unknown",
            table_name="unknown",
            row_count=len(df),
            columns=columns,
            primary_key_candidates=self._find_pk_candidates(df)
        )
    
    def _infer_type(self, series: pd.Series) -> str:
        """타입 추론"""
        if pd.api.types.is_integer_dtype(series):
            return "bigint"
        elif pd.api.types.is_float_dtype(series):
            return "double"
        elif pd.api.types.is_bool_dtype(series):
            return "boolean"
        elif pd.api.types.is_datetime64_any_dtype(series):
            return "timestamp"
        else:
            # 문자열인데 JSON/Array인지 체크
            sample = series.dropna().head(10)
            if self._is_json(sample):
                return "json"
            elif self._is_array(sample):
                return "array"
            else:
                return "string"
    
    def _detect_pii(self, series: pd.Series) -> tuple[bool, str]:
        """PII 탐지"""
        import re
        
        # Sample 10 values
        sample = series.dropna().astype(str).head(10)
        
        # Email pattern
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if sample.str.match(email_pattern).any():
            return True, "email"
        
        # Phone pattern
        phone_pattern = r'^\+?1?\d{9,15}$'
        if sample.str.match(phone_pattern).any():
            return True, "phone"
        
        # SSN pattern (US)
        ssn_pattern = r'^\d{3}-\d{2}-\d{4}$'
        if sample.str.match(ssn_pattern).any():
            return True, "ssn"
        
        # Credit card pattern
        cc_pattern = r'^\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}$'
        if sample.str.match(cc_pattern).any():
            return True, "credit_card"
        
        # Column name 기반 휴리스틱
        col_name = series.name.lower()
        if any(kw in col_name for kw in ['email', 'mail']):
            return True, "email"
        elif any(kw in col_name for kw in ['phone', 'mobile', 'tel']):
            return True, "phone"
        elif any(kw in col_name for kw in ['ssn', 'social_security']):
            return True, "ssn"
        
        return False, None
    
    def _suggest_masking(self, pii_type: str) -> str:
        """마스킹 규칙 제안"""
        rules = {
            "email": "mask_email",  # abc***@example.com
            "phone": "mask_phone",  # ***-***-1234
            "ssn": "mask_full",     # ***-**-****
            "credit_card": "mask_full"  # ****-****-****-1234
        }
        return rules.get(pii_type, "mask_full")
    
    def _find_pk_candidates(self, df: pd.DataFrame) -> List[str]:
        """Primary Key 후보 찾기"""
        candidates = []
        
        for col in df.columns:
            # Unique하고 null이 없으면 PK 후보
            if df[col].nunique() == len(df) and not df[col].isnull().any():
                candidates.append(col)
        
        return candidates
    
    async def _ai_analysis(
        self,
        df: pd.DataFrame,
        profile: TableProfile
    ) -> TableProfile:
        """AI 기반 고급 분석"""
        
        # LLM에게 메타데이터 분석 요청
        prompt = f"""
        Analyze this table metadata and provide recommendations:
        
        Table: {len(df)} rows, {len(df.columns)} columns
        
        Columns:
        {self._format_columns_for_llm(profile.columns)}
        
        Please provide:
        1. Best partition column(s) for Apache Iceberg
        2. Best clustering column(s) for query performance
        3. Data quality score (0-100)
        4. Any data quality issues you notice
        
        Respond in JSON format.
        """
        
        response = await self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="claude-sonnet",
            temperature=0.2
        )
        
        # Parse AI response
        import json
        recommendations = json.loads(response["choices"][0]["message"]["content"])
        
        profile.recommended_partition_by = recommendations.get("partition_by", [])
        profile.recommended_cluster_by = recommendations.get("cluster_by", [])
        profile.data_quality_score = recommendations.get("quality_score", 0.0)
        
        return profile
    
    def _format_columns_for_llm(self, columns: List[ColumnProfile]) -> str:
        """LLM용 컬럼 정보 포맷팅"""
        lines = []
        for col in columns:
            line = f"- {col.name} ({col.type}): "
            line += f"distinct={col.distinct_count}, "
            line += f"null_ratio={col.null_ratio:.2%}"
            if col.is_pii:
                line += f", PII={col.pii_type}"
            lines.append(line)
        return "\n".join(lines)
```

### API Endpoints

```python
# backend/app/api/ingestion.py
from fastapi import APIRouter, Depends, HTTPException
from app.services.metadata_analyzer import MetadataAnalyzer

router = APIRouter(prefix="/api/ingestion", tags=["Ingestion"])

@router.post("/analyze")
async def analyze_source(
    request: dict,
    user = Depends(get_current_user)
):
    """데이터 소스 분석"""
    
    analyzer = MetadataAnalyzer(litellm_client)
    
    try:
        profile = await analyzer.analyze_source(
            connection_params=request["source"],
            sample_size=request.get("sample_size", 1000)
        )
        
        return {
            "profile": profile.dict(),
            "recommendations": {
                "partition_by": profile.recommended_partition_by,
                "cluster_by": profile.recommended_cluster_by,
                "masking_rules": [
                    {
                        "column": col.name,
                        "type": col.pii_type,
                        "rule": col.masking_rule
                    }
                    for col in profile.columns
                    if col.is_pii
                ]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_to_lakehouse(
    request: dict,
    user = Depends(get_current_user)
):
    """Lakehouse로 데이터 수집"""
    
    # 1. Airbyte connection 생성
    connection_id = await create_airbyte_connection(
        source=request["source"],
        destination={
            "type": "iceberg",
            "catalog": "jdbc",
            "warehouse": "s3a://iceberg/warehouse",
            "table": request["target_table"]
        },
        configuration={
            "partition_by": request.get("partition_by", []),
            "sync_mode": request.get("sync_mode", "full_refresh")
        }
    )
    
    # 2. Sync 시작
    job_id = await trigger_airbyte_sync(connection_id)
    
    return {
        "connection_id": connection_id,
        "job_id": job_id,
        "status": "started"
    }

@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    user = Depends(get_current_user)
):
    """수집 작업 상태 조회"""
    status = await get_airbyte_job_status(job_id)
    
    return {
        "job_id": job_id,
        "status": status["status"],
        "rows_synced": status.get("rows_synced", 0),
        "bytes_synced": status.get("bytes_synced", 0),
        "duration_ms": status.get("duration_ms", 0)
    }
```

---

## 🎨 Component 3: Smart Import UI

### UI Flow

```typescript
// frontend/src/pages/Ingestion/SourceCatalog.tsx
import React, { useState } from 'react';

export const SourceCatalogPage: React.FC = () => {
  const [sources, setSources] = useState([]);
  const [selectedSource, setSelectedSource] = useState(null);
  
  return (
    <div className="source-catalog">
      {/* Step 1: Source Selection */}
      <SourceSelector>
        <h2>Connect Data Source</h2>
        <SourceGrid>
          {/* 카테고리별 소스 */}
          <Category name="Databases">
            <SourceCard name="PostgreSQL" icon="🐘" />
            <SourceCard name="MySQL" icon="🐬" />
            <SourceCard name="MongoDB" icon="🍃" />
            <SourceCard name="SQL Server" icon="🪟" />
          </Category>
          
          <Category name="SaaS">
            <SourceCard name="Salesforce" icon="☁️" />
            <SourceCard name="HubSpot" icon="🧲" />
            <SourceCard name="Stripe" icon="💳" />
            <SourceCard name="Google Analytics" icon="📊" />
          </Category>
          
          <Category name="Files">
            <SourceCard name="S3" icon="📦" />
            <SourceCard name="Google Cloud Storage" icon="☁️" />
            <SourceCard name="SFTP" icon="📂" />
          </Category>
          
          <Category name="Streaming">
            <SourceCard name="Kafka" icon="🌊" />
            <SourceCard name="Kinesis" icon="🚀" />
          </Category>
        </SourceGrid>
      </SourceSelector>
      
      {/* Step 2: Connection Setup */}
      {selectedSource && (
        <ConnectionSetup source={selectedSource}>
          <Form>
            {/* 소스별 필드 동적 생성 */}
            <Input label="Host" placeholder="localhost" />
            <Input label="Port" placeholder="5432" />
            <Input label="Database" placeholder="mydb" />
            <Input label="Username" />
            <Input label="Password" type="password" />
            
            <Button onClick={testConnection}>Test Connection</Button>
          </Form>
        </ConnectionSetup>
      )}
      
      {/* Step 3: Source Discovery */}
      {connectionSuccess && (
        <SourceDiscovery>
          <h3>Available Tables</h3>
          <TableList>
            {tables.map(table => (
              <TableCard
                key={table.name}
                table={table}
                onAnalyze={() => analyzeTable(table)}
              />
            ))}
          </TableList>
        </SourceDiscovery>
      )}
      
      {/* Step 4: AI Analysis Results */}
      {analysis && (
        <AnalysisResults analysis={analysis}>
          {/* 메타데이터 */}
          <MetadataSection>
            <h4>Table: {analysis.table_name}</h4>
            <p>Rows: {analysis.row_count.toLocaleString()}</p>
            <p>Columns: {analysis.columns.length}</p>
            <p>Quality Score: {analysis.data_quality_score}/100</p>
          </MetadataSection>
          
          {/* 컬럼 프로파일 */}
          <ColumnProfileTable>
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Distinct</th>
                <th>Nulls</th>
                <th>PII</th>
              </tr>
            </thead>
            <tbody>
              {analysis.columns.map(col => (
                <tr key={col.name}>
                  <td>{col.name}</td>
                  <td>{col.type}</td>
                  <td>{col.distinct_count}</td>
                  <td>{(col.null_ratio * 100).toFixed(1)}%</td>
                  <td>
                    {col.is_pii && (
                      <Badge color="warning">
                        {col.pii_type}
                        <Tooltip>
                          Masking rule: {col.masking_rule}
                        </Tooltip>
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </ColumnProfileTable>
          
          {/* AI Recommendations */}
          <RecommendationsCard>
            <h4>🤖 AI Recommendations</h4>
            <ul>
              <li>
                <strong>Partition by:</strong> 
                {analysis.recommended_partition_by.join(', ')}
              </li>
              <li>
                <strong>Cluster by:</strong>
                {analysis.recommended_cluster_by.join(', ')}
              </li>
              <li>
                <strong>PII Columns:</strong> 
                {analysis.columns.filter(c => c.is_pii).length} found
                <Button size="small">Apply Masking</Button>
              </li>
            </ul>
          </RecommendationsCard>
        </AnalysisResults>
      )}
      
      {/* Step 5: Import Configuration */}
      {analysis && (
        <ImportConfig>
          <h3>Import to Lakehouse</h3>
          <Form>
            <Input
              label="Target Table"
              value={`bronze.${analysis.table_name}`}
              onChange={setTargetTable}
            />
            
            <Select label="Sync Mode">
              <option value="full_refresh">Full Refresh</option>
              <option value="incremental">Incremental (Append)</option>
              <option value="cdc">CDC (Change Data Capture)</option>
            </Select>
            
            <MultiSelect
              label="Partition Columns"
              options={analysis.columns.map(c => c.name)}
              value={partitionColumns}
              onChange={setPartitionColumns}
              suggestions={analysis.recommended_partition_by}
            />
            
            <MultiSelect
              label="Clustering Columns"
              options={analysis.columns.map(c => c.name)}
              value={clusterColumns}
              onChange={setClusterColumns}
              suggestions={analysis.recommended_cluster_by}
            />
            
            <Checkbox
              label="Apply PII Masking"
              checked={applyMasking}
              onChange={setApplyMasking}
            />
            
            <Button
              size="large"
              variant="primary"
              onClick={startImport}
            >
              Start Import
            </Button>
          </Form>
        </ImportConfig>
      )}
      
      {/* Step 6: Import Progress */}
      {importJob && (
        <ImportProgress job={importJob}>
          <ProgressBar value={job.progress} />
          <Stats>
            <Stat label="Rows" value={job.rows_synced.toLocaleString()} />
            <Stat label="Bytes" value={formatBytes(job.bytes_synced)} />
            <Stat label="Duration" value={formatDuration(job.duration_ms)} />
          </Stats>
          
          {job.status === 'completed' && (
            <SuccessMessage>
              ✅ Import completed!
              <Button onClick={() => navigateTo(`/tables/${targetTable}`)}>
                View Table
              </Button>
            </SuccessMessage>
          )}
        </ImportProgress>
      )}
    </div>
  );
};
```

---

## 🔄 Component 4: Auto Sync & Schema Evolution

### Background Job (Airflow DAG)

```python
# airflow/dags/auto_sync_sources.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

def check_schema_changes():
    """스키마 변경 감지"""
    sources = get_all_connected_sources()
    
    for source in sources:
        # 현재 스키마 가져오기
        current_schema = get_source_schema(source)
        
        # 이전 스키마와 비교
        previous_schema = get_cached_schema(source)
        
        if current_schema != previous_schema:
            # 변경사항 분석
            changes = analyze_schema_diff(previous_schema, current_schema)
            
            # Iceberg 테이블 자동 업데이트
            if changes["addedColumns"]:
                add_columns_to_iceberg(source.target_table, changes["addedColumns"])
            
            # 알림
            send_notification(
                channel="slack",
                message=f"Schema changed in {source.name}: {changes}"
            )
            
            # 캐시 업데이트
            update_cached_schema(source, current_schema)

def sync_incremental_data():
    """증분 데이터 동기화"""
    sources = get_all_sources(sync_mode="incremental")
    
    for source in sources:
        # Airbyte sync 트리거
        trigger_airbyte_sync(source.connection_id)

dag = DAG(
    'auto_sync_sources',
    default_args={
        'owner': 'datapond',
        'retries': 3,
        'retry_delay': timedelta(minutes=5)
    },
    description='Auto sync and schema evolution',
    schedule_interval='0 * * * *',  # 매시간
    start_date=datetime(2026, 1, 1),
    catchup=False
)

check_schema = PythonOperator(
    task_id='check_schema_changes',
    python_callable=check_schema_changes,
    dag=dag
)

sync_data = PythonOperator(
    task_id='sync_incremental_data',
    python_callable=sync_incremental_data,
    dag=dag
)

check_schema >> sync_data
```

---

## 📊 Supported Data Sources

### Tier 1 (High Priority)

```yaml
Databases:
  - PostgreSQL ✅
  - MySQL ✅
  - MongoDB ✅
  - SQL Server ✅
  - Oracle (enterprise)

Cloud Data Warehouses:
  - Snowflake ✅
  - BigQuery ✅
  - Redshift ✅

SaaS:
  - Salesforce ✅
  - HubSpot ✅
  - Stripe ✅
  - Google Analytics ✅

Files:
  - S3 ✅
  - Google Cloud Storage ✅
  - Azure Blob ✅
  - SFTP ✅

Streaming:
  - Kafka ✅
  - AWS Kinesis ✅
  - Google Pub/Sub ✅
```

### Tier 2 (Medium Priority)

```yaml
Databases:
  - Cassandra
  - DynamoDB
  - Elasticsearch

SaaS:
  - Shopify
  - Zendesk
  - Intercom
  - Slack
  - GitHub

Ad Platforms:
  - Google Ads
  - Facebook Ads
  - LinkedIn Ads
```

---

## 🎯 차별화 포인트

### DataPond vs Competitors

| 기능 | Airbyte | Fivetran | DataPond |
|------|---------|----------|----------|
| **커넥터 수** | 350+ | 400+ | 350+ (Airbyte 기반) |
| **AI 메타데이터 분석** | ❌ | ❌ | ✅ **차별화!** |
| **AI 추천** | ❌ | 일부 | ✅ **완전 자동** |
| **PII 자동 탐지** | ❌ | ✅ | ✅ **+ AI 마스킹** |
| **원클릭 수집** | ❌ (복잡) | ✅ | ✅ **+ AI 설정** |
| **라이센스** | Apache 2.0 | 상용 | Apache 2.0 |
| **비용** | 무료 | $$$$ | 무료 |
| **통합 플랫폼** | 별도 설치 | 별도 SaaS | ✅ **내장** |

### 핵심 차별화

1. **AI-Powered Metadata Analysis**
   ```
   - 다른 도구: 수동 스키마 매핑
   - DataPond: AI가 자동 분석 + 추천
   ```

2. **Zero-Code Import**
   ```
   - 다른 도구: 복잡한 설정
   - DataPond: "이 테이블 수집할까요?" → 원클릭
   ```

3. **Integrated Platform**
   ```
   - 다른 도구: 별도 제품 (추가 비용)
   - DataPond: 내장 (추가 비용 없음)
   ```

---

## 📈 Impact on Product

### 새로운 Value Proposition

```yaml
Before:
  "AI-Native Open Lakehouse Platform"

After:
  "Zero-Code AI Data Platform"
  
  - 코딩 없이 350+ 데이터 소스 연결
  - AI가 자동으로 스키마 분석 및 최적화
  - 원클릭으로 Lakehouse 수집
```

### User Journey 개선

```yaml
Before (Without Ingestion Layer):
  1. 사용자가 Airflow DAG 작성 (30분)
  2. Spark job 코딩 (1시간)
  3. 스키마 수동 매핑 (30분)
  4. 에러 디버깅 (1시간)
  Total: 3시간

After (With Smart Ingestion):
  1. 소스 선택 (1분)
  2. 연결 정보 입력 (2분)
  3. AI 분석 확인 (1분)
  4. 원클릭 수집 (1분)
  Total: 5분!

생산성 향상: 36배!
```

### Positioning 변화

```
Before:
  "Databricks alternative for engineers"
  (타겟: 데이터 엔지니어)

After:
  "Databricks alternative for everyone"
  (타겟: 데이터 엔지니어 + 분석가 + 비즈니스 유저)
```

---

## 🚀 Implementation Plan

### Phase 1 (2주)
```yaml
- [ ] Airbyte Helm integration
- [ ] Basic metadata analyzer (no AI)
- [ ] PostgreSQL, MySQL 커넥터 테스트
- [ ] Simple UI (테이블 목록 + 수집 버튼)
```

### Phase 2 (4주)
```yaml
- [ ] AI metadata analysis (LiteLLM)
- [ ] PII detection
- [ ] AI recommendations (partition, cluster)
- [ ] Full UI (6-step wizard)
```

### Phase 3 (6주)
```yaml
- [ ] Schema evolution 자동화
- [ ] 350+ 커넥터 테스트 (주요 20개)
- [ ] CDC 지원
- [ ] Real-time monitoring
```

---

## 🎯 Conclusion

Data Ingestion Layer 추가로:

1. **완전한 플랫폼** - 수집 → 저장 → 처리 → 분석 → ML
2. **차별화 강화** - AI-Powered Smart Ingestion
3. **진입 장벽 제거** - No-code로 비개발자도 사용
4. **시장 확대** - 엔지니어 → 전체 데이터 팀

이것이 DataPond를 **진정한 Databricks 대안**으로 만들어줍니다!
