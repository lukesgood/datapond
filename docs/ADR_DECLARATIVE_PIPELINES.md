# ADR: Declarative Pipeline Framework (DataPond Live Tables)

**Status:** Accepted  
**Date:** 2026-04-30  
**Author:** Architecture Agent  
**Sprint:** 2.1.0 Sprint 2  
**Supersedes:** N/A

---

## 1. Problem Statement

DataPond needs a **Delta Live Tables (DLT) equivalent** to compete with Databricks on enterprise PoCs. Currently, users must:

1. Write imperative Airflow DAGs manually (50-200 lines per pipeline)
2. Manage table dependencies by hand
3. Wire data quality checks into custom operators
4. Manually register lineage in OpenMetadata
5. Handle incremental logic independently per task

This results in:
- 3-5x slower pipeline development vs. Databricks DLT
- Error-prone dependency management
- Inconsistent data quality enforcement
- Incomplete lineage tracking

**Goal:** Reduce pipeline authoring to declarative Python definitions that auto-generate DAGs, enforce quality, track lineage, and manage incremental state.

---

## 2. Design Decisions

### Decision 1: Python Decorator DSL (not YAML, not SQL-only)

**Choice:** Python decorators with function-body SQL/DataFrame logic

**Rationale:**
- Matches DLT's developer ergonomics (familiar to Databricks users)
- Python allows complex transformations beyond pure SQL
- Type-safe with Pydantic validation at definition time
- IDE autocomplete and linting support
- Easier to unit test than YAML-based approaches

**Rejected alternatives:**
- YAML pipelines (Prefect-style): Less expressive, no inline logic
- SQL-only (dbt-style): Cannot handle complex Python transforms
- Notebook-first: Poor version control, no reusability

### Decision 2: Airflow as Execution Engine (batch), RisingWave as Streaming Engine

**Choice:** Generate Airflow DAGs for batch; generate RisingWave MVs for streaming

**Rationale:**
- Airflow is already deployed in DataPond (Helm chart exists)
- Airflow REST API is fully integrated (`/api/airflow/*` endpoints exist)
- RisingWave handles streaming with PostgreSQL-compatible SQL
- Separation allows independent scheduling and scaling
- Both engines share the Polaris catalog for table metadata

**Rejected alternatives:**
- Custom scheduler: Too much engineering, Airflow is battle-tested
- Dagster: Requires separate deployment, overlaps with existing Airflow
- Spark Structured Streaming: Higher resource cost, more complex

### Decision 3: Polaris + Iceberg as Table Target

**Choice:** All tables materialized as Iceberg tables via Polaris REST Catalog

**Rationale:**
- Single catalog for all engines (Trino, Spark, DuckDB can read outputs)
- ACID guarantees and time-travel out of the box
- Polaris provides RBAC at table/namespace level
- Consistent with DataPond's unified catalog architecture

### Decision 4: OpenMetadata for Automatic Lineage

**Choice:** Pipeline compiler emits lineage events to OpenMetadata API at DAG generation time and runtime

**Rationale:**
- OpenMetadata already tracks Trino/Airflow lineage
- Adding pipeline-level lineage closes the gap (source -> transform -> target)
- REST API at `openmetadata-server:8585` is available
- Provides data quality test results integration

### Decision 5: Trino as Default Query Engine for Batch Transforms

**Choice:** Use Trino for SQL-based batch transformations (CTAS into Iceberg)

**Rationale:**
- Trino is always active in DataPond (unlike Spark which is disabled by default)
- Trino supports Iceberg CREATE TABLE AS SELECT directly
- Sub-second query planning for moderate data volumes (<100GB per table)
- For larger volumes, framework can switch to Spark when enabled

---

## 3. Architecture Overview

### 3.1 System Components

```
                    ┌─────────────────────────────────┐
                    │       Pipeline Definition        │
                    │   (Python DSL with decorators)   │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │        Pipeline Compiler         │
                    │  - Dependency resolution         │
                    │  - Quality constraint injection  │
                    │  - Lineage graph extraction      │
                    │  - Incremental state mgmt        │
                    └───────┬───────────────┬─────────┘
                            │               │
               ┌────────────▼────┐   ┌──────▼──────────────┐
               │  Batch Target   │   │  Streaming Target    │
               │  (Airflow DAG)  │   │  (RisingWave DDL)    │
               └────────┬───────┘   └──────┬──────────────┘
                        │                   │
          ┌─────────────▼─────────┐   ┌────▼────────────────┐
          │   Execution Engine    │   │   RisingWave Engine  │
          │  ┌──────┐ ┌───────┐  │   │  - CREATE SOURCE     │
          │  │Trino │ │ Spark │  │   │  - CREATE MV         │
          │  └──┬───┘ └───┬───┘  │   │  - CREATE SINK       │
          │     └─────┬───┘      │   └────┬────────────────┘
          └───────────┼──────────┘        │
                      │                   │
          ┌───────────▼───────────────────▼──────────────┐
          │              Apache Polaris                    │
          │          (Iceberg REST Catalog)                │
          │  - Table registration                         │
          │  - Schema evolution                           │
          │  - RBAC enforcement                           │
          └───────────────────┬──────────────────────────┘
                              │
          ┌───────────────────▼──────────────────────────┐
          │            SeaweedFS (S3)                      │
          │         Iceberg Data Files                     │
          └──────────────────────────────────────────────┘

          ┌──────────────────────────────────────────────┐
          │            OpenMetadata                        │
          │  - Pipeline lineage                           │
          │  - Table lineage                              │
          │  - Quality test results                       │
          │  - Column-level lineage                       │
          └──────────────────────────────────────────────┘
```

### 3.2 Data Flow (Batch Pipeline)

