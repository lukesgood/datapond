"""
SQL Lab API - Query execution via Trino with history logging
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Any
from sqlalchemy.orm import Session
import os
import time
import asyncio
import re
import uuid
import logging

logger = logging.getLogger(__name__)

# RLS (Layer 1) — gated by RLS_ENABLED (default off). See docs/RLS_DESIGN.md.
# When off, query execution behaves exactly as before (no auth/policy required).
RLS_ENABLED = os.getenv("RLS_ENABLED", "false").lower() in ("1", "true", "yes")
try:
    from app.api.auth import get_current_user
    from app.rls.engine import enforce, RlsDenied
    from app.rls import loader as rls_loader
    _RLS_IMPORTS_OK = True
except Exception as _rls_imp_err:  # pragma: no cover - import-time guard
    logging.getLogger(__name__).warning(f"[rls] disabled, import failed: {_rls_imp_err}")
    _RLS_IMPORTS_OK = False
    async def get_current_user(*a, **k):  # type: ignore
        return None

# Trino connection (lazy import to handle missing dependency gracefully)
try:
    from trino.dbapi import connect
    from trino.auth import BasicAuthentication
    TRINO_AVAILABLE = True
except ImportError:
    TRINO_AVAILABLE = False

from app.database.connection import get_db
from app.models.query import QueryHistory
from app.schemas.query import QueryExecuteRequest, QueryHistoryResponse, QueryHistoryListResponse
from app.api.query_engine import get_engine

router = APIRouter()

# Configuration
TRINO_HOST = os.getenv("TRINO_HOST", "trino.datapond.svc.cluster.local")
# Handle K8s injected env vars like "tcp://10.43.87.193:8080"
trino_port_str = os.getenv("TRINO_PORT", "8080")
if trino_port_str.startswith("tcp://"):
    TRINO_PORT = int(trino_port_str.split(":")[-1])
else:
    TRINO_PORT = int(trino_port_str)
TRINO_USER = os.getenv("TRINO_USER", "datapond")
# Trino 카탈로그명은 'iceberg'(Polaris REST 카탈로그). writer/ai_sql/catalog/quality와 통일.
# (과거 'polaris' 기본값은 Trino에 없는 카탈로그라 SHOW/USE/비수식 쿼리가 깨졌음)
TRINO_CATALOG = os.getenv("TRINO_CATALOG", "iceberg")
TRINO_SCHEMA = os.getenv("TRINO_SCHEMA", "default")
QUERY_TIMEOUT_SECONDS = 30
MAX_ROWS = 1000

# Mock user ID for now (replace with actual auth when implemented)
MOCK_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class QueryResult(BaseModel):
    columns: List[str]
    rows: List[List[Any]]
    execution_time_ms: float
    row_count: int


class CatalogColumn(BaseModel):
    name: str
    type: str


class CatalogTable(BaseModel):
    name: str
    columns: Optional[List[CatalogColumn]] = None


class CatalogSchema(BaseModel):
    name: str
    tables: List[CatalogTable]


class Catalog(BaseModel):
    name: str
    schemas: List[CatalogSchema]
    catalog_type: str = "managed"


class CatalogTree(BaseModel):
    catalogs: List[Catalog]


def get_trino_connection(trino_user: Optional[str] = None):
    """Create Trino connection with timeout. `trino_user` overrides the session
    user so RLS/Trino-native policies see the real identity (default: TRINO_USER)."""
    if not TRINO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Trino client not available. Install trino package."
        )

    try:
        conn = connect(
            host=TRINO_HOST,
            port=TRINO_PORT,
            user=trino_user or TRINO_USER,
            catalog=TRINO_CATALOG,
            schema=TRINO_SCHEMA,
            http_scheme="http",
            request_timeout=QUERY_TIMEOUT_SECONDS
        )
        return conn
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to Trino: {str(e)}"
        )


def add_limit_to_query(query: str, limit: int = MAX_ROWS) -> str:
    """Add LIMIT clause to query if not present"""
    query = query.strip().rstrip(";")

    # Check if query already has LIMIT (case-insensitive)
    if re.search(r'\bLIMIT\s+\d+\b', query, re.IGNORECASE):
        return query

    # Don't add LIMIT to DDL or SHOW commands
    ddl_commands = ['CREATE', 'DROP', 'ALTER', 'SHOW', 'DESCRIBE', 'DESC']
    first_word = query.split()[0].upper() if query.split() else ""
    if first_word in ddl_commands:
        return query

    # Add LIMIT to SELECT queries
    if query.upper().startswith('SELECT'):
        # Remove trailing semicolon if present
        if query.endswith(';'):
            query = query[:-1]
        return f"{query} LIMIT {limit}"

    return query


@router.post("/queries/execute", response_model=QueryResult)
async def execute_query(
    request: QueryExecuteRequest,
    db: Session = Depends(get_db),
    user: Optional[dict] = Depends(get_current_user),
):
    """
    Execute SQL query via Trino with optional history logging

    - Timeout: 30 seconds
    - Row limit: 1000 rows (auto-added if not present)
    - Returns: columns, rows, execution time, row count
    - Saves to history if save_history=true
    """
    # Strip comments and whitespace to get actual SQL
    sql_lines = [
        line for line in request.query.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    effective_query = "\n".join(sql_lines).strip()

    if not effective_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    engine = get_engine()
    # ── RLS enforcement (Layer 1) — gated by RLS_ENABLED ──────────────────────
    trino_user = TRINO_USER
    if RLS_ENABLED and _RLS_IMPORTS_OK:
        if not user:
            raise HTTPException(status_code=401, detail="RLS 활성화됨 — 인증이 필요합니다")
        try:
            ctx = await rls_loader.load_user_context(user)
            policies = await rls_loader.load_policies()
            masks = await rls_loader.load_masks()
            result = enforce(effective_query, ctx, policies, masks, dialect=engine.rls_dialect)
            effective_query = result.sql
            trino_user = ctx.username or TRINO_USER  # run as the real user
        except RlsDenied as d:
            await rls_loader.audit_denial(ctx, request.query, d.message, d.table)
            raise HTTPException(status_code=403, detail=f"RLS 차단: {d.message}")
        except HTTPException:
            raise
        except Exception as e:
            # fail-closed under default_deny posture
            logger.warning(f"[rls] enforcement error, blocking: {e}")
            raise HTTPException(status_code=403, detail="RLS 적용 중 오류로 쿼리가 차단되었습니다")

    # Add row limit for safety
    safe_query = add_limit_to_query(effective_query, MAX_ROWS)

    start_time = time.time()
    status = "success"
    error_msg = None
    rows = []
    columns = []

    def _run_blocking():
        """엔진 실행/페치(블로킹) — 워커 스레드에서 수행해 이벤트루프를 보호한다.
        무거운 쿼리 1건이 전체 API를 동결시키던 문제의 근본 수정."""
        return engine.execute(safe_query, trino_user)

    try:
        rows, columns = await asyncio.to_thread(_run_blocking)

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        # Engine-specific error taxonomy (Trino codes vs Athena/pyathena messages).
        status, error_detail, http_code = engine.map_error(e)

        # Save error to history if requested
        if request.save_history:
            try:
                history = QueryHistory(
                    user_id=MOCK_USER_ID,
                    query_text=request.query,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    rows_returned=0,
                    status=status,
                    error_message=error_msg,
                    catalog=engine.default_catalog,
                    schema=engine.default_schema
                )
                db.add(history)
                db.commit()
            except Exception as db_err:
                # Don't fail the request if history save fails
                print(f"Failed to save query history: {db_err}")

        raise HTTPException(status_code=http_code, detail=error_detail)

    execution_time_ms = (time.time() - start_time) * 1000

    # Save successful query to history
    if request.save_history:
        try:
            history = QueryHistory(
                user_id=MOCK_USER_ID,
                query_text=request.query,
                execution_time_ms=int(execution_time_ms),
                rows_returned=len(rows),
                status=status,
                catalog=engine.default_catalog,
                schema=engine.default_schema
            )
            db.add(history)
            db.commit()
        except Exception as e:
            # Don't fail the request if history save fails
            print(f"Failed to save query history: {e}")

    return QueryResult(
        columns=columns,
        rows=rows,
        execution_time_ms=round(execution_time_ms, 2),
        row_count=len(rows)
    )


@router.get("/queries/history", response_model=QueryHistoryListResponse)
async def get_query_history(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get query execution history for current user

    - Paginated results (default: 50 items)
    - Ordered by most recent first
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 200")

    if offset < 0:
        raise HTTPException(status_code=400, detail="Offset must be non-negative")

    try:
        # Get total count
        total = db.query(QueryHistory).filter(
            QueryHistory.user_id == MOCK_USER_ID
        ).count()

        # Get paginated results
        items = db.query(QueryHistory).filter(
            QueryHistory.user_id == MOCK_USER_ID
        ).order_by(
            QueryHistory.created_at.desc()
        ).limit(limit).offset(offset).all()

        return QueryHistoryListResponse(
            items=[QueryHistoryResponse.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch query history: {str(e)}"
        )


@router.get("/catalog/schemas", response_model=CatalogTree)
async def get_catalog_schemas(columns: bool = False):
    """
    Get catalog tree structure — only catalogs registered in Polaris (governance gate).
    Catalog/namespace/table listing comes from Polaris (fast). Column metadata is
    NOT fetched by default — eager column enumeration triggers a Trino
    information_schema scan that reads every table's Iceberg metadata from object
    storage (tens of seconds → ingress 504). Columns load lazily per table via
    /catalog/columns. Pass ?columns=true to force the (slow) eager scan.
    Cached in Valkey (TTL 60s, keyed by the columns flag).
    """
    cache_key = f"catalog:schemas:v3:{'full' if columns else 'tree'}"
    # Try Valkey cache first
    try:
        import redis, json as _json
        _redis = redis.Redis(
            host=os.getenv("VALKEY_HOST", "valkey.datapond.svc.cluster.local"),
            port=int(os.getenv("VALKEY_PORT", "6379")),
            decode_responses=True, socket_timeout=1,
        )
        cached = _redis.get(cache_key)
        if cached:
            return CatalogTree(**_json.loads(cached))
    except Exception:
        _redis = None

    try:
        from app.api.catalog_backend import get_catalog_reader
        reader = get_catalog_reader()

        schemas_list = []
        for ns in reader.list_namespaces():
            try:
                table_names = reader.list_tables(ns)
            except Exception:
                table_names = []
            tables_list = []
            for tbl in table_names:
                cols = None
                if columns:
                    # Opt-in eager column load (per-table). Lazy /catalog/columns is the default.
                    try:
                        cols = [CatalogColumn(name=c["name"], type=c["type"])
                                for c in reader.get_columns(ns, tbl)]
                    except Exception:
                        cols = None
                tables_list.append(CatalogTable(name=tbl, columns=cols))
            schemas_list.append(CatalogSchema(name=ns, tables=tables_list))

        result = CatalogTree(catalogs=[Catalog(name=get_engine().default_catalog, catalog_type="managed", schemas=schemas_list)])

        # Cache result
        try:
            if _redis:
                _redis.setex(cache_key, 60, result.model_dump_json())
        except Exception:
            pass

        return result

    except HTTPException:
        raise
    except Exception as e:
        if "connection" in str(e).lower() or "refused" in str(e).lower():
            return CatalogTree(catalogs=[
                Catalog(
                    name="iceberg",
                    catalog_type="managed",
                    schemas=[
                        CatalogSchema(
                            name="default",
                            tables=[
                                CatalogTable(
                                    name="sample_table",
                                    columns=[
                                        CatalogColumn(name="id", type="bigint"),
                                        CatalogColumn(name="name", type="varchar"),
                                        CatalogColumn(name="created_at", type="timestamp")
                                    ]
                                )
                            ]
                        )
                    ]
                )
            ])
        raise HTTPException(status_code=500, detail=f"Failed to fetch catalog: {str(e)}")


_COL_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


@router.get("/catalog/columns", response_model=List[CatalogColumn])
async def get_table_columns(catalog: str, schema: str, table: str):
    """Lazily fetch ONE table's columns (loaded on table expand in the schema tree).
    A single-table information_schema query is one metadata read (fast) — unlike the
    eager full-tree scan that made /catalog/schemas time out. Cached 5 min."""
    for v in (catalog, schema, table):
        if not _COL_IDENT.match(v or ""):
            raise HTTPException(status_code=400, detail="catalog/schema/table must be bare identifiers.")
    ck = f"catalog:cols:v1:{catalog}.{schema}.{table}"
    try:
        import redis, json as _json
        _r = redis.Redis(
            host=os.getenv("VALKEY_HOST", "valkey.datapond.svc.cluster.local"),
            port=int(os.getenv("VALKEY_PORT", "6379")), decode_responses=True, socket_timeout=1,
        )
        c = _r.get(ck)
        if c:
            return [CatalogColumn(**x) for x in _json.loads(c)]
    except Exception:
        _r = None
    try:
        from app.api.catalog_backend import get_catalog_reader
        cols = [CatalogColumn(name=c["name"], type=c["type"])
                for c in get_catalog_reader().get_columns(schema, table)]
        try:
            if _r:
                import json as _json
                _r.setex(ck, 300, _json.dumps([c.model_dump() for c in cols]))
        except Exception:
            pass
        return cols
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch columns: {str(e)[:200]}")
