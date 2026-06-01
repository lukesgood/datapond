"""
SQL Lab API - Query execution via Trino with history logging
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Any
from sqlalchemy.orm import Session
import os
import time
import re
import uuid

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


def get_trino_connection():
    """Create Trino connection with timeout"""
    if not TRINO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Trino client not available. Install trino package."
        )

    try:
        conn = connect(
            host=TRINO_HOST,
            port=TRINO_PORT,
            user=TRINO_USER,
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
async def execute_query(request: QueryExecuteRequest, db: Session = Depends(get_db)):
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

    # Add row limit for safety
    safe_query = add_limit_to_query(effective_query, MAX_ROWS)

    start_time = time.time()
    status = "success"
    error_msg = None
    rows = []
    columns = []

    try:
        conn = get_trino_connection()
        cursor = conn.cursor()

        # Execute query
        cursor.execute(safe_query)

        # Fetch results
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

        cursor.close()
        conn.close()

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        status = "error"

        # Extract clean message from Trino error
        # TrinoUserError format: "...message="actual message", query_id=..."
        clean_msg = error_msg
        if 'message="' in error_msg:
            try:
                clean_msg = error_msg.split('message="')[1].split('"')[0]
            except Exception:
                pass

        if "SYNTAX_ERROR" in error_msg or "syntax error" in error_msg.lower():
            error_detail = f"Syntax error: {clean_msg}"
        elif "TABLE_NOT_FOUND" in error_msg or "Table" in error_msg and "not found" in error_msg.lower():
            error_detail = f"Table not found: {clean_msg}"
        elif "SCHEMA_NOT_FOUND" in error_msg or "Schema" in error_msg and "not found" in error_msg.lower():
            error_detail = f"Schema not found: {clean_msg}"
        elif "CATALOG_NOT_FOUND" in error_msg:
            error_detail = f"Catalog not found: {clean_msg}"
        elif "PERMISSION_DENIED" in error_msg:
            error_detail = f"Permission denied: {clean_msg}"
        elif "timeout" in error_msg.lower():
            status = "timeout"
            error_detail = "Query timed out (30s limit). Try adding a LIMIT clause."
        elif "connect" in error_msg.lower() or "connection" in error_msg.lower():
            error_detail = "Cannot connect to query engine. Check if Trino is running."
        else:
            error_detail = clean_msg if clean_msg != error_msg else f"Query failed: {clean_msg}"

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
                    catalog=TRINO_CATALOG,
                    schema=TRINO_SCHEMA
                )
                db.add(history)
                db.commit()
            except Exception as db_err:
                # Don't fail the request if history save fails
                print(f"Failed to save query history: {db_err}")

        raise HTTPException(status_code=400 if status == "error" else 504, detail=error_detail)

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
                catalog=TRINO_CATALOG,
                schema=TRINO_SCHEMA
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
async def get_catalog_schemas():
    """
    Get catalog tree structure — only catalogs registered in Polaris (governance gate).
    Uses Polaris for catalog/namespace/table listing, Trino for column metadata.
    Cached in Valkey (TTL 60s).
    """
    # Try Valkey cache first
    try:
        import redis, json as _json
        _redis = redis.Redis(
            host=os.getenv("VALKEY_HOST", "valkey.datapond.svc.cluster.local"),
            port=int(os.getenv("VALKEY_PORT", "6379")),
            decode_responses=True, socket_timeout=1,
        )
        cached = _redis.get("catalog:schemas:v2")
        if cached:
            return CatalogTree(**_json.loads(cached))
    except Exception:
        _redis = None

    try:
        from app.api.polaris_client import list_catalogs, list_namespaces, list_tables, get_catalog_type

        polaris_catalogs = list_catalogs()
        catalogs = []

        # Get Trino connection for column info
        try:
            conn = get_trino_connection()
            cursor = conn.cursor()
            has_trino = True
        except Exception:
            has_trino = False
            cursor = None

        for pcat in polaris_catalogs:
            cat_name = pcat["name"]
            cat_type = get_catalog_type(pcat)
            schemas_list = []

            try:
                namespaces = list_namespaces(cat_name)
            except Exception:
                namespaces = []

            for ns in namespaces:
                tables_list = []
                try:
                    table_names = list_tables(cat_name, ns)
                except Exception:
                    table_names = []

                # Batch column fetch from Trino if available
                col_map: dict = {}
                if has_trino and table_names:
                    try:
                        cursor.execute(
                            f"SELECT table_name, column_name, data_type "
                            f"FROM {cat_name}.information_schema.columns "
                            f"WHERE table_schema = '{ns}' "
                            f"ORDER BY table_name, ordinal_position"
                        )
                        for tbl, col, dtype in cursor.fetchall():
                            col_map.setdefault(tbl, []).append(
                                CatalogColumn(name=col, type=dtype)
                            )
                    except Exception:
                        pass

                for tbl in table_names:
                    cols = col_map.get(tbl)
                    tables_list.append(CatalogTable(name=tbl, columns=cols))

                schemas_list.append(CatalogSchema(name=ns, tables=tables_list))

            catalogs.append(Catalog(name=cat_name, schemas=schemas_list, catalog_type=cat_type))

        if has_trino and cursor:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass

        result = CatalogTree(catalogs=catalogs)

        # Cache result
        try:
            if _redis:
                import json as _json
                _redis.setex("catalog:schemas:v2", 60, result.model_dump_json())
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