```
1. Developer writes pipeline.py with @live_table decorators
2. CLI command: `datapond pipeline deploy my_pipeline.py`
3. Compiler:
   a. Parses decorators → builds dependency DAG
   b. Validates quality constraints
   c. Resolves incremental checkpoints
   d. Generates Airflow DAG Python file
   e. Registers lineage in OpenMetadata
4. Airflow picks up generated DAG
5. Each task:
   a. Checks quality constraints (pre-conditions)
   b. Executes Trino SQL (CTAS/INSERT INTO)
   c. Validates output quality (post-conditions)
   d. Updates incremental checkpoint
   e. Emits lineage event
```

### 3.3 Data Flow (Streaming Pipeline)

```
1. Developer writes stream_pipeline.py with @live_table(mode="streaming")
2. CLI command: `datapond pipeline deploy stream_pipeline.py --streaming`
3. Compiler:
   a. Parses decorators → builds streaming topology
   b. Generates RisingWave DDL (CREATE SOURCE, CREATE MV, CREATE SINK)
   c. Registers lineage in OpenMetadata
4. DDL executed against RisingWave (port 4566)
5. RisingWave continuously processes and sinks to Iceberg
```

---

## 4. DSL Design

### 4.1 Core Decorators

```python
from datapond.pipelines import live_table, source, quality, pipeline

# Pipeline declaration (top-level)
@pipeline(
    name="ecommerce_analytics",
    schedule="@hourly",
    tags=["ecommerce", "analytics"],
    owner="data-team@company.com"
)

# Source table (external data reference)
@source(
    name="raw_orders",
    connection="postgres_oltp",          # Airflow connection ID
    table="public.orders",
    mode="incremental",                  # full_refresh | incremental | streaming
    watermark_column="updated_at",       # For incremental detection
    catalog="datapond",
    namespace="bronze"
)

# Live table (transformation)
@live_table(
    name="clean_orders",
    comment="Cleaned and validated orders",
    catalog="datapond",
    namespace="silver",
    mode="incremental",
    partition_by=["order_date"],
    properties={"write.format.default": "parquet"}
)
@quality.expect("valid_amount", "amount > 0")
@quality.expect_or_drop("valid_status", "status IN ('pending','shipped','delivered','cancelled')")
@quality.expect_or_fail("non_null_id", "order_id IS NOT NULL")
def clean_orders():
    """Transform raw orders into clean silver table."""
    return """
        SELECT
            order_id,
            customer_id,
            CAST(amount AS DECIMAL(10,2)) AS amount,
            status,
            CAST(created_at AS DATE) AS order_date,
            updated_at
        FROM {{ source('raw_orders') }}
        WHERE amount > 0
    """


# Aggregation table (depends on clean_orders)
@live_table(
    name="daily_revenue",
    comment="Daily revenue aggregation",
    catalog="datapond",
    namespace="gold",
    mode="incremental",
    partition_by=["order_date"]
)
@quality.expect("positive_revenue", "total_revenue >= 0")
def daily_revenue():
    """Aggregate daily revenue from clean orders."""
    return """
        SELECT
            order_date,
            COUNT(*) AS order_count,
            SUM(amount) AS total_revenue,
            AVG(amount) AS avg_order_value
        FROM {{ ref('clean_orders') }}
        WHERE status != 'cancelled'
        GROUP BY order_date
    """
```

### 4.2 Streaming Table Definition

```python
from datapond.pipelines import live_table, streaming_source, quality

@streaming_source(
    name="kafka_clickstream",
    connector="kafka",
    topic="user.clickstream",
    format="json",
    schema={
        "user_id": "VARCHAR",
        "page_url": "VARCHAR",
        "event_type": "VARCHAR",
        "timestamp": "TIMESTAMP"
    }
)

@live_table(
    name="realtime_page_views",
    comment="Real-time page view counts (1-minute windows)",
    catalog="datapond",
    namespace="streaming",
    mode="streaming",
    engine="risingwave"
)
@quality.expect("valid_window", "window_start IS NOT NULL")
def realtime_page_views():
    """Streaming aggregation of page views."""
    return """
        SELECT
            page_url,
            COUNT(*) AS view_count,
            COUNT(DISTINCT user_id) AS unique_users,
            window_start,
            window_end
        FROM TUMBLE(
            {{ streaming_source('kafka_clickstream') }},
            timestamp,
            INTERVAL '1 MINUTE'
        )
        GROUP BY page_url, window_start, window_end
    """
```

### 4.3 Python Transform (Non-SQL)

```python
from datapond.pipelines import live_table, quality
import pandas as pd

@live_table(
    name="customer_segments",
    comment="ML-based customer segmentation",
    catalog="datapond",
    namespace="gold",
    mode="full_refresh",
    engine="python"  # Executes in-process with DuckDB/pandas
)
@quality.expect("valid_segment", "segment IS NOT NULL")
def customer_segments(context):
    """Python-based transformation using pandas."""
    # Read upstream table via DuckDB
    df = context.read_table("clean_orders")

    # Python logic
    customer_agg = df.groupby("customer_id").agg(
        total_spend=("amount", "sum"),
        order_count=("order_id", "count")
    ).reset_index()

    # Segmentation logic
    customer_agg["segment"] = pd.cut(
        customer_agg["total_spend"],
        bins=[0, 100, 500, float("inf")],
        labels=["low", "medium", "high"]
    )

    return customer_agg
```

### 4.4 Template Functions

| Function | Description | Example |
|----------|-------------|---------|
| `{{ source('name') }}` | Reference a @source table | `FROM {{ source('raw_orders') }}` |
| `{{ ref('name') }}` | Reference another @live_table | `FROM {{ ref('clean_orders') }}` |
| `{{ streaming_source('name') }}` | Reference a @streaming_source | `FROM {{ streaming_source('kafka_clicks') }}` |
| `{{ incremental_filter() }}` | Auto-inject WHERE for incremental | `WHERE {{ incremental_filter() }}` |
| `{{ current_timestamp() }}` | Pipeline execution timestamp | `{{ current_timestamp() }}` |

