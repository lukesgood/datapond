"""
Data Catalog API — reads from Polaris (governance gate) + Trino for details.
Only data registered in Polaris is visible.
"""
import logging
import math
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import require_permission, require_user
from app.api.catalog_backend import get_catalog_reader, safe_identifier
from app.api.queries import execute_query
from app.api.query_engine import get_engine
from app.database.connection import get_db
from app.schemas.query import QueryExecuteRequest

# Every route here names tables, and a caller scoped away from the catalog should not
# learn what exists. The preview reads rows and adds `query:run` on top.
router = APIRouter(dependencies=[Depends(require_permission("catalog:read"))])

PREVIEW_MAX_ROWS = 500


def _bare(namespace: str, table: str) -> None:
    try:
        safe_identifier(namespace)
        safe_identifier(table)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="namespace and table must be bare identifiers.")
logger = logging.getLogger(__name__)


# ── Models ─────────────────────────────────────────────────────────────────────

class NamespaceInfo(BaseModel):
    name: str
    catalog: str = "iceberg"
    catalog_type: str = "managed"
    properties: Dict[str, Any] = {}

class NamespacesResponse(BaseModel):
    namespaces: List[NamespaceInfo]

class TableInfo(BaseModel):
    name: str
    namespace: str
    catalog: str = "iceberg"
    catalog_type: str = "managed"
    table_type: str = "iceberg"
    metadata_location: Optional[str] = None
    last_updated: Optional[str] = None
    row_count: Optional[int] = None

class TablesResponse(BaseModel):
    tables: List[TableInfo]

class TableColumn(BaseModel):
    name: str
    type: str
    nullable: bool = True
    comment: Optional[str] = None

class TableDetails(BaseModel):
    name: str
    namespace: str
    table_type: str = "iceberg"
    location: Optional[str] = None
    columns: List[TableColumn] = []
    properties: Dict[str, Any] = {}
    snapshot_id: Optional[str] = None
    row_count: Optional[int] = None
    last_updated: Optional[str] = None

class CatalogTree(BaseModel):
    catalogs: List[Dict[str, Any]] = []



# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/catalog/namespaces", response_model=NamespacesResponse)
async def list_all_namespaces():
    """List namespaces from the active catalog backend (Glue or Polaris)."""
    try:
        names = get_catalog_reader().list_namespaces()
        return NamespacesResponse(namespaces=[NamespaceInfo(name=n) for n in names])
    except Exception as e:
        logger.error(f"catalog namespaces error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables", response_model=TablesResponse)
async def list_all_tables():
    """List all tables from the active catalog backend (Glue or Polaris)."""
    try:
        reader = get_catalog_reader()
        # The engine decides the catalog name — AwsDataCatalog on Athena, iceberg on
        # Trino. Hardcoding it printed a name the engine would reject.
        default_catalog = get_engine().default_catalog
        tables = []
        for ns in reader.list_namespaces():
            try:
                for tbl in reader.list_tables(ns):
                    tables.append(TableInfo(name=tbl, namespace=ns, catalog=default_catalog))
            except Exception:
                continue
        return TablesResponse(tables=tables)
    except Exception as e:
        logger.error(f"catalog tables error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}", response_model=TableDetails)
async def get_table_details(namespace: str, table: str, catalog: Optional[str] = None):
    """Get table schema, location, and row count from the active catalog backend."""
    _bare(namespace, table)
    try:
        reader = get_catalog_reader()
        columns = [TableColumn(**c) for c in reader.get_columns(namespace, table)]
        if not columns:
            raise HTTPException(status_code=404, detail=f"Table {namespace}.{table} not found")
        location = reader.get_location(namespace, table)
        row_count = reader.row_count(namespace, table)
        return TableDetails(
            name=table,
            namespace=namespace,
            table_type="iceberg",
            location=location,
            columns=columns,
            properties={"location": location} if location else {},
            row_count=row_count,
            # last_updated intentionally omitted: neither the Glue nor Polaris
            # catalog reader currently surfaces a real snapshot/modification
            # timestamp here, so we don't fabricate one (see TableDetails model).
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"catalog table detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}/preview",
            dependencies=[Depends(require_permission("query:run"))])
async def preview_table(namespace: str, table: str, catalog: Optional[str] = None,
                        limit: int = 100, db: Session = Depends(get_db),
                        user: dict = Depends(require_user)):
    """Return top N rows and per-column statistics (null rate, distinct count, min, max).

    The rows come from the governed query path — the same table resolution, RLS,
    column masks, PII guardrail and tool-call audit as `/queries/execute` — because a
    preview is a query. It used to read the table directly, which returned raw rows to
    any caller holding the catalog capability. Statistics are computed on what that
    path returned, so they describe the masked values the caller may see.
    """
    _bare(namespace, table)
    limit = max(1, min(int(limit), PREVIEW_MAX_ROWS))
    request = QueryExecuteRequest(
        query=f"SELECT * FROM {namespace}.{table} LIMIT {limit}",
        save_history=False, origin="ui")
    result = await execute_query(request, db, user)
    try:
        cols = list(result.columns)
        rows = [dict(zip(cols, row)) for row in result.rows]
        # Serialise non-JSON-safe types
        for row in rows:
            for k, v in row.items():
                if v is None:
                    continue
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    row[k] = None

        # Column statistics (null rate, distinct count, min, max)
        stats = []
        total = len(rows)
        for col in cols:
            values = [r[col] for r in rows if r[col] is not None]
            null_count = total - len(values)
            null_rate = round(null_count / total * 100, 1) if total > 0 else 0.0
            distinct = len(set(str(v) for v in values))
            min_val = None
            max_val = None
            try:
                if values:
                    min_val = str(min(values))
                    max_val = str(max(values))
            except TypeError:
                pass
            stats.append({
                "column": col,
                "null_rate": null_rate,
                "null_count": null_count,
                "distinct_count": distinct,
                "min": min_val,
                "max": max_val,
            })

        return {
            "columns": cols,
            "rows": rows,
            "total_returned": len(rows),
            "column_stats": stats,
        }
    except Exception as e:
        logger.error(f"catalog preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/health")
async def catalog_health():
    try:
        # Reachability check against the active catalog backend (Glue or Polaris).
        get_catalog_reader().list_namespaces()
        return {"status": "healthy", "catalogs": [get_engine().default_catalog]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


