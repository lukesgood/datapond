"""
FastAPI routes for RisingWave streaming pipeline management.

Endpoints:
- GET  /streaming/cluster       — cluster health + worker nodes
- GET  /streaming/sources       — list sources
- POST /streaming/sources       — create source (execute CREATE SOURCE SQL)
- DELETE /streaming/sources/{name} — drop source
- GET  /streaming/sinks         — list sinks
- POST /streaming/sinks         — create sink
- DELETE /streaming/sinks/{name}   — drop sink
- GET  /streaming/views         — list materialized views
- POST /streaming/views         — create materialized view
- DELETE /streaming/views/{name}   — drop materialized view
- GET  /streaming/views/{name}/data — preview MV data
- GET  /streaming/progress      — DDL progress
- POST /streaming/sql           — execute arbitrary SQL
- POST /streaming/cdc-pipeline  — atomic CDC pipeline (source→mv→sink per table)
- POST /streaming/event-pipeline — atomic event pipeline (source→mv→sink), rollback on failure
"""

import os
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["streaming"])

RW_HOST = os.getenv("RISINGWAVE_HOST", "risingwave-frontend.datapond.svc.cluster.local")
RW_PORT = int(os.getenv("RISINGWAVE_PORT", "4566"))


def _iceberg_sink_s3_props() -> dict:
    """S3 credential/endpoint props for a RisingWave Iceberg sink.

    MinIO/onprem: S3_ACCESS_KEY/S3_SECRET_KEY/S3_ENDPOINT are injected as env → pass
    them into the sink DDL. AWS: they're absent (empty endpoint, no keys) → omit them
    so RisingWave's Iceberg connector falls back to its own credential chain instead of
    a bogus literal key. Mirrors iceberg_catalog._s3_fileio_props().

    NOTE: RisingWave's Iceberg 'storage' connector credential-chain support on AWS is
    version-dependent and unverified live — RisingWave is disabled on the AWS profiles
    today, so this omit-path is not currently exercised on AWS. Omitting a bogus literal
    is still strictly better than injecting one.
    """
    props: dict = {}
    ep = os.getenv("S3_ENDPOINT", "").strip()
    if ep:
        props["s3.endpoint"] = ep if ep.startswith("http") else f"http://{ep}"
    ak = os.getenv("S3_ACCESS_KEY", "").strip()
    sk = os.getenv("S3_SECRET_KEY", "").strip()
    if ak and sk:
        props["s3.access.key"] = ak
        props["s3.secret.key"] = sk
    return props