---

## 5. DAG Generation Strategy

### 5.1 Compilation Process

```python
class PipelineCompiler:
    """
    Compiles decorated pipeline definitions into executable artifacts.

    Steps:
    1. Discovery: Find all @pipeline, @source, @live_table decorated functions
    2. Resolution: Build dependency graph from {{ ref() }} and {{ source() }}
    3. Validation: Check for cycles, missing refs, invalid quality constraints
    4. Code Generation: Produce Airflow DAG / RisingWave DDL
    5. Registration: Register lineage in OpenMetadata
    """

    def compile(self, pipeline_module: str) -> CompilationResult:
        # 1. Import and discover
        tables = self.discover_tables(pipeline_module)

        # 2. Build dependency graph
        graph = self.resolve_dependencies(tables)

        # 3. Validate
        self.validate(graph)

        # 4. Generate artifacts
        if self.is_streaming(graph):
            artifact = self.generate_risingwave_ddl(graph)
        else:
            artifact = self.generate_airflow_dag(graph)

        # 5. Register lineage
        self.register_lineage(graph)

        return CompilationResult(
            artifact=artifact,
            graph=graph,
            lineage_registered=True
        )
```

### 5.2 Dependency Resolution

```
Input pipeline with tables:
  - raw_orders (source)
  - clean_orders (refs: raw_orders)
  - daily_revenue (refs: clean_orders)
  - customer_segments (refs: clean_orders)

Resolved DAG:

  raw_orders ──► clean_orders ──┬──► daily_revenue
                                │
                                └──► customer_segments

Airflow task order:
  Task 1: ingest_raw_orders (PythonOperator - extract from source)
  Task 2: transform_clean_orders (TrinoOperator - CTAS)
  Task 3a: transform_daily_revenue (TrinoOperator - CTAS) [parallel]
  Task 3b: transform_customer_segments (PythonOperator - pandas) [parallel]
```

### 5.3 Generated Airflow DAG (Output)

```python
# AUTO-GENERATED by DataPond Pipeline Compiler
# Source: pipelines/ecommerce_analytics.py
# Generated: 2026-04-30T10:00:00Z
# DO NOT EDIT MANUALLY

from airflow import DAG
from airflow.utils.dates import days_ago
from datapond.operators import (
    TrinoOperator,
    PolarisTableOperator,
    QualityCheckOperator,
    IncrementalCheckpointOperator,
    SourceIngestOperator,
    PythonTransformOperator,
    LineageEmitOperator
)

default_args = {
    "owner": "data-team@company.com",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="datapond__ecommerce_analytics",
    default_args=default_args,
    schedule_interval="@hourly",
    start_date=days_ago(1),
    catchup=False,
    tags=["datapond-pipeline", "ecommerce", "analytics"],
    doc_md="""
    ## ecommerce_analytics
    Auto-generated pipeline from DataPond Live Tables.
    Source: `pipelines/ecommerce_analytics.py`
    """,
) as dag:

    # === Source: raw_orders ===
    ingest_raw_orders = SourceIngestOperator(
        task_id="ingest__raw_orders",
        connection_id="postgres_oltp",
        source_table="public.orders",
        target_catalog="datapond",
        target_namespace="bronze",
        target_table="raw_orders",
        mode="incremental",
        watermark_column="updated_at",
    )

    # === Table: clean_orders ===
    quality_pre__clean_orders = QualityCheckOperator(
        task_id="quality_pre__clean_orders",
        checks=[
            {"name": "valid_amount", "sql": "amount > 0", "action": "expect"},
            {"name": "valid_status", "sql": "status IN ('pending','shipped','delivered','cancelled')", "action": "expect_or_drop"},
            {"name": "non_null_id", "sql": "order_id IS NOT NULL", "action": "expect_or_fail"},
        ],
        source_table="datapond.bronze.raw_orders",
    )

    transform__clean_orders = TrinoOperator(
        task_id="transform__clean_orders",
        sql="""
            CREATE TABLE IF NOT EXISTS datapond.silver.clean_orders
            WITH (partitioning = ARRAY['order_date'], format = 'PARQUET')
            AS SELECT ... FROM datapond.bronze.raw_orders WHERE ...
        """,
        trino_conn_id="trino_default",
    )

    checkpoint__clean_orders = IncrementalCheckpointOperator(
        task_id="checkpoint__clean_orders",
        table="datapond.silver.clean_orders",
        watermark_column="updated_at",
    )

    lineage__clean_orders = LineageEmitOperator(
        task_id="lineage__clean_orders",
        pipeline="ecommerce_analytics",
        source_tables=["datapond.bronze.raw_orders"],
        target_table="datapond.silver.clean_orders",
    )

    # === Table: daily_revenue ===
    transform__daily_revenue = TrinoOperator(
        task_id="transform__daily_revenue",
        sql="...",
        trino_conn_id="trino_default",
    )

    # === Dependencies ===
    ingest_raw_orders >> quality_pre__clean_orders >> transform__clean_orders
    transform__clean_orders >> [checkpoint__clean_orders, lineage__clean_orders]
    transform__clean_orders >> transform__daily_revenue
```

### 5.4 Error Handling Strategy

| Scenario | Behavior |
|----------|----------|
| `@expect` violation | Log warning, continue execution, report to OpenMetadata |
| `@expect_or_drop` violation | Filter out bad rows, log count, continue |
| `@expect_or_fail` violation | Fail task, trigger alert, halt downstream |
| Trino query failure | Retry per `default_args.retries`, then fail |
| Source connection failure | Retry with exponential backoff, alert on 3rd failure |
| Polaris catalog error | Fail immediately (structural issue) |
| Cyclic dependency detected | Fail at compile time with clear error message |

