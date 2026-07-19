# DataPond Declarative Pipeline Framework

> **Optional add-on:** this framework compiles to Airflow and is available only when
> the `pipelines` capability is enabled. Portable Core and Knowledge freshness do not
> depend on Airflow; the backend RAG scheduler handles collection re-embedding.

Delta Live Tables (DLT) equivalent for DataPond. Define data pipelines declaratively using Python decorators.

## Features

- **Declarative DSL**: Python decorators for pipeline definition (`@pipeline`, `@source`, `@live_table`)
- **Automatic Dependencies**: Resolves table dependencies from SQL templates
- **Data Quality**: Built-in quality checks (`@quality.expect`, `@quality.expect_or_drop`, `@quality.expect_or_fail`)
- **Incremental Processing**: Automatic watermark-based incremental loading
- **DAG Generation**: Compiles to Airflow DAG Python code
- **Validation**: Pre-deployment validation with circular dependency detection

## Quick Start

### 1. Define a Pipeline

```python
from datapond.pipelines import pipeline, source, live_table, quality

@pipeline(
    name="sales_analytics",
    schedule="@hourly",
    tags=["sales", "analytics"],
    owner="data-team@company.com"
)

@source(
    name="raw_orders",
    connection="postgres_oltp",
    table="public.orders",
    mode="incremental",
    watermark_column="updated_at"
)
def raw_orders_source():
    """Raw orders from OLTP database"""
    pass

@live_table(
    name="clean_orders",
    mode="incremental",
    partition_by=["order_date"]
)
@quality.expect_or_fail("non_null_id", "order_id IS NOT NULL")
@quality.expect("valid_amount", "amount > 0")
def clean_orders():
    """Cleaned and validated orders"""
    return """
        SELECT
            order_id,
            customer_id,
            amount,
            order_date
        FROM {{ source('raw_orders') }}
        WHERE {{ incremental_filter('updated_at') }}
    """

@live_table(
    name="daily_revenue",
    mode="incremental"
)
def daily_revenue():
    """Daily revenue aggregation"""
    return """
        SELECT
            order_date,
            SUM(amount) AS total_revenue
        FROM {{ ref('clean_orders') }}
        GROUP BY order_date
    """
```

### 2. Validate Pipeline

```bash
python -m app.pipelines.cli validate examples/pipelines/example_sales.py
```

Output:
```
✓ Pipeline validation successful!

Pipeline: example_sales_analytics

Pipeline Dependency Graph
==================================================

Batch 1 (parallel execution):
  - clean_sales (depends on: raw_sales)
  - clean_customers (depends on: raw_customers)

Batch 2 (parallel execution):
  - daily_sales_summary (depends on: clean_sales)
  - customer_lifetime_value (depends on: clean_customers, clean_sales)

Edges (dependencies):
  raw_sales → clean_sales
  raw_customers → clean_customers
  clean_sales → daily_sales_summary
  clean_customers → customer_lifetime_value
  clean_sales → customer_lifetime_value
```

### 3. Compile to Airflow DAG

```bash
python -m app.pipelines.cli compile examples/pipelines/example_sales.py -o /opt/airflow/dags/sales.py
```

Output:
```
✓ Pipeline compiled successfully!

Pipeline: example_sales_analytics

Generated artifacts (1):
  - airflow_dag: 4523 bytes

✓ Saved to: /opt/airflow/dags/sales.py
```

### 4. Use REST API

```python
import requests

# Validate pipeline
response = requests.post(
    "http://localhost:8000/api/pipelines/validate",
    json={
        "code": open("pipeline.py").read(),
        "filename": "pipeline.py"
    }
)
result = response.json()

if result["success"]:
    print("✓ Validation successful")
    print(f"Execution batches: {result['execution_batches']}")
else:
    print("✗ Validation failed")
    for error in result["errors"]:
        print(f"  - {error}")
```

## Core Concepts

### Pipeline Layers

- **Bronze**: Raw ingested data (`namespace="bronze"`)
- **Silver**: Cleaned and validated data (`namespace="silver"`)
- **Gold**: Business-ready aggregates (`namespace="gold"`)

### Processing Modes

- **`full_refresh`**: Recompute entire table each run (default)
- **`incremental`**: Process only new/changed data (requires `watermark_column`)
- **`streaming`**: Real-time processing with RisingWave (Phase 2)

### Quality Checks

- **`@quality.expect`**: Log violations, continue execution
- **`@quality.expect_or_drop`**: Filter out bad rows
- **`@quality.expect_or_fail`**: Fail pipeline on violation

### Template Functions

- **`{{ source('name') }}`**: Reference a `@source` table
- **`{{ ref('name') }}`**: Reference another `@live_table`
- **`{{ incremental_filter('column') }}`**: Auto-inject WHERE for incremental
- **`{{ current_timestamp() }}`**: Pipeline execution timestamp

## Architecture

```
Pipeline Definition (.py)
         │
         ▼
    Decorators
    (@pipeline, @source, @live_table)
         │
         ▼
    Compiler
    - Parse decorators
    - Build dependency graph
    - Validate (cycles, refs)
         │
         ▼
    DAG Generator
    - Generate Airflow DAG code
    - Add quality checks
    - Add incremental logic
         │
         ▼
    Airflow DAG (.py)
    - Source ingestion tasks
    - Transform tasks
    - Quality check tasks
    - Checkpoint tasks
```

## API Reference

### Decorators

