"""Reach a Trino-backed source through its own driver.

A connection becomes queryable through Trino only after its catalog is projected and
Trino has restarted (~1 min). The wizard cannot wait for that to test a password or
list tables for Step 2, and a connection whose catalog is broken still needs a check
that says why. So three things go through the source's driver: `test` (one connect, one
trivial statement), `list_tables` and `columns`. Everything else — reads, syncs — is
Trino's. Nothing here returns the password in a message: driver errors echo connection
strings, so `scrub` removes it (raw and URL-encoded) before the text leaves.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
import logging
import re
import ssl as _ssl
import time
from typing import Dict, List, Tuple
from urllib.parse import quote, quote_plus

from .base import ColumnSchema, ConnectionTestResult, ConnectorType as T
from .trino_source import TrinoSourceConfig

logger = logging.getLogger(__name__)

DRIVERS: Dict[T, str] = {
    T.POSTGRESQL: "psycopg2", T.MYSQL: "pymysql", T.SQLSERVER: "pytds",
    T.ORACLE: "oracledb", T.MONGODB: "pymongo",
    T.REDSHIFT: "psycopg2",             # Redshift speaks the PostgreSQL wire protocol
}
# BigQuery has no driver here: it is reached through its REST API (`_bq_*` below) with a
# token for the pasted service account.

# Schemas the engines keep for themselves (same list the registry reader hides).
SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog", "pg_toast", "mysql", "sys",
                            "performance_schema"})
_IDENT = re.compile(r"^[A-Za-z0-9_$]+$")


class ProbeError(RuntimeError):
    """A failure with a message safe to show."""


def _driver(t: T):
    mod = DRIVERS.get(t)
    if mod is None:
        raise ProbeError(f"{t.value} has no driver probe.")
    try:
        return importlib.import_module(mod)
    except ImportError:
        raise ProbeError(f"{mod} is not installed")


def scrub(text: str, cfg: TrinoSourceConfig) -> str:
    """`text` with every spelling of the password removed. A password shorter than four
    characters is not scrubbed: it would be a substring of ordinary words and turn the
    message into asterisks (and no real system accepts one)."""
    return scrub_password(text, cfg.password)


def scrub_password(text: str, password) -> str:
    """`scrub` for a raw config dict's password (routes that have no TrinoSourceConfig)."""
    out = str(text or "")
    pw = password or ""
    if len(pw) >= 4:
        for spelled in {pw, quote_plus(pw), quote(pw, safe="")}:
            out = out.replace(spelled, "***")
    return out


def default_schema(t: T, cfg: TrinoSourceConfig) -> str:
    if cfg.schema_name:
        return cfg.schema_name
    if t in (T.POSTGRESQL, T.REDSHIFT):
        return "public"
    if t == T.SQLSERVER:
        return "dbo"
    if t == T.ORACLE:
        return (cfg.username or "").upper()
    return cfg.database or ""           # MySQL schema = database; MongoDB database


def split_table(t: T, cfg: TrinoSourceConfig, table: str) -> Tuple[str, str]:
    """"schema.table" → (schema, table); a bare name gets the engine's default."""
    parts = str(table or "").split(".")
    if len(parts) == 1:
        schema, name = default_schema(t, cfg), parts[0]
    elif len(parts) == 2:
        schema, name = parts
    else:
        raise ValueError(f"Not a table name: {table!r} — expected table or schema.table.")
    for p in (schema, name):
        if not p or not _IDENT.match(p):
            raise ValueError(f"Not a table name: {table!r}")
    return schema, name


# ── connecting ────────────────────────────────────────────────────────────────