---

## 6. Integration Architecture

### 6.1 RisingWave Streaming Integration

```
Pipeline Definition (mode="streaming")
         │
         ▼
┌─────────────────────────────┐
│   Streaming Compiler        │
│   1. Parse streaming_source │
│   2. Parse live_table(mode= │
│      "streaming")           │
│   3. Generate DDL sequence  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   RisingWave (port 4566)    │
│                             │
│   CREATE SOURCE kafka_src   │
│     WITH (connector='kafka',│
│     topic='...', ...)       │
│                             │
│   CREATE MATERIALIZED VIEW  │
│     realtime_page_views AS  │
│     SELECT ... FROM kafka.. │
│                             │
│   CREATE SINK iceberg_sink  │
│     FROM realtime_page_views│
│     WITH (connector='iceberg│
│     ', catalog='polaris',...)│
└─────────────────────────────┘
```

**Generated RisingWave DDL:**

```sql
-- Source
CREATE SOURCE IF NOT EXISTS kafka_clickstream
WITH (
    connector = 'kafka',
    topic = 'user.clickstream',
    properties.bootstrap.server = 'kafka:9092',
    scan.startup.mode = 'latest'
) FORMAT PLAIN ENCODE JSON;

-- Materialized View (the live table)
CREATE MATERIALIZED VIEW realtime_page_views AS
SELECT
    page_url,
    COUNT(*) AS view_count,
    COUNT(DISTINCT user_id) AS unique_users,
    window_start,
    window_end
FROM TUMBLE(kafka_clickstream, timestamp, INTERVAL '1 MINUTE')
GROUP BY page_url, window_start, window_end;

-- Sink to Iceberg (via Polaris)
CREATE SINK realtime_page_views_sink FROM realtime_page_views
WITH (
    connector = 'iceberg',
    type = 'upsert',
    primary_key = 'page_url, window_start',
    catalog.type = 'rest',
    catalog.uri = 'http://polaris:8181/api/catalog',
    catalog.name = 'datapond',
    database.name = 'streaming',
    table.name = 'realtime_page_views',
    s3.endpoint = 'http://seaweedfs-filer:8333',
    s3.access.key = '${SEAWEEDFS_ACCESS_KEY}',
    s3.secret.key = '${SEAWEEDFS_SECRET_KEY}'
);
```

### 6.2 Polaris/Iceberg Integration

```
Pipeline Compiler
       │
       ▼
┌──────────────────────────────┐
│  Polaris Client              │
│  (REST API at :8181)         │
│                              │
│  1. Create namespace if not  │
│     exists (bronze/silver/   │
│     gold/streaming)          │
│                              │
│  2. Register table metadata  │
│     (schema, partitioning,   │
│      properties)             │
│                              │
│  3. Grant access (RBAC)      │
│     based on pipeline owner  │
└──────────────────────────────┘
```

**API calls during deployment:**

```python
class PolarisIntegration:
    BASE_URL = "http://polaris:8181/api/catalog/v1"

    async def ensure_namespace(self, catalog: str, namespace: str):
        """Create namespace if not exists."""
        await self.client.post(
            f"{self.BASE_URL}/{catalog}/namespaces",
            json={"namespace": [namespace]}
        )

    async def register_table(self, table_def: LiveTableDef):
        """Register or update table in Polaris catalog."""
        await self.client.post(
            f"{self.BASE_URL}/{table_def.catalog}/namespaces/"
            f"{table_def.namespace}/tables",
            json={
                "name": table_def.name,
                "schema": table_def.iceberg_schema,
                "partition-spec": table_def.partition_spec,
                "properties": table_def.properties
            }
        )
```

### 6.3 OpenMetadata Lineage Integration

```
Pipeline Compiler (compile time)
       │
       ├──► Create Pipeline entity
       ├──► Create Table entities (source + target)
       └──► Create Lineage edges (source → pipeline → target)

Pipeline Runtime (execution time)
       │
       ├──► Update pipeline run status
       ├──► Report quality test results
       └──► Update column-level lineage (if SQL parsed)
```

**OpenMetadata API integration:**

```python
class OpenMetadataLineage:
    BASE_URL = "http://openmetadata-server:8585/api/v1"

    async def register_pipeline(self, pipeline_def):
        """Register pipeline entity."""
        await self.client.put(
            f"{self.BASE_URL}/pipelines",
            json={
                "name": pipeline_def.name,
                "service": {"id": self.datapond_service_id},
                "tasks": [
                    {"name": t.name, "description": t.comment}
                    for t in pipeline_def.tables
                ]
            }
        )

    async def add_lineage(self, source_fqn: str, target_fqn: str, pipeline_fqn: str):
        """Add lineage edge."""
        await self.client.put(
            f"{self.BASE_URL}/lineage",
            json={
                "edge": {
                    "fromEntity": {"type": "table", "fqn": source_fqn},
                    "toEntity": {"type": "table", "fqn": target_fqn},
                    "lineageDetails": {
                        "pipeline": {"type": "pipeline", "fqn": pipeline_fqn}
                    }
                }
            }
        )

    async def report_quality_results(self, table_fqn: str, results: list):
        """Report data quality test results."""
        await self.client.put(
            f"{self.BASE_URL}/dataQuality/testCases/testCaseResults",
            json={
                "testCase": {"fullyQualifiedName": table_fqn},
                "testCaseResults": results
            }
        )
```

### 6.4 Airflow Integration

The generated DAGs are deployed to Airflow's DAG folder via:

