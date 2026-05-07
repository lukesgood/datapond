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
        rows = _execute(f"SELECT * FROM {name} LIMIT {limit}")
        return _serialize({"rows": rows, "count": len(rows)})
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
        s3_endpoint  = os.getenv("S3_ENDPOINT", "seaweedfs-s3:8333")
        s3_key       = os.getenv("S3_ACCESS_KEY", "datapond")
        s3_secret    = os.getenv("S3_SECRET_KEY", "datapond_dev")
        warehouse    = os.getenv("ICEBERG_WAREHOUSE", "s3a://iceberg/warehouse")

        if req.connector == "iceberg":
            props = {
                "connector":       "iceberg",
                "type":            req.sink_type,
                "catalog.type":    "storage",
                "warehouse.path":  warehouse,
                "s3.endpoint":     f"http://{s3_endpoint}",
                "s3.access.key":   s3_key,
                "s3.secret.key":   s3_secret,
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