#### `@pipeline()`
```python
@pipeline(
    name: str,                      # Pipeline name (unique)
    schedule: str = "@daily",       # Cron or Airflow preset
    tags: List[str] = [],           # Tags for organization
    owner: str = "...",             # Owner email
    max_retries: int = 2,           # Max retries on failure
    alert_on_failure: bool = True   # Send alerts
)
```

#### `@source()`
```python
@source(
    name: str,                      # Source name
    connection: str,                # Airflow connection ID
    table: str,                     # Source table name
    mode: str = "full_refresh",     # Processing mode
    watermark_column: str = None,   # Column for incremental
    catalog: str = "datapond",      # Target catalog
    namespace: str = "bronze"       # Target namespace
)
```

#### `@live_table()`
```python
@live_table(
    name: str,                      # Table name
    comment: str = "",              # Description
    catalog: str = "datapond",      # Iceberg catalog
    namespace: str = "silver",      # Namespace (bronze/silver/gold)
    mode: str = "full_refresh",     # Processing mode
    partition_by: List[str] = [],   # Partition columns
    engine: str = "trino",          # Execution engine
    watermark_column: str = None    # Column for incremental
)
```

#### `@quality.expect()`
```python
@quality.expect(
    name: str,        # Check name
    condition: str    # SQL WHERE condition
)
# Log violations, continue execution
```

#### `@quality.expect_or_drop()`
```python
@quality.expect_or_drop(
    name: str,        # Check name
    condition: str    # SQL WHERE condition
)
# Filter out bad rows
```

#### `@quality.expect_or_fail()`
```python
@quality.expect_or_fail(
    name: str,        # Check name
    condition: str    # SQL WHERE condition
)
# Fail pipeline on violation
```

### CLI Commands

```bash
# Validate pipeline
python -m app.pipelines.cli validate <file>

# Compile to DAG
python -m app.pipelines.cli compile <file> [-o output.py]

# List deployed pipelines (Phase 2)
python -m app.pipelines.cli list

# Get pipeline status (Phase 2)
python -m app.pipelines.cli status <name>
```

### REST API Endpoints

- `POST /api/pipelines/validate` - Validate pipeline definition
- `POST /api/pipelines/compile` - Compile to Airflow DAG
- `POST /api/pipelines/deploy` - Deploy to Airflow (Phase 2)
- `GET /api/pipelines` - List pipelines (Phase 2)
- `GET /api/pipelines/{name}` - Get pipeline details (Phase 2)
- `POST /api/pipelines/{name}/trigger` - Trigger run (Phase 2)
- `DELETE /api/pipelines/{name}` - Delete pipeline (Phase 2)

## Testing

```bash
# Run unit tests
pytest backend/tests/test_pipelines/

# Test specific module
pytest backend/tests/test_pipelines/test_decorators.py

# Test with coverage
pytest backend/tests/test_pipelines/ --cov=app.pipelines
```

## Phase 1 Status (Current)

**Implemented:**
- ✅ Decorator framework (`@pipeline`, `@source`, `@live_table`, `@quality`)
- ✅ Pydantic models (Pipeline, Table, Source, QualityCheck)
- ✅ Template engine (`{{ ref() }}`, `{{ source() }}`, `{{ incremental_filter() }}`)
- ✅ Dependency graph builder (topological sort, cycle detection)
- ✅ Airflow DAG generator (generates Python code)
- ✅ Pipeline compiler (orchestrates validation + generation)
- ✅ CLI tool (validate, compile commands)
- ✅ REST API endpoints (validate, compile)
- ✅ Unit tests (decorators, compiler)
- ✅ Example pipeline (sales analytics)

**Limitations:**
- Generated DAG uses `EmptyOperator` placeholders (custom operators not implemented)
- No actual deployment to Airflow (file copy + API trigger)
- No OpenMetadata lineage registration
- No incremental checkpoint state management
- No RisingWave streaming support

## Phase 2 Roadmap (Next)

**Integrations:**
- [ ] Polaris client for catalog registration
- [ ] OpenMetadata client for lineage tracking
- [ ] Custom Airflow operators (`TrinoOperator`, `QualityCheckOperator`, etc.)
- [ ] Deployment logic (copy DAG file, trigger refresh)
- [ ] Incremental checkpoint state (PostgreSQL table)

**Streaming:**
- [ ] RisingWave DDL generator
- [ ] Streaming source support (`@streaming_source`)
- [ ] Materialized view creation

**UI:**
- [ ] Pipeline editor with syntax highlighting
- [ ] Visual DAG builder
- [ ] Lineage graph visualization
- [ ] Quality check dashboard

## Troubleshooting

### Import Errors

If you see `ModuleNotFoundError: No module named 'app.pipelines'`:

```python
# Add to top of pipeline file
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
```

### Circular Dependency Detected

Check your `{{ ref() }}` calls. Tables cannot reference each other in a cycle:

```
Bad:  table_a → table_b → table_a
Good: table_a → table_b → table_c
```

### Quality Check SQL Injection Warning

Quality checks are validated to prevent SQL injection. Dangerous keywords are blocked:

```python
# ✗ Blocked
@quality.expect("bad", "1=1; DROP TABLE users")

# ✓ Allowed
@quality.expect("valid", "amount > 0")
```

## Examples

See `backend/examples/pipelines/` for complete examples:
- `example_sales.py` - Multi-layer sales analytics pipeline

## Contributing

When adding new features:
1. Add Pydantic model in `models.py`
2. Update decorator in `decorators.py`
3. Add compilation logic in `compiler.py`
4. Update DAG generator in `dag_generator.py`
5. Add unit tests in `tests/test_pipelines/`
6. Update this README

## License

Internal DataPond framework - see main project LICENSE.