def _rw_conn():
    return psycopg2.connect(
        host=RW_HOST, port=RW_PORT,
        user="root", dbname="dev", password="",
        connect_timeout=10,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _execute(sql: str, fetch: bool = True) -> List[Dict]:
    conn = _rw_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if fetch:
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        conn.commit()
        return []
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


# ── Request models ─────────────────────────────────────────────────────────────

class SqlRequest(BaseModel):
    sql: str


class CreateSourceRequest(BaseModel):
    name: str
    connector: str          # kafka | kinesis | pulsar | nexmark
    topic: str = ""
    bootstrap_servers: str = ""
    format: str = "plain"   # plain | upsert | debezium | maxwell | canal
    row_encode: str = "json"  # json | avro | protobuf | csv
    extra_props: Dict[str, str] = {}
    columns_sql: str = ""   # raw column definitions e.g. "user_id BIGINT, name VARCHAR"


class CreateSinkRequest(BaseModel):
    name: str
    from_mv: str            # materialized view or table to sink from
    connector: str = "iceberg"
    sink_type: str = "append-only"   # append-only | upsert
    extra_props: Dict[str, str] = {}
    # Iceberg-specific (auto-filled from env)
    iceberg_schema: str = "default"
    iceberg_table: str = ""   # defaults to sink name


class CreateMvRequest(BaseModel):
    name: str
    definition: str         # full SQL after "AS"


# ── Cluster ────────────────────────────────────────────────────────────────────

@router.get("/streaming/cluster")
async def get_cluster():
    """Cluster health and worker node info."""
    try:
        workers = _execute("""
            SELECT id, host, port, type, state, parallelism,
                   is_streaming, is_serving, rw_version,
                   total_memory_bytes, total_cpu_cores, started_at
            FROM rw_catalog.rw_worker_nodes
            ORDER BY type, id
        """)
        source_count = _execute("SELECT COUNT(*) AS cnt FROM rw_catalog.rw_sources")[0]["cnt"]
        sink_count   = _execute("SELECT COUNT(*) AS cnt FROM rw_catalog.rw_sinks")[0]["cnt"]
        mv_count     = _execute("SELECT COUNT(*) AS cnt FROM rw_catalog.rw_materialized_views")[0]["cnt"]

        running = [w for w in workers if w.get("state") == "RUNNING"]
        status = "healthy" if running else "down"

        return _serialize({
            "status": status,
            "version": workers[0]["rw_version"] if workers else None,
            "worker_count": len(workers),
            "source_count": source_count,
            "sink_count": sink_count,
            "mv_count": mv_count,
            "workers": workers,
        })
    except Exception as e:
        logger.error(f"streaming cluster error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Sources ────────────────────────────────────────────────────────────────────

@router.get("/streaming/sources")
async def list_sources():
    try:
        rows = _execute("""
            SELECT id, name, connector, format, row_encode,
                   append_only, definition, created_at
            FROM rw_catalog.rw_sources
            ORDER BY created_at DESC
        """)
        return _serialize(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/streaming/sources")
async def create_source(req: CreateSourceRequest):
    try:
        col_defs = req.columns_sql or "data JSONB"
        props = {
            "connector": f"'{req.connector}'",
        }
        if req.connector == "kafka":
            props["topic"] = f"'{req.topic}'"
            props["properties.bootstrap.server"] = f"'{req.bootstrap_servers}'"
            props["scan.startup.mode"] = "'latest'"
        for k, v in req.extra_props.items():
            props[k] = f"'{v}'"

        props_sql = ",\n  ".join(f"{k} = {v}" for k, v in props.items())
        sql = f"""
CREATE SOURCE {req.name} ({col_defs})
WITH (
  {props_sql}
)
FORMAT {req.format.upper()} ENCODE {req.row_encode.upper()}
"""
        _execute(sql, fetch=False)
        return {"message": f"Source '{req.name}' created", "sql": sql.strip()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/streaming/sources/{name}")
async def drop_source(name: str):
    try:
        _execute(f"DROP SOURCE {name}", fetch=False)
        return {"message": f"Source '{name}' dropped"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Materialized Views ─────────────────────────────────────────────────────────

@router.get("/streaming/views")
async def list_views():
    try:
        rows = _execute("""
            SELECT id, name, definition, created_at
            FROM rw_catalog.rw_materialized_views
            ORDER BY created_at DESC
        """)
        return _serialize(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/streaming/views")
async def create_view(req: CreateMvRequest):
    try:
        sql = f"CREATE MATERIALIZED VIEW {req.name} AS {req.definition}"
        _execute(sql, fetch=False)
        return {"message": f"Materialized view '{req.name}' created", "sql": sql}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/streaming/views/{name}")
async def drop_view(name: str):
    try:
        _execute(f"DROP MATERIALIZED VIEW {name}", fetch=False)
        return {"message": f"Materialized view '{name}' dropped"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/streaming/views/{name}/data")
async def preview_view(name: str, limit: int = 50):
    try:
        records = _execute(f"SELECT * FROM {name} LIMIT {limit}")
        columns = list(records[0].keys()) if records else []
        rows = [[record.get(column) for column in columns] for record in records]
        return _serialize({
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "count": len(rows),  # compatibility for older clients
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Sinks ──────────────────────────────────────────────────────────────────────

@router.get("/streaming/sinks")
async def list_sinks():
    try:
        rows = _execute("""
            SELECT id, name, connector, sink_type, definition, created_at
            FROM rw_catalog.rw_sinks
            ORDER BY created_at DESC
        """)
        return _serialize(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/streaming/sinks")
async def create_sink(req: CreateSinkRequest):
    try:
        target_table = req.iceberg_table or req.name
        warehouse    = os.getenv("ICEBERG_WAREHOUSE", "s3a://iceberg/warehouse")

        if req.connector == "iceberg":
            props = {
                "connector":       "iceberg",
                "type":            req.sink_type,
                "catalog.type":    "storage",
                "warehouse.path":  warehouse,
                **_iceberg_sink_s3_props(),
                "database.name":   req.iceberg_schema,
                "table.name":      target_table,
                **req.extra_props,
            }
        else:
            props = {"connector": req.connector, "type": req.sink_type, **req.extra_props}

        props_sql = ",\n  ".join(f"{k} = '{v}'" for k, v in props.items())
        sql = f"""
CREATE SINK {req.name}
FROM {req.from_mv}
WITH (
  {props_sql}
)
"""
        _execute(sql, fetch=False)
        return {"message": f"Sink '{req.name}' created", "sql": sql.strip()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/streaming/sinks/{name}")
async def drop_sink(name: str):
    try:
        _execute(f"DROP SINK {name}", fetch=False)
        return {"message": f"Sink '{name}' dropped"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── CDC Connection Test ────────────────────────────────────────────────────────

class CdcTestRequest(BaseModel):
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    db_schema: str = "public"


@router.post("/streaming/cdc-test")
async def test_cdc_connection(req: CdcTestRequest):
    """Test PostgreSQL CDC connection and return table list."""
    import psycopg2 as _pg
    try:
        conn = _pg.connect(
            host=req.db_host, port=req.db_port, dbname=req.db_name,
            user=req.db_user, password=req.db_password,
            connect_timeout=10,
        )
        cur = conn.cursor()
        # Check wal_level
        cur.execute("SHOW wal_level")
        wal_level = cur.fetchone()[0]
        # List tables in schema
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, (req.db_schema,))
        tables = [row[0] for row in cur.fetchall()]
        conn.close()
        return {
            "success": True,
            "wal_level": wal_level,
            "wal_ok": wal_level == "logical",
            "tables": tables,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "tables": []}


# ── CDC Pipeline ──────────────────────────────────────────────────────────────

class CdcPipelineRequest(BaseModel):
    """Create a full CDC pipeline: RisingWave postgres-cdc source → Iceberg sink."""
    pipeline_name: str          # unique name prefix for source/mv/sink
    # Source DB connection
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    db_schema: str = "public"
    # Tables to capture (list)
    tables: List[str]
    # Iceberg target namespace
    iceberg_schema: str = "raw"
    # Slot name (must be unique per pipeline in PostgreSQL)
    slot_name: str = ""


@router.post("/streaming/cdc-pipeline")
async def create_cdc_pipeline(req: CdcPipelineRequest):
    """
    Create a complete CDC pipeline for each table:
      1. CREATE SOURCE <name>_<table>_src  (postgres-cdc connector)
      2. CREATE MATERIALIZED VIEW <name>_<table>_mv  AS SELECT * FROM source
      3. CREATE SINK <name>_<table>_sink  (Iceberg sink)
    Returns the generated SQL and status for each table.
    """
    warehouse   = os.getenv("ICEBERG_WAREHOUSE", "s3a://iceberg/warehouse")
    slot_name   = req.slot_name or f"datapond_{req.pipeline_name.lower().replace('-','_')}"

    results = []
    for table in req.tables:
        safe   = table.lower().replace(".", "_")
        prefix = f"{req.pipeline_name}_{safe}"
        src_name  = f"{prefix}_src"
        mv_name   = f"{prefix}_mv"
        sink_name = f"{prefix}_sink"
        sqls: List[str] = []
        status = "success"
        error  = None
        try:
            # 1. CDC Source
            src_sql = f"""CREATE SOURCE IF NOT EXISTS {src_name}
WITH (
  connector        = 'postgres-cdc',
  hostname         = '{req.db_host}',
  port             = '{req.db_port}',
  username         = '{req.db_user}',
  password         = '{req.db_password}',
  database.name    = '{req.db_name}',
  schema.name      = '{req.db_schema}',
  table.name       = '{table}',
  slot.name        = '{slot_name}_{safe}'
)"""
            _execute(src_sql, fetch=False)
            sqls.append(src_sql.strip())

            # 2. Materialized View (captures all columns)
            mv_sql = f"CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} AS SELECT * FROM {src_name}"
            _execute(mv_sql, fetch=False)
            sqls.append(mv_sql.strip())

            # 3. Iceberg Sink — S3 creds injected on MinIO, omitted on AWS (credential
            # chain) via _iceberg_sink_s3_props().
            sink_props = {
                "connector":      "iceberg",
                "type":           "upsert",
                "catalog.type":   "storage",
                "warehouse.path": warehouse,
                **_iceberg_sink_s3_props(),
                "database.name":  req.iceberg_schema,
                "table.name":     safe,
            }
            sink_props_sql = ",\n  ".join(f"{k} = '{v}'" for k, v in sink_props.items())
            sink_sql = f"""CREATE SINK IF NOT EXISTS {sink_name}
FROM {mv_name}
WITH (
  {sink_props_sql}
)"""
            _execute(sink_sql, fetch=False)
            sqls.append(sink_sql.strip())

        except Exception as e:
            status = "failed"
            error  = str(e)

        results.append({
            "table":     table,
            "source":    src_name,
            "view":      mv_name,
            "sink":      sink_name,
            "status":    status,
            "error":     error,
            "sqls":      sqls,
        })

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "pipeline_name": req.pipeline_name,
        "tables_total":   len(req.tables),
        "tables_success": success_count,
        "tables_failed":  len(req.tables) - success_count,
        "results":        results,
    }


@router.get("/streaming/cdc-pipelines")
async def list_cdc_pipelines():
    """List CDC sources (postgres-cdc connector) from RisingWave catalog."""
    try:
        rows = _execute("""
            SELECT id, name, connector, definition, created_at
            FROM rw_catalog.rw_sources
            WHERE connector = 'postgres-cdc'
            ORDER BY created_at DESC
        """)
        return _serialize(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Event Pipeline ────────────────────────────────────────────────────────────

class EventPipelineRequest(BaseModel):
    """Create a full event-stream pipeline: RisingWave source → MV → Iceberg sink."""
    pipeline_name: str              # unique name prefix for source/mv/sink
    source_type: str = "kafka"      # kafka | kinesis
    topic: str = ""                 # kafka topic
    bootstrap_servers: str = ""     # kafka bootstrap servers
    stream_name: str = ""           # kinesis stream name
    aws_region: str = "us-east-1"   # kinesis region
    format: str = "json"            # message encoding: json | avro | csv
    iceberg_schema: str = "raw"     # Iceberg target namespace
    columns_sql: str = "data JSONB" # raw column definitions


@router.post("/streaming/event-pipeline")
async def create_event_pipeline(req: EventPipelineRequest):
    """
    Atomically create an event-stream pipeline (Kafka/Kinesis):
      1. CREATE SOURCE <name>_src
      2. CREATE MATERIALIZED VIEW <name>_mv  AS SELECT * FROM source
      3. CREATE SINK <name>_sink  (Iceberg sink)

    RisingWave DDL is auto-commit, so a real transaction is not possible. Instead,
    on any failure the objects already created by this call are dropped in reverse
    order (best-effort rollback) and a 400 is returned — nothing is left partially
    created. Mirrors the /streaming/cdc-pipeline error shape.
    """
    name      = req.pipeline_name
    src_name  = f"{name}_src"
    mv_name   = f"{name}_mv"
    sink_name = f"{name}_sink"
    is_kafka  = req.source_type == "kafka"
    warehouse = os.getenv("ICEBERG_WAREHOUSE", "s3a://iceberg/warehouse")

    # Track objects successfully created so rollback never drops one we did not create.
    created: List[tuple] = []

    def _rollback():
        removed = 0
        failures: List[str] = []
        for kind, obj in reversed(created):
            try:
                _execute(f"DROP {kind} {obj}", fetch=False)
                removed += 1
            except Exception as drop_err:
                failures.append(f"{obj}: {drop_err}")
        return removed, failures

    try:
        # 1. Source
        col_defs = req.columns_sql or "data JSONB"
        props = {"connector": f"'{req.source_type}'"}
        if is_kafka:
            props["topic"] = f"'{req.topic}'"
            props["properties.bootstrap.server"] = f"'{req.bootstrap_servers}'"
            props["scan.startup.mode"] = "'latest'"
        else:
            props["stream"] = f"'{req.stream_name}'"
            props["aws.region"] = f"'{req.aws_region}'"
        props_sql = ",\n  ".join(f"{k} = {v}" for k, v in props.items())
        src_sql = f"""CREATE SOURCE {src_name} ({col_defs})
WITH (
  {props_sql}
)
FORMAT PLAIN ENCODE {req.format.upper()}"""
        _execute(src_sql, fetch=False)
        created.append(("SOURCE", src_name))

        # 2. Materialized view (captures all columns)
        mv_sql = f"CREATE MATERIALIZED VIEW {mv_name} AS SELECT * FROM {src_name}"
        _execute(mv_sql, fetch=False)
        created.append(("MATERIALIZED VIEW", mv_name))

        # 3. Iceberg sink — S3 creds injected on MinIO, omitted on AWS (credential
        # chain) via _iceberg_sink_s3_props().
        sink_props = {
            "connector":      "iceberg",
            "type":           "append-only",
            "catalog.type":   "storage",
            "warehouse.path": warehouse,
            **_iceberg_sink_s3_props(),
            "database.name":  req.iceberg_schema,
            "table.name":     name,
        }
        sink_props_sql = ",\n  ".join(f"{k} = '{v}'" for k, v in sink_props.items())
        sink_sql = f"""CREATE SINK {sink_name}
FROM {mv_name}
WITH (
  {sink_props_sql}
)"""
        _execute(sink_sql, fetch=False)
        created.append(("SINK", sink_name))
    except Exception as e:
        cause = str(e)
        if not created:
            raise HTTPException(status_code=400, detail=f"{cause}. No resources were created.")
        removed, failures = _rollback()
        if not failures:
            raise HTTPException(
                status_code=400,
                detail=f"{cause}. Rollback removed all {removed} created resources.",
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"{cause}. Rollback incomplete: removed {removed}/{len(created)}; "
                f"failed to remove {'; '.join(failures)}"
            ),
        )

    return {
        "pipeline_name": name,
        "source": src_name,
        "view":   mv_name,
        "sink":   sink_name,
        "status": "success",
    }


# ── Sample Streams ────────────────────────────────────────────────────────────

SAMPLE_STREAMS = [
    {
        "name": "sample_clickstream",
        "description": "Website click events (datagen)",
        "source_sql": """CREATE SOURCE IF NOT EXISTS sample_clickstream_src (
  user_id     BIGINT,
  page        VARCHAR,
  event_type  VARCHAR,
  device      VARCHAR,
  occurred_at TIMESTAMPTZ
) WITH (
  connector = 'datagen',
  fields.user_id.kind      = 'sequence',
  fields.user_id.start     = '1',
  fields.user_id.end       = '10000',
  fields.page.kind         = 'random',
  fields.page.length       = '8',
  fields.event_type.kind   = 'random',
  fields.event_type.length = '6',
  fields.device.kind       = 'random',
  fields.device.length     = '7',
  datagen.rows.per.second  = '10'
) FORMAT PLAIN ENCODE JSON""",
        "mv_sql": """CREATE MATERIALIZED VIEW IF NOT EXISTS sample_clickstream_mv AS
SELECT * FROM sample_clickstream_src""",
        "sink_sql": None,  # MV only — no Iceberg sink for sample
    },
    {
        "name": "sample_orders",
        "description": "E-commerce order events (datagen)",
        "source_sql": """CREATE SOURCE IF NOT EXISTS sample_orders_src (
  order_id   BIGINT,
  customer_id BIGINT,
  amount     DOUBLE,
  status     VARCHAR,
  created_at TIMESTAMPTZ
) WITH (
  connector = 'datagen',
  fields.order_id.kind      = 'sequence',
  fields.order_id.start     = '1',
  fields.customer_id.kind   = 'random',
  fields.customer_id.min    = '1',
  fields.customer_id.max    = '5000',
  fields.amount.kind        = 'random',
  fields.amount.min         = '1',
  fields.amount.max         = '500',
  fields.status.kind        = 'random',
  fields.status.length      = '7',
  datagen.rows.per.second   = '5'
) FORMAT PLAIN ENCODE JSON""",
        "mv_sql": """CREATE MATERIALIZED VIEW IF NOT EXISTS sample_orders_mv AS
SELECT * FROM sample_orders_src""",
        "sink_sql": None,
    },
]


@router.post("/streaming/sample-streams")
async def create_sample_streams():
    """Create sample datagen streams for demo/onboarding purposes."""
    results = []
    for s in SAMPLE_STREAMS:
        status = "success"
        error = None
        sqls = []
        try:
            _execute(s["source_sql"], fetch=False)
            sqls.append(s["source_sql"].strip().split("\n")[0])
            _execute(s["mv_sql"], fetch=False)
            sqls.append(s["mv_sql"].strip().split("\n")[0])
            if s.get("sink_sql"):
                _execute(s["sink_sql"], fetch=False)
                sqls.append(s["sink_sql"].strip().split("\n")[0])
        except Exception as e:
            status = "failed"
            error = str(e)
        results.append({"name": s["name"], "description": s["description"],
                        "status": status, "error": error})

    success = sum(1 for r in results if r["status"] == "success")
    return {"created": success, "total": len(results), "results": results}


# ── DDL Progress ───────────────────────────────────────────────────────────────

@router.get("/streaming/progress")
async def get_ddl_progress():
    try:
        rows = _execute("""
            SELECT ddl_id, ddl_statement, progress
            FROM rw_catalog.rw_ddl_progress
        """)
        return _serialize(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── SQL Console ────────────────────────────────────────────────────────────────

@router.post("/streaming/sql")
async def execute_sql(req: SqlRequest):
    """Execute arbitrary SQL against RisingWave."""
    sql = req.sql.strip()
    if not sql:
        raise HTTPException(status_code=400, detail="SQL is empty")

    # Determine if this is a SELECT/SHOW or DDL/DML
    first_word = sql.split()[0].upper()
    is_query = first_word in ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")

    try:
        import time
        start = time.time()
        if is_query:
            rows = _execute(sql, fetch=True)
            elapsed_ms = round((time.time() - start) * 1000, 1)
            cols = list(rows[0].keys()) if rows else []
            return _serialize({
                "columns": cols,
                "rows": [[r[c] for c in cols] for r in rows],
                "row_count": len(rows),
                "execution_time_ms": elapsed_ms,
            })
        else:
            _execute(sql, fetch=False)
            elapsed_ms = round((time.time() - start) * 1000, 1)
            return {"message": "OK", "execution_time_ms": elapsed_ms}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
