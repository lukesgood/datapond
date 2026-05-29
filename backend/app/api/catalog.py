"""
Data Catalog API — reads from Polaris (governance gate) + Trino for details.
Only data registered in Polaris is visible.
"""
import os
import logging
import re
import math
from typing import List, Optional, Dict, Any
from datetime import datetime

import trino
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.polaris_client import list_catalogs, list_namespaces, list_tables, get_catalog_type

router = APIRouter()
logger = logging.getLogger(__name__)

TRINO_HOST    = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT    = int(os.getenv("TRINO_SERVICE_PORT", "8080"))


def _trino(catalog: str = "iceberg"):
    return trino.dbapi.connect(
        host=TRINO_HOST, port=TRINO_PORT,
        user="datapond", catalog=catalog,
        http_scheme="http", request_timeout=15,
    )


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
    """List namespaces across all Polaris-registered catalogs."""
    try:
        polaris_cats = list_catalogs()
        namespaces = []
        for pcat in polaris_cats:
            cat_name = pcat["name"]
            cat_type = get_catalog_type(pcat)
            try:
                for ns in list_namespaces(cat_name):
                    namespaces.append(NamespaceInfo(
                        name=ns, catalog=cat_name, catalog_type=cat_type,
                    ))
            except Exception:
                continue
        return NamespacesResponse(namespaces=namespaces)
    except Exception as e:
        logger.error(f"catalog namespaces error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables", response_model=TablesResponse)
async def list_all_tables():
    """List all tables across all Polaris-registered catalogs."""
    try:
        polaris_cats = list_catalogs()
        tables = []
        for pcat in polaris_cats:
            cat_name = pcat["name"]
            cat_type = get_catalog_type(pcat)
            try:
                for ns in list_namespaces(cat_name):
                    try:
                        for tbl in list_tables(cat_name, ns):
                            tables.append(TableInfo(
                                name=tbl, namespace=ns,
                                catalog=cat_name, catalog_type=cat_type,
                            ))
                    except Exception:
                        continue
            except Exception:
                continue
        return TablesResponse(tables=tables)
    except Exception as e:
        logger.error(f"catalog tables error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}", response_model=TableDetails)
async def get_table_details(namespace: str, table: str, catalog: str = "iceberg"):
    """Get table schema, properties, and row count from Trino."""
    try:
        cur = _trino(catalog).cursor()

        # Columns
        cur.execute(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM {catalog}.information_schema.columns "
            f"WHERE table_schema='{namespace}' AND table_name='{table}' "
            f"ORDER BY ordinal_position"
        )
        columns = [
            TableColumn(name=r[0], type=r[1], nullable=(r[2].upper() == "YES"))
            for r in cur.fetchall()
        ]

        if not columns:
            raise HTTPException(status_code=404, detail=f"Table {namespace}.{table} not found")

        # Row count
        row_count = None
        try:
            cur2 = _trino(catalog).cursor()
            cur2.execute(f"SELECT COUNT(*) FROM {catalog}.{namespace}.{table}")
            row_count = cur2.fetchone()[0]
        except Exception:
            pass

        # Table properties (location, format)
        props: Dict[str, Any] = {}
        try:
            cur3 = _trino(catalog).cursor()
            cur3.execute(f"SHOW CREATE TABLE {catalog}.{namespace}.{table}")
            ddl = cur3.fetchone()[0]
            if "location" in ddl.lower():
                m = re.search(r"location\s*=\s*'([^']+)'", ddl, re.IGNORECASE)
                if m:
                    props["location"] = m.group(1)
        except Exception:
            pass

        return TableDetails(
            name=table,
            namespace=namespace,
            table_type="iceberg",
            location=props.get("location"),
            columns=columns,
            properties=props,
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
        fqtn = f"{catalog}.{namespace}.{table}"

        # Sample rows
        cur = _trino(catalog).cursor()
        cur.execute(f"SELECT * FROM {fqtn} LIMIT {min(limit, 500)}")
        rows_raw = cur.fetchall()
        cols = [d[0] for d in cur.description]

        rows = [dict(zip(cols, row)) for row in rows_raw]
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
        cats = list_catalogs()
        return {"status": "healthy", "catalogs": [c["name"] for c in cats]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