```
Pipeline Definition (.py)
       │
       ▼
Pipeline Compiler
       │
       ▼
Generated DAG (.py)
       │
       ▼
/opt/airflow/dags/datapond_pipelines/
       │
       ▼
Airflow Scheduler (auto-detects new DAG)
       │
       ▼
DataPond API (/api/airflow/dags) ──► Frontend UI
```

**DAG deployment mechanism:**
- In K8s: ConfigMap or PersistentVolume shared with Airflow worker pods
- Generated DAGs placed in `datapond_pipelines/` subdirectory
- Airflow's `dag_discovery_safe_mode` ensures no broken imports affect other DAGs

---

## 7. Implementation Plan

### 7.1 File Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── pipelines.py              # REST API endpoints for pipeline management
│   │   └── ... (existing)
│   ├── pipelines/                     # Core pipeline framework
│   │   ├── __init__.py               # Public API exports
│   │   ├── decorators.py             # @live_table, @source, @quality decorators
│   │   ├── compiler.py              # Pipeline compiler (main orchestrator)
│   │   ├── dependency_graph.py      # DAG resolution and cycle detection
│   │   ├── dag_generator.py         # Airflow DAG code generation
│   │   ├── streaming_generator.py   # RisingWave DDL generation
│   │   ├── quality.py               # Data quality constraint engine
│   │   ├── incremental.py           # Incremental processing state
│   │   ├── template_engine.py       # {{ ref() }}, {{ source() }} resolution
│   │   └── models.py                # Pydantic models for pipeline definitions
│   ├── integrations/
│   │   ├── polaris_client.py        # Polaris REST API client
│   │   ├── openmetadata_client.py   # OpenMetadata lineage client
│   │   ├── risingwave_client.py     # RisingWave DDL executor
│   │   └── trino_client.py          # Trino query executor
│   └── operators/                    # Custom Airflow operators
│       ├── __init__.py
│       ├── trino_operator.py        # Execute Trino SQL
│       ├── quality_operator.py      # Run quality checks
│       ├── source_ingest_operator.py # Ingest from external sources
│       ├── python_transform_operator.py # Execute Python transforms
│       ├── checkpoint_operator.py   # Manage incremental state
│       └── lineage_operator.py      # Emit lineage to OpenMetadata
├── cli/
│   ├── __init__.py
│   └── pipeline_cli.py             # CLI: datapond pipeline [deploy|validate|status]
└── tests/
    ├── test_decorators.py
    ├── test_compiler.py
    ├── test_dag_generator.py
    ├── test_quality.py
    └── test_integration.py
```

### 7.2 Key Classes

```python
# === decorators.py ===
class LiveTableRegistry:
    """Global registry of all decorated tables in a pipeline module."""
    _tables: Dict[str, LiveTableDef] = {}
    _sources: Dict[str, SourceDef] = {}
    _pipeline: Optional[PipelineDef] = None

def live_table(name, comment="", catalog="datapond", namespace="silver",
               mode="full_refresh", partition_by=None, engine="trino",
               properties=None):
    """Decorator to define a live table."""
    def decorator(func):
        table_def = LiveTableDef(
            name=name, comment=comment, catalog=catalog,
            namespace=namespace, mode=mode, partition_by=partition_by,
            engine=engine, properties=properties or {},
            transform_fn=func, quality_checks=[]
        )
        LiveTableRegistry.register(table_def)
        return func
    return decorator


# === compiler.py ===
class PipelineCompiler:
    def __init__(self):
        self.polaris = PolarisClient()
        self.openmetadata = OpenMetadataClient()
        self.dag_gen = AirflowDagGenerator()
        self.stream_gen = RisingWaveGenerator()

    async def compile(self, module_path: str) -> CompilationResult:
        """Main compilation entry point."""
        registry = self.load_module(module_path)
        graph = DependencyGraph.from_registry(registry)
        graph.validate()  # Raises on cycles or missing refs

        # Separate batch vs streaming
        batch_tables = [t for t in graph.tables if t.mode != "streaming"]
        stream_tables = [t for t in graph.tables if t.mode == "streaming"]

        artifacts = []
        if batch_tables:
            dag_code = self.dag_gen.generate(registry.pipeline, batch_tables, graph)
            artifacts.append(("airflow_dag", dag_code))

        if stream_tables:
            ddl = self.stream_gen.generate(stream_tables, registry.sources)
            artifacts.append(("risingwave_ddl", ddl))

        # Register in Polaris and OpenMetadata
        await self.polaris.ensure_tables(graph.all_tables)
        await self.openmetadata.register_lineage(graph)

        return CompilationResult(artifacts=artifacts, graph=graph)


# === dependency_graph.py ===
class DependencyGraph:
    """Directed acyclic graph of table dependencies."""

    def __init__(self):
        self.nodes: Dict[str, TableNode] = {}
        self.edges: List[Tuple[str, str]] = []

    @classmethod
    def from_registry(cls, registry: LiveTableRegistry) -> "DependencyGraph":
        """Build graph by parsing {{ ref() }} and {{ source() }} calls."""
        graph = cls()
        for table in registry.tables.values():
            graph.add_node(table)
            refs = TemplateEngine.extract_refs(table.transform_fn)
            for ref in refs:
                graph.add_edge(ref, table.name)
        return graph

    def validate(self):
        """Check for cycles, missing references."""
        if self.has_cycle():
            raise PipelineValidationError("Cyclic dependency detected")
        for edge in self.edges:
            if edge[0] not in self.nodes:
                raise PipelineValidationError(f"Missing reference: {edge[0]}")

    def topological_sort(self) -> List[str]:
        """Return execution order."""
        ...


