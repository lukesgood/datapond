"""
Data Catalog API — reads from Polaris (governance gate) + Trino for details.
Only data registered in Polaris is visible.
"""
import logging
import math
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.catalog_backend import get_catalog_reader

router = APIRouter()
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
        tables = []
        for ns in reader.list_namespaces():
            try:
                for tbl in reader.list_tables(ns):
                    tables.append(TableInfo(name=tbl, namespace=ns))
            except Exception:
                continue
        return TablesResponse(tables=tables)
    except Exception as e:
        logger.error(f"catalog tables error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}", response_model=TableDetails)
async def get_table_details(namespace: str, table: str, catalog: str = "iceberg"):
    """Get table schema, location, and row count from the active catalog backend."""
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
            last_updated=datetime.utcnow().isoformat() + "Z",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"catalog table detail error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}/preview")
async def preview_table(namespace: str, table: str, catalog: str = "iceberg", limit: int = 100):
    """Return top N rows and per-column statistics (null rate, distinct count, min, max)."""
    try:
        # Sample rows via the active catalog backend (Glue → pyiceberg scan; Polaris → Trino)
        preview = get_catalog_reader().preview(namespace, table, limit)
        cols = preview["columns"]
        rows = [dict(zip(cols, row)) for row in preview["rows"]]
        # Serialise non-JSON-safe types
        import math
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
        return {"status": "healthy", "catalogs": ["iceberg"]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


