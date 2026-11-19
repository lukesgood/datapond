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
import re
import uuid
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.api.auth import require_permission, require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["streaming"])

RW_HOST = os.getenv("RISINGWAVE_HOST", "risingwave-frontend.datapond.svc.cluster.local")
# K8s injects <SVC>_PORT=tcp://<ip>:<port> when a matching service exists; take the
# trailing port so int() can't choke on the scheme (same class as the POSTGRES_PORT /
# VALKEY_PORT fixes).
RW_PORT = int(os.getenv("RISINGWAVE_PORT", "4566").rsplit(":", 1)[-1] or "4566")


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


# ── Quoting ────────────────────────────────────────────────────────────────────
# Every name and value below ends up inside a RisingWave DDL statement. Names are held
# to plain identifiers and values are SQL string literals with quotes doubled: a
# password or table name with a quote used to end the literal and run as SQL.

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
_PROP_KEY = re.compile(r"[a-z][a-z0-9._-]{0,63}")
_SOURCE_CONNECTORS = {"kafka", "kinesis", "pulsar", "nexmark"}
_FORMATS = {"plain", "upsert", "debezium", "maxwell", "canal"}
_ENCODES = {"json", "avro", "protobuf", "csv"}


def _ident(v: str, what: str = "name") -> str:
    v = (v or "").strip()
    if not _IDENT.fullmatch(v):
        raise HTTPException(400, f"{what} must be a letter or underscore followed by letters, digits or underscores (max 63)")
    return v


def _lit(v: Any) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _props_sql(props: Dict[str, Any]) -> str:
    for k in props:
        if not _PROP_KEY.fullmatch(k):
            raise HTTPException(400, f"Invalid property name: {k!r}")
    return ",\n  ".join(f"{k} = {_lit(v)}" for k, v in props.items())


# RisingWave keeps each object's DDL, credentials included, in rw_catalog. Lists
# return the definition for display; the secret values in it never leave.
_SECRET_PROP = re.compile(
    r"((?:password|[\w.]*secret[\w.]*|[\w.]*access[._]key[\w.]*|[\w.]*token)\s*=\s*)'(?:[^']|'')*'",
    re.I)


def _redact(definition: Optional[str]) -> Optional[str]:
    return _SECRET_PROP.sub(r"\1'••••••'", definition) if definition else definition


def _redacted(rows: List[Dict]) -> List[Dict]:
    return [{**r, "definition": _redact(r.get("definition"))} if "definition" in r else r for r in rows]


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
        return _serialize(_redacted(rows))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/streaming/sources", dependencies=[Depends(require_permission("pipeline:write"))])