# === quality.py ===
class QualityEngine:
    """Evaluates data quality constraints."""

    @staticmethod
    def expect(name: str, condition: str):
        """Log violations but continue."""
        return QualityCheck(name=name, condition=condition, action="log")

    @staticmethod
    def expect_or_drop(name: str, condition: str):
        """Filter rows that violate condition."""
        return QualityCheck(name=name, condition=condition, action="drop")

    @staticmethod
    def expect_or_fail(name: str, condition: str):
        """Fail pipeline if condition violated."""
        return QualityCheck(name=name, condition=condition, action="fail")

    def generate_check_sql(self, check: QualityCheck, table_fqn: str) -> str:
        """Generate SQL to evaluate a quality check."""
        return f"""
            SELECT
                '{check.name}' AS check_name,
                COUNT(*) AS total_rows,
                SUM(CASE WHEN NOT ({check.condition}) THEN 1 ELSE 0 END) AS failed_rows,
                CAST(SUM(CASE WHEN NOT ({check.condition}) THEN 1 ELSE 0 END) AS DOUBLE)
                    / NULLIF(COUNT(*), 0) AS failure_rate
            FROM {table_fqn}
        """
```

### 7.3 REST API Endpoints

```python
# === app/api/pipelines.py ===

@router.post("/pipelines/compile")
async def compile_pipeline(request: PipelineCompileRequest):
    """Compile a pipeline definition and return artifacts."""
    ...

@router.post("/pipelines/deploy")
async def deploy_pipeline(request: PipelineDeployRequest):
    """Deploy a compiled pipeline (create DAG or streaming job)."""
    ...

@router.get("/pipelines")
async def list_pipelines():
    """List all deployed pipelines."""
    ...

@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str):
    """Get pipeline details including lineage graph."""
    ...

@router.get("/pipelines/{pipeline_id}/runs")
async def get_pipeline_runs(pipeline_id: str):
    """Get execution history for a pipeline."""
    ...

@router.post("/pipelines/{pipeline_id}/trigger")
async def trigger_pipeline(pipeline_id: str):
    """Manually trigger a pipeline run."""
    ...

@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(pipeline_id: str):
    """Delete a pipeline and its generated DAG."""
    ...

@router.get("/pipelines/{pipeline_id}/quality")
async def get_pipeline_quality(pipeline_id: str):
    """Get latest quality check results."""
    ...

@router.get("/pipelines/{pipeline_id}/lineage")
async def get_pipeline_lineage(pipeline_id: str):
    """Get lineage graph for a pipeline."""
    ...
```

### 7.4 CLI Tool

```bash
# Validate pipeline without deploying
datapond pipeline validate pipelines/ecommerce_analytics.py

# Deploy pipeline (compile + register + activate)
datapond pipeline deploy pipelines/ecommerce_analytics.py

# Deploy streaming pipeline
datapond pipeline deploy pipelines/stream_clicks.py --streaming

# List deployed pipelines
datapond pipeline list

# Get pipeline status
datapond pipeline status ecommerce_analytics

# Trigger manual run
datapond pipeline run ecommerce_analytics

# View lineage
datapond pipeline lineage ecommerce_analytics

# Delete pipeline
datapond pipeline delete ecommerce_analytics

# Local testing (uses DuckDB instead of Trino)
datapond pipeline test pipelines/ecommerce_analytics.py --engine duckdb
```

### 7.5 Testing Strategy

| Layer | Approach | Tools |
|-------|----------|-------|
| Decorators | Unit tests | pytest, mock |
| Compiler | Unit tests | pytest (parse -> graph -> validate) |
| DAG Generator | Snapshot tests | pytest (compare generated code to golden files) |
| Quality Engine | Unit tests | pytest (SQL generation correctness) |
| Integration | Integration tests | pytest + Docker (Trino, RisingWave, Polaris) |
| End-to-end | E2E tests | pytest + K8s (full pipeline deploy + execute) |

**Local testing with DuckDB:**
```python
# tests/test_integration.py
def test_pipeline_with_duckdb():
    """Run pipeline locally using DuckDB instead of Trino."""
    compiler = PipelineCompiler(engine_override="duckdb")
    result = compiler.compile("pipelines/ecommerce_analytics.py")

    # Execute transforms locally
    executor = DuckDBExecutor()
    executor.load_test_data("raw_orders", test_orders_df)
    executor.execute_pipeline(result)

    # Verify output
    output = executor.read_table("daily_revenue")
    assert len(output) > 0
    assert all(output["total_revenue"] >= 0)
```

---

## 8. Example End-to-End Use Case

### Scenario: E-commerce Analytics Pipeline

**Requirements:**
1. Ingest orders from PostgreSQL (OLTP) every hour
2. Clean and validate (drop invalid statuses, ensure non-null IDs)
3. Compute daily revenue (gold table)
4. Track full lineage (source -> bronze -> silver -> gold)
5. Alert on quality failures

### Complete Pipeline Definition

```python
# pipelines/ecommerce_analytics.py
"""
DataPond Live Tables: E-commerce Analytics Pipeline
Refreshes hourly. Processes orders from OLTP into analytics-ready gold tables.
"""
from datapond.pipelines import pipeline, source, live_table, quality

# === Pipeline Metadata ===
@pipeline(
    name="ecommerce_analytics",
    schedule="0 * * * *",  # Every hour
    tags=["ecommerce", "analytics", "production"],
    owner="analytics-team@datapond.io",
    max_retries=2,
    alert_on_failure=True,
    alert_channel="slack:#data-alerts"
)

# === Layer 1: Bronze (Raw Ingestion) ===
@source(
    name="raw_orders",
    connection="postgres_oltp",
    table="public.orders",
    mode="incremental",
    watermark_column="updated_at",
    catalog="datapond",
    namespace="bronze"
)

@source(
    name="raw_customers",
    connection="postgres_oltp",
    table="public.customers",
    mode="incremental",
    watermark_column="modified_at",
    catalog="datapond",
    namespace="bronze"
)