def _connect(t: T, cfg: TrinoSourceConfig, timeout: float):
    drv = _driver(t)
    secs = max(1, int(timeout))
    if t == T.POSTGRESQL:
        return drv.connect(host=cfg.host, port=cfg.port, dbname=cfg.database, user=cfg.username,
                           password=cfg.password, connect_timeout=secs,
                           sslmode="require" if cfg.ssl else "prefer")
    if t == T.REDSHIFT:
        return drv.connect(host=cfg.host, port=cfg.port, dbname=cfg.database, user=cfg.username,
                           password=cfg.password, connect_timeout=secs,
                           sslmode="require" if cfg.ssl else "prefer")
    if t == T.MYSQL:
        ctx = None
        if cfg.ssl:
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        return drv.connect(host=cfg.host, port=cfg.port, user=cfg.username, password=cfg.password,
                           database=cfg.database or None, connect_timeout=secs,
                           read_timeout=secs, ssl=ctx)
    if t == T.SQLSERVER:
        return drv.connect(server=cfg.host, port=cfg.port, database=cfg.database,
                           user=cfg.username, password=cfg.password,
                           login_timeout=secs, timeout=secs)
    if t == T.ORACLE:
        return drv.connect(user=cfg.username, password=cfg.password,
                           dsn=f"{cfg.host}:{cfg.port}/{cfg.database}",
                           tcp_connect_timeout=float(secs))
    if t == T.MONGODB:
        return drv.MongoClient(host=cfg.host, port=cfg.port, username=cfg.username or None,
                               password=cfg.password or None, authSource=cfg.auth_source or "admin",
                               tls=bool(cfg.ssl), serverSelectionTimeoutMS=secs * 1000,
                               connectTimeoutMS=secs * 1000, socketTimeoutMS=secs * 1000)
    raise ProbeError(f"{t.value} has no driver probe.")


def _close(handle) -> None:
    try:
        handle.close()
    except Exception:
        pass