async def create_source(req: CreateSourceRequest):
    try:
        name = _ident(req.name)
        if req.connector not in _SOURCE_CONNECTORS:
            raise HTTPException(400, f"connector must be one of {sorted(_SOURCE_CONNECTORS)}")
        if req.format.lower() not in _FORMATS or req.row_encode.lower() not in _ENCODES:
            raise HTTPException(400, f"format must be one of {sorted(_FORMATS)}; encode one of {sorted(_ENCODES)}")
        col_defs = req.columns_sql or "data JSONB"
        props: Dict[str, Any] = {"connector": req.connector}
        if req.connector == "kafka":
            props["topic"] = req.topic
            props["properties.bootstrap.server"] = req.bootstrap_servers
            props["scan.startup.mode"] = "latest"
        props.update(req.extra_props)

        props_sql = _props_sql(props)
        sql = f"""
CREATE SOURCE {name} ({col_defs})
WITH (
  {props_sql}
)
FORMAT {req.format.upper()} ENCODE {req.row_encode.upper()}
"""
        _execute(sql, fetch=False)
        return {"message": f"Source '{name}' created", "sql": _redact(sql.strip())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/streaming/sources/{name}", dependencies=[Depends(require_permission("pipeline:write"))])
async def drop_source(name: str):
    try:
        _execute(f"DROP SOURCE {_ident(name)}", fetch=False)
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


@router.post("/streaming/views", dependencies=[Depends(require_permission("pipeline:write"))])
async def create_view(req: CreateMvRequest):
    try:
        sql = f"CREATE MATERIALIZED VIEW {_ident(req.name)} AS {req.definition}"
        _execute(sql, fetch=False)
        return {"message": f"Materialized view '{req.name}' created", "sql": sql}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/streaming/views/{name}", dependencies=[Depends(require_permission("pipeline:write"))])
async def drop_view(name: str):
    try:
        _execute(f"DROP MATERIALIZED VIEW {_ident(name)}", fetch=False)
        return {"message": f"Materialized view '{name}' dropped"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/streaming/views/{name}/data", dependencies=[Depends(require_permission("pipeline:write"))])
async def preview_view(name: str, limit: int = 50):
    """Rows of a view, as RisingWave holds them: unmasked source data, so only for
    those who build streams. The name used to go into the SQL as typed, for anyone
    signed in."""
    name = _ident(name)
    limit = max(1, min(int(limit), 500))
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
        return _serialize(_redacted(rows))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/streaming/sinks", dependencies=[Depends(require_permission("pipeline:write"))])
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

        props_sql = _props_sql(props)
        sql = f"""
CREATE SINK {_ident(req.name)}
FROM {_ident(req.from_mv, "from_mv")}
WITH (
  {props_sql}
)
"""
        _execute(sql, fetch=False)
        return {"message": f"Sink '{req.name}' created", "sql": _redact(sql.strip())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/streaming/sinks/{name}", dependencies=[Depends(require_permission("pipeline:write"))])
async def drop_sink(name: str):
    try:
        _execute(f"DROP SINK {_ident(name)}", fetch=False)
        return {"message": f"Sink '{name}' dropped"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── CDC Connection Test ────────────────────────────────────────────────────────

class CdcTestRequest(BaseModel):
    """Either an existing DataPond source (connection_id: its stored host, user and
    password are used, never sent back) or a connection typed in."""
    connection_id: Optional[str] = None
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_schema: str = "public"


async def _db_target(req, user: dict) -> Dict[str, Any]:
    """Host, port, database, user and password for the CDC source."""
    if req.connection_id:
        from app.api.connectors import get_db_pool, vault
        from app.api.source_access import CONNECTOR, require_access
        # Writing a source's stored password into a stream is a change to that source.
        await require_access(CONNECTOR, req.connection_id, user, write=True)
        try:
            cid = uuid.UUID(req.connection_id)
        except ValueError:
            raise HTTPException(400, "Invalid connection id")
        pool = await get_db_pool()
        async with pool.acquire() as c:
            row = await c.fetchrow("SELECT connector_type, config_encrypted FROM connector_connections WHERE id = $1", cid)
        if not row:
            raise HTTPException(404, "Source not found")
        if str(row["connector_type"]).lower() not in ("postgresql", "postgres"):
            raise HTTPException(400, "Only PostgreSQL sources can stream changes (CDC)")
        cfg = vault.decrypt_credentials(row["config_encrypted"])
        return {"host": cfg.get("host") or "", "port": int(cfg.get("port") or 5432),
                "database": cfg.get("database") or "", "user": cfg.get("username") or "",
                "password": cfg.get("password") or "", "schema": req.db_schema or "public"}
    if not (req.db_host and req.db_name and req.db_user):
        raise HTTPException(400, "Choose a source, or give host, database and user")
    return {"host": req.db_host, "port": req.db_port, "database": req.db_name,
            "user": req.db_user, "password": req.db_password, "schema": req.db_schema or "public"}


def _cdc_checks(t: Dict[str, Any]) -> Dict[str, Any]:
    """What RisingWave's postgres-cdc needs from the database, each as a check."""
    import psycopg2 as _pg
    checks: List[Dict[str, Any]] = []
    try:
        conn = _pg.connect(host=t["host"], port=t["port"], dbname=t["database"],
                           user=t["user"], password=t["password"], connect_timeout=10)
    except Exception as e:
        checks.append({"key": "reachable", "ok": False, "label": "Reachable",
                       "detail": str(e).strip().splitlines()[0] if str(e).strip() else "Could not connect"})
        return {"success": False, "checks": checks, "tables": [], "wal_level": None, "wal_ok": False,
                "error": checks[0]["detail"]}
    try:
        cur = conn.cursor()
        checks.append({"key": "reachable", "ok": True, "label": f"Reachable as {t['user']}", "detail": None})
        cur.execute("SHOW wal_level")
        wal = cur.fetchone()[0]
        checks.append({"key": "wal_level", "ok": wal == "logical", "label": f"wal_level is {wal}",
                       "detail": None if wal == "logical" else
                       "Must be logical. Set wal_level = logical (on RDS/Aurora: rds.logical_replication = 1 in the parameter group), then restart the database."})
        cur.execute("""SELECT r.rolsuper OR r.rolreplication
                              OR EXISTS (SELECT 1 FROM pg_roles g WHERE g.rolname = 'rds_replication'
                                         AND pg_has_role(current_user, g.oid, 'member'))
                       FROM pg_roles r WHERE r.rolname = current_user""")
        rep = bool((cur.fetchone() or [False])[0])
        checks.append({"key": "replication", "ok": rep, "label": "REPLICATION privilege",
                       "detail": None if rep else f"Grant it: ALTER ROLE {t['user']} WITH REPLICATION (on RDS: GRANT rds_replication TO {t['user']})."})
        cur.execute("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name""", (t["schema"],))
        tables = [r[0] for r in cur.fetchall()]
        checks.append({"key": "publication", "ok": True, "label": "Publication",
                       "detail": "Created for you if missing."})
    finally:
        conn.close()
    ok = all(c["ok"] for c in checks)
    return {"success": True, "ready": ok, "checks": checks, "tables": tables,
            "wal_level": wal, "wal_ok": wal == "logical"}


@router.post("/streaming/cdc-test", dependencies=[Depends(require_permission("pipeline:write"))])
async def test_cdc_connection(req: CdcTestRequest, user: dict = Depends(require_user)):
    """Can this database stream? Connects, checks wal_level and the REPLICATION
    privilege, and lists its tables. Never returns the password."""
    import asyncio
    target = await _db_target(req, user)
    return await asyncio.to_thread(_cdc_checks, target)


# ── CDC Pipeline ──────────────────────────────────────────────────────────────

class CdcPipelineRequest(CdcTestRequest):
    """Create a full CDC pipeline: RisingWave postgres-cdc source → Iceberg sink."""
    pipeline_name: str          # unique name prefix for source/mv/sink
    tables: List[str]
    iceberg_schema: str = "raw"
    slot_name: str = ""         # unique per pipeline in PostgreSQL


@router.post("/streaming/cdc-pipeline", dependencies=[Depends(require_permission("pipeline:write"))])
async def create_cdc_pipeline(req: CdcPipelineRequest, user: dict = Depends(require_user)):
    """
    Create a complete CDC pipeline for each table:
      1. CREATE SOURCE <name>_<table>_src  (postgres-cdc connector)
      2. CREATE MATERIALIZED VIEW <name>_<table>_mv  AS SELECT * FROM source
      3. CREATE SINK <name>_<table>_sink  (Iceberg sink)
    Returns the status for each table. The DDL is not returned: it holds the password.
    """
    pipeline = _ident(req.pipeline_name, "pipeline_name")
    _ident(req.iceberg_schema, "iceberg_schema")
    if not req.tables:
        raise HTTPException(400, "Choose at least one table")
    tables = [_ident(t, "table") for t in req.tables]
    target = await _db_target(req, user)
    warehouse   = os.getenv("ICEBERG_WAREHOUSE", "s3a://iceberg/warehouse")
    slot_name   = _ident(req.slot_name, "slot_name") if req.slot_name else f"datapond_{pipeline.lower()}"

    results = []
    for table in tables:
        safe   = table.lower()
        prefix = f"{pipeline}_{safe}"
        src_name  = f"{prefix}_src"
        mv_name   = f"{prefix}_mv"
        sink_name = f"{prefix}_sink"
        status = "success"
        error  = None
        try:
            src_props = _props_sql({
                "connector": "postgres-cdc", "hostname": target["host"], "port": target["port"],
                "username": target["user"], "password": target["password"],
                "database.name": target["database"], "schema.name": target["schema"],
                "table.name": table, "slot.name": f"{slot_name}_{safe}",
            })
            _execute(f"CREATE SOURCE IF NOT EXISTS {src_name}\nWITH (\n  {src_props}\n)", fetch=False)
            _execute(f"CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} AS SELECT * FROM {src_name}", fetch=False)
            # S3 creds injected on MinIO, omitted on AWS (credential chain).
            sink_props = _props_sql({
                "connector": "iceberg", "type": "upsert", "catalog.type": "storage",
                "warehouse.path": warehouse, **_iceberg_sink_s3_props(),
                "database.name": req.iceberg_schema, "table.name": safe,
            })
            _execute(f"CREATE SINK IF NOT EXISTS {sink_name}\nFROM {mv_name}\nWITH (\n  {sink_props}\n)", fetch=False)
        except Exception as e:
            status = "failed"
            error  = _redact(str(e))

        results.append({"table": table, "source": src_name, "view": mv_name, "sink": sink_name,
                        "status": status, "error": error})

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "pipeline_name": pipeline,
        "tables_total":   len(tables),
        "tables_success": success_count,
        "tables_failed":  len(tables) - success_count,
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
        return _serialize(_redacted(rows))
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


@router.post("/streaming/event-pipeline", dependencies=[Depends(require_permission("pipeline:write"))])
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
    name      = _ident(req.pipeline_name, "pipeline_name")
    _ident(req.iceberg_schema, "iceberg_schema")
    if req.source_type not in ("kafka", "kinesis"):
        raise HTTPException(400, "source_type must be kafka or kinesis")
    if req.format.lower() not in _ENCODES:
        raise HTTPException(400, f"format must be one of {sorted(_ENCODES)}")
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
        props: Dict[str, Any] = {"connector": req.source_type}
        if is_kafka:
            props["topic"] = req.topic
            props["properties.bootstrap.server"] = req.bootstrap_servers
            props["scan.startup.mode"] = "latest"
        else:
            props["stream"] = req.stream_name
            props["aws.region"] = req.aws_region
        props_sql = _props_sql(props)
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
        sink_props_sql = _props_sql(sink_props)
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


@router.post("/streaming/sample-streams", dependencies=[Depends(require_permission("pipeline:write"))])
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

@router.post("/streaming/sql", dependencies=[Depends(require_permission("pipeline:write"))])
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