# === Layer 2: Silver (Cleaned & Validated) ===
@live_table(
    name="clean_orders",
    comment="Validated orders with proper types and business rules applied",
    catalog="datapond",
    namespace="silver",
    mode="incremental",
    partition_by=["order_date"]
)
@quality.expect("valid_amount", "amount > 0 AND amount < 1000000")
@quality.expect_or_drop("valid_status", "status IN ('pending','processing','shipped','delivered','cancelled','refunded')")
@quality.expect_or_fail("non_null_pk", "order_id IS NOT NULL AND customer_id IS NOT NULL")
@quality.expect("recent_date", "order_date >= DATE '2020-01-01'")
def clean_orders():
    return """
        SELECT
            order_id,
            customer_id,
            CAST(amount AS DECIMAL(12,2)) AS amount,
            LOWER(TRIM(status)) AS status,
            CAST(created_at AS DATE) AS order_date,
            created_at,
            updated_at
        FROM {{ source('raw_orders') }}
        WHERE {{ incremental_filter('updated_at') }}
    """


@live_table(
    name="clean_customers",
    comment="Deduplicated and validated customer records",
    catalog="datapond",
    namespace="silver",
    mode="incremental"
)
@quality.expect_or_fail("non_null_pk", "customer_id IS NOT NULL")
@quality.expect("valid_email", "email LIKE '%@%.%'")
def clean_customers():
    return """
        SELECT
            customer_id,
            TRIM(name) AS name,
            LOWER(TRIM(email)) AS email,
            country,
            created_at,
            modified_at
        FROM {{ source('raw_customers') }}
        WHERE {{ incremental_filter('modified_at') }}
    """


# === Layer 3: Gold (Business-Ready Aggregates) ===
@live_table(
    name="daily_revenue",
    comment="Daily revenue KPIs by status",
    catalog="datapond",
    namespace="gold",
    mode="incremental",
    partition_by=["order_date"]
)
@quality.expect("positive_revenue", "total_revenue >= 0")
@quality.expect("reasonable_aov", "avg_order_value BETWEEN 1 AND 100000")
def daily_revenue():
    return """
        SELECT
            order_date,
            status,
            COUNT(*) AS order_count,
            SUM(amount) AS total_revenue,
            AVG(amount) AS avg_order_value,
            MIN(amount) AS min_order,
            MAX(amount) AS max_order
        FROM {{ ref('clean_orders') }}
        GROUP BY order_date, status
    """


@live_table(
    name="customer_lifetime_value",
    comment="Customer LTV calculation",
    catalog="datapond",
    namespace="gold",
    mode="full_refresh"  # Recomputes fully each run
)
@quality.expect("positive_ltv", "lifetime_value >= 0")
def customer_lifetime_value():
    return """
        SELECT
            c.customer_id,
            c.name,
            c.email,
            c.country,
            COUNT(o.order_id) AS total_orders,
            SUM(o.amount) AS lifetime_value,
            MIN(o.order_date) AS first_order_date,
            MAX(o.order_date) AS last_order_date,
            DATE_DIFF('day', MIN(o.order_date), MAX(o.order_date)) AS customer_tenure_days
        FROM {{ ref('clean_customers') }} c
        LEFT JOIN {{ ref('clean_orders') }} o ON c.customer_id = o.customer_id
        WHERE o.status IN ('shipped', 'delivered')
        GROUP BY c.customer_id, c.name, c.email, c.country
    """
```

### What Happens on `datapond pipeline deploy`

```
$ datapond pipeline deploy pipelines/ecommerce_analytics.py

[1/6] Parsing pipeline definition...
  Found: 2 sources, 4 tables, 1 pipeline
  Pipeline: ecommerce_analytics (schedule: @hourly)

[2/6] Resolving dependencies...
  raw_orders ──► clean_orders ──┬──► daily_revenue
                                └──► customer_lifetime_value
  raw_customers ──► clean_customers ──┘

[3/6] Validating quality constraints...
  clean_orders: 4 checks (1 fail, 1 drop, 2 log)
  clean_customers: 2 checks (1 fail, 1 log)
  daily_revenue: 2 checks (2 log)
  customer_lifetime_value: 1 check (1 log)
  All checks valid.

[4/6] Registering tables in Polaris catalog...
  Created namespace: datapond.bronze
  Created namespace: datapond.silver
  Created namespace: datapond.gold
  Registered: datapond.bronze.raw_orders
  Registered: datapond.bronze.raw_customers
  Registered: datapond.silver.clean_orders
  Registered: datapond.silver.clean_customers
  Registered: datapond.gold.daily_revenue
  Registered: datapond.gold.customer_lifetime_value

[5/6] Generating Airflow DAG...
  Output: /opt/airflow/dags/datapond_pipelines/ecommerce_analytics.py
  DAG ID: datapond__ecommerce_analytics

[6/6] Registering lineage in OpenMetadata...
  Pipeline: datapond.pipeline.ecommerce_analytics
  Lineage edges: 6 registered
  Quality tests: 9 registered

Pipeline deployed successfully!
  DAG: datapond__ecommerce_analytics
  Schedule: Every hour
  Next run: 2026-04-30 11:00:00 UTC
  Dashboard: http://datapond.local/pipelines/ecommerce_analytics
```

---

## 9. Incremental Processing Design

### 9.1 Checkpoint State

```sql
-- Stored in PostgreSQL (datapond database)
CREATE TABLE pipeline_checkpoints (
    pipeline_name VARCHAR(255) NOT NULL,
    table_name VARCHAR(255) NOT NULL,
    watermark_column VARCHAR(255) NOT NULL,
    last_watermark_value TIMESTAMP NOT NULL,
    last_run_id VARCHAR(255),
    rows_processed BIGINT DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (pipeline_name, table_name)
);
```

### 9.2 Incremental Filter Resolution

When `{{ incremental_filter('updated_at') }}` is used:

```sql
-- First run (no checkpoint): processes all data
WHERE 1=1