def _query(t: T, handle, sql: str, params=()) -> List[tuple]:
    cur = handle.cursor()
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        return [tuple(r) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        except Exception:
            pass


# ── the three probes ──────────────────────────────────────────────────────────

def test(t: T, cfg: TrinoSourceConfig, timeout: float = 10.0) -> ConnectionTestResult:
    started = time.monotonic()
    if t == T.BIGQUERY:
        try:
            datasets = _bq_datasets(cfg, timeout)
            return ConnectionTestResult(
                success=True, latency_ms=(time.monotonic() - started) * 1000,
                message=f"Connected to BigQuery project {_bq_project(cfg)} ({len(datasets)} datasets)",
                metadata={"engine": "trino", "preview": True})
        except ProbeError as e:
            return ConnectionTestResult(success=False, message=str(e))
        except Exception as e:
            return ConnectionTestResult(success=False, message=_bq_scrub(str(e) or type(e).__name__, cfg)[:500],
                                        latency_ms=(time.monotonic() - started) * 1000)
    try:
        handle = _connect(t, cfg, timeout)
        try:
            if t == T.MONGODB:
                handle.admin.command("ping")
            elif t == T.ORACLE:
                _query(t, handle, "SELECT 1 FROM dual")
            else:
                _query(t, handle, "SELECT 1")
        finally:
            _close(handle)
        return ConnectionTestResult(success=True, message=f"Connected to {t.value}",
                                    latency_ms=(time.monotonic() - started) * 1000,
                                    metadata={"engine": "trino"})
    except ProbeError as e:
        return ConnectionTestResult(success=False, message=str(e))
    except Exception as e:
        msg = scrub(str(e) or type(e).__name__, cfg)[:500]
        return ConnectionTestResult(success=False, message=msg,
                                    latency_ms=(time.monotonic() - started) * 1000)


def list_tables(t: T, cfg: TrinoSourceConfig, timeout: float = 10.0) -> List[str]:
    """`schema.table` for the user's schemas (MongoDB: `database.collection`; BigQuery:
    `dataset.table`)."""
    if t == T.BIGQUERY:
        return _bq_tables(cfg, timeout)
    handle = _connect(t, cfg, timeout)
    try:
        if t == T.MONGODB:
            names = handle[cfg.database].list_collection_names()
            return [f"{cfg.database}.{n}" for n in sorted(names) if not n.startswith("system.")]
        if t == T.ORACLE:
            rows = _query(t, handle, "SELECT owner, table_name FROM all_tables "
                                     "WHERE oracle_maintained = 'N' ORDER BY owner, table_name")
        elif t == T.MYSQL and cfg.database:
            rows = _query(t, handle, "SELECT table_schema, table_name FROM information_schema.tables "
                                     "WHERE table_schema = %s ORDER BY 1, 2", (cfg.database,))
        else:
            rows = _query(t, handle, "SELECT table_schema, table_name FROM information_schema.tables "
                                     "WHERE table_type IN ('BASE TABLE', 'VIEW') ORDER BY 1, 2")
        return [f"{s}.{n}" for s, n in rows if str(s).lower() not in SYSTEM_SCHEMAS]
    finally:
        _close(handle)


def mongo_columns(doc: dict) -> List[ColumnSchema]:
    """Columns from one sampled document, typed the way Trino's MongoDB connector would."""
    def kind(v):
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "bigint"
        if isinstance(v, float):
            return "double"
        if isinstance(v, _dt.datetime):
            return "timestamp(3)"
        if isinstance(v, (dict, list)):
            return "json"
        return "varchar"
    return [ColumnSchema(name=str(k), type=kind(v), nullable=True) for k, v in (doc or {}).items()]


def columns(t: T, cfg: TrinoSourceConfig, table: str, timeout: float = 10.0) -> List[ColumnSchema]:
    if t == T.BIGQUERY:
        return _bq_columns(cfg, table, timeout)
    schema, name = split_table(t, cfg, table)
    handle = _connect(t, cfg, timeout)
    try:
        if t == T.MONGODB:
            return mongo_columns(handle[schema][name].find_one() or {})
        if t == T.ORACLE:
            rows = _query(t, handle, "SELECT column_name, data_type, nullable FROM all_tab_columns "
                                     "WHERE owner = :1 AND table_name = :2 ORDER BY column_id",
                          (schema, name))
            return [ColumnSchema(name=c, type=str(d).lower(), nullable=(str(n).upper() == "Y"))
                    for c, d, n in rows]
        rows = _query(t, handle, "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                                 "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                      (schema, name))
        return [ColumnSchema(name=c, type=str(d).lower(), nullable=(str(n).upper() == "YES"))
                for c, d, n in rows]
    finally:
        _close(handle)


# ── BigQuery over REST (preview) ──────────────────────────────────────────────

_BQ = "https://bigquery.googleapis.com/bigquery/v2"
_BQ_SCOPE = "https://www.googleapis.com/auth/bigquery.readonly"
# Trino's BigQuery connector maps BigQuery types to these.
_BQ_TYPES = {"STRING": "varchar", "BYTES": "varbinary", "INTEGER": "bigint", "INT64": "bigint",
             "FLOAT": "double", "FLOAT64": "double", "NUMERIC": "decimal(38,9)",
             "BIGNUMERIC": "bignumeric", "BOOLEAN": "boolean", "BOOL": "boolean",
             "DATE": "date", "DATETIME": "timestamp(6)", "TIME": "time(6)",
             "TIMESTAMP": "timestamp(6) with time zone", "GEOGRAPHY": "varchar", "JSON": "json",
             "RECORD": "row", "STRUCT": "row"}


def _bq_info(cfg: TrinoSourceConfig) -> dict:
    from .trino_source import service_account_info
    try:
        return service_account_info({"credentials_key": cfg.credentials_key})
    except ValueError as e:
        raise ProbeError(str(e))


def _bq_project(cfg: TrinoSourceConfig) -> str:
    return cfg.project_id or _bq_info(cfg).get("project_id") or ""


def _bq_scrub(text: str, cfg: TrinoSourceConfig) -> str:
    """Errors never carry the private key."""
    out = str(text or "")
    try:
        key = _bq_info(cfg).get("private_key") or ""
    except ProbeError:
        key = ""
    return out.replace(key, "***") if len(key) > 8 else out


def _bq_get(cfg: TrinoSourceConfig, path: str, timeout: float, params=None) -> dict:
    import httpx
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(_bq_info(cfg), scopes=[_BQ_SCOPE])
    try:
        creds.refresh(Request())
    except Exception as e:
        raise ProbeError(f"Google refused the service account key: {_bq_scrub(str(e), cfg)[:300]}")
    r = httpx.get(f"{_BQ}{path}", params=params or {}, timeout=timeout,
                  headers={"Authorization": f"Bearer {creds.token}"})
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message") or r.text
        except ValueError:
            msg = r.text
        raise ProbeError(f"BigQuery answered {r.status_code}: {str(msg)[:300]}")
    return r.json()


def _bq_pages(cfg, path, key, timeout, cap=2000) -> List[dict]:
    out: List[dict] = []
    token = None
    while len(out) < cap:
        params = {"maxResults": 1000, **({"pageToken": token} if token else {})}
        body = _bq_get(cfg, path, timeout, params)
        out.extend(body.get(key) or [])
        token = body.get("nextPageToken")
        if not token:
            break
    return out


def _bq_datasets(cfg: TrinoSourceConfig, timeout: float) -> List[str]:
    project = _bq_project(cfg)
    if not project:
        raise ProbeError("project_id is required (or a key that names one).")
    if cfg.database:                    # one dataset asked for: check it exists
        _bq_get(cfg, f"/projects/{project}/datasets/{cfg.database}", timeout)
        return [cfg.database]
    return [d["datasetReference"]["datasetId"]
            for d in _bq_pages(cfg, f"/projects/{project}/datasets", "datasets", timeout)]


def _bq_tables(cfg: TrinoSourceConfig, timeout: float) -> List[str]:
    project = _bq_project(cfg)
    out: List[str] = []
    for ds in _bq_datasets(cfg, timeout):
        for t in _bq_pages(cfg, f"/projects/{project}/datasets/{ds}/tables", "tables", timeout):
            ref = t.get("tableReference") or {}
            if ref.get("tableId") and t.get("type") in ("TABLE", "VIEW", "EXTERNAL", "MATERIALIZED_VIEW", None):
                out.append(f"{ds}.{ref['tableId']}")
    return sorted(out)


def _bq_columns(cfg: TrinoSourceConfig, table: str, timeout: float) -> List[ColumnSchema]:
    parts = str(table or "").split(".")
    if len(parts) != 2 or not all(_IDENT.match(p) for p in parts):
        raise ValueError(f"Not a BigQuery table: {table!r} — expected dataset.table.")
    body = _bq_get(cfg, f"/projects/{_bq_project(cfg)}/datasets/{parts[0]}/tables/{parts[1]}", timeout)
    fields = (body.get("schema") or {}).get("fields") or []
    return [ColumnSchema(name=f["name"],
                         type=("array" if f.get("mode") == "REPEATED"
                               else _BQ_TYPES.get(str(f.get("type")).upper(), str(f.get("type")).lower())),
                         nullable=f.get("mode") != "REQUIRED")
            for f in fields]


# ── async wrappers (drivers block; never on the request loop) ────────────────

async def _run(fn, timeout: float, *args):
    return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout + 5)


async def atest(t, cfg, timeout: float = 10.0) -> ConnectionTestResult:
    try:
        return await _run(test, timeout, t, cfg, timeout)
    except asyncio.TimeoutError:
        return ConnectionTestResult(success=False, message=f"No answer within {timeout:.0f}s")


async def alist_tables(t, cfg, timeout: float = 10.0) -> List[str]:
    return await _run(list_tables, timeout, t, cfg, timeout)


async def acolumns(t, cfg, table: str, timeout: float = 10.0) -> List[ColumnSchema]:
    return await _run(columns, timeout, t, cfg, table, timeout)