-- Subsequent runs: filters to new data only
WHERE updated_at > '2026-04-30T09:00:00Z'  -- last checkpoint value
```

### 9.3 Merge Strategy for Incremental Tables

```sql
-- For tables with mode="incremental", use MERGE (Iceberg supports it)
MERGE INTO datapond.silver.clean_orders AS target
USING (
    SELECT ... FROM datapond.bronze.raw_orders
    WHERE updated_at > '2026-04-30T09:00:00Z'
) AS source
ON target.order_id = source.order_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
```

---

## 10. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| SQL injection in quality checks | Parameterized queries, AST validation at compile time |
| Arbitrary code execution in Python transforms | Sandboxed execution environment, resource limits |
| Credential exposure in source definitions | Connection IDs reference Airflow Connections (secrets in K8s) |
| Unauthorized pipeline deployment | RBAC via Polaris catalog privileges |
| Data leakage across namespaces | Namespace-level isolation in Polaris |

---

## 11. Implementation Roadmap

### Phase 1: Core Framework (Day 1 - Priority)

| Task | Effort | Owner |
|------|--------|-------|
| `decorators.py` - @live_table, @source, @quality | 2h | Backend Agent |
| `models.py` - Pydantic models | 1h | Backend Agent |
| `dependency_graph.py` - DAG resolution | 2h | Backend Agent |
| `template_engine.py` - {{ ref() }} / {{ source() }} | 1h | Backend Agent |
| `compiler.py` - Main orchestrator | 2h | Backend Agent |
| `dag_generator.py` - Airflow DAG output | 3h | Backend Agent |
| `quality.py` - Constraint engine | 1.5h | Backend Agent |
| **Total Phase 1** | **12.5h** | |

### Phase 2: Integrations (Day 2)

| Task | Effort | Owner |
|------|--------|-------|
| `polaris_client.py` - Catalog registration | 2h | Backend Agent |
| `openmetadata_client.py` - Lineage registration | 2h | Backend Agent |
| `api/pipelines.py` - REST endpoints | 3h | Backend Agent |
| Custom Airflow operators (4 operators) | 4h | Backend Agent |
| `pipeline_cli.py` - CLI tool | 2h | Backend Agent |
| **Total Phase 2** | **13h** | |

### Phase 3: Streaming & Polish (Day 3)

| Task | Effort | Owner |
|------|--------|-------|
| `streaming_generator.py` - RisingWave DDL | 3h | Backend Agent |
| `risingwave_client.py` - DDL executor | 2h | Backend Agent |
| `incremental.py` - Checkpoint management | 2h | Backend Agent |
| Unit tests (all modules) | 4h | Backend Agent |
| Integration tests | 3h | Backend Agent |
| Frontend: Pipeline management UI | 6h | Frontend Agent |
| **Total Phase 3** | **20h** | |

### Phase 4: Production Hardening (Sprint 3)

- Pipeline versioning and rollback
- Spark engine support (when activated)
- Advanced quality metrics dashboard
- Pipeline templates gallery
- Multi-tenant isolation

---

## 12. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Pipeline authoring time | <30 min for standard ETL | User testing |
| Lines of code reduction | 70% fewer vs manual Airflow DAG | Code comparison |
| Quality check coverage | 100% of tables have at least 1 check | Automated scan |
| Lineage completeness | 100% of pipeline tables tracked | OpenMetadata audit |
| Deployment time | <60 seconds compile + deploy | CLI timing |
| DLT feature parity | 80%+ of core DLT features | Feature checklist |

---

## 13. Appendix: Comparison with Delta Live Tables

| Feature | Delta Live Tables | DataPond Live Tables | Notes |
|---------|-------------------|---------------------|-------|
| Declarative syntax | @dlt.table | @live_table | Equivalent |
| Data quality: expect | @dlt.expect | @quality.expect | Equivalent |
| Data quality: drop | @dlt.expect_or_drop | @quality.expect_or_drop | Equivalent |
| Data quality: fail | @dlt.expect_or_fail | @quality.expect_or_fail | Equivalent |
| Auto dependency | Implicit (Spark lineage) | Explicit ({{ ref() }}) | More explicit, dbt-like |
| Incremental | Auto-loader | watermark + checkpoint | Comparable |
| Streaming | Spark Structured Streaming | RisingWave MV | Different engine, same UX |
| Catalog integration | Unity Catalog | Apache Polaris | Equivalent architecture |
| Lineage tracking | Unity Catalog | OpenMetadata | Richer (column-level) |
| Execution engine | Spark | Trino/Spark/DuckDB | Multi-engine advantage |
| Python transforms | Spark DataFrame | pandas + DuckDB | Lower resource usage |
| Local testing | dbx (Databricks CLI) | datapond pipeline test | Equivalent |
| Scheduling | Databricks Jobs | Airflow | More flexible (cron, sensors) |
| Multi-cloud | Databricks only | Any K8s cluster | Sovereign infrastructure |

---

## 14. Open Questions (For PM Decision)

1. **Naming**: "DataPond Live Tables" vs "DataPond Pipelines" vs "DataPond Flow"?
2. **UI Priority**: Should Phase 1 include a basic pipeline editor UI, or CLI-only first?
3. **Spark activation**: Should we activate Spark now for large-scale transforms, or keep Trino-only in v1?
4. **Pipeline storage**: Store pipeline definitions in PostgreSQL (versioned), or Git-only?
5. **Multi-tenant**: Should pipelines respect namespace-level RBAC from day 1, or add later?

---

*End of ADR. This document should be reviewed by PM Agent before Backend Agent begins implementation.*
