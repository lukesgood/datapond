"""
Data Catalog API — reads from Trino iceberg catalog directly.
Polaris stores metadata, Trino exposes it via INFORMATION_SCHEMA.
"""
import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

import trino
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

TRINO_HOST    = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT    = int(os.getenv("TRINO_SERVICE_PORT", "8080"))
TRINO_CATALOG = "iceberg"

# Tables to hide from catalog (internal DataPond bookkeeping)
HIDDEN_TABLES = {
    "_test_datapond", "_writer_test", "t1",
    "connector_connections", "connector_credentials_audit",
    "connector_sync_jobs", "connector_sync_history",
    "query_history", "dashboards", "pipelines", "users",
}


def _trino():
    return trino.dbapi.connect(
        host=TRINO_HOST, port=TRINO_PORT,
        user="datapond", catalog=TRINO_CATALOG,
        http_scheme="http", request_timeout=15,
    )


# ── Models ─────────────────────────────────────────────────────────────────────

class NamespaceInfo(BaseModel):
    name: str
    properties: Dict[str, Any] = {}

class NamespacesResponse(BaseModel):
    namespaces: List[NamespaceInfo]

class TableInfo(BaseModel):
    name: str
    namespace: str
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _user_schema(schema: str) -> bool:
    """Only show user-visible schemas."""
    return schema not in ("information_schema", "system")

def _user_table(schema: str, table: str) -> bool:
    """Filter internal bookkeeping tables from default schema."""
    if schema == "default" and table in HIDDEN_TABLES:
        return False
    return True


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/catalog/namespaces", response_model=NamespacesResponse)
async def list_namespaces():
    """List Iceberg schemas from Trino."""
    try:
        cur = _trino().cursor()
        cur.execute(f"SHOW SCHEMAS FROM {TRINO_CATALOG}")
        schemas = [row[0] for row in cur.fetchall() if _user_schema(row[0])]
        return NamespacesResponse(namespaces=[
            NamespaceInfo(name=s, properties={"description": f"{s} namespace"})
            for s in schemas
        ])
    except Exception as e:
        logger.error(f"catalog namespaces error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables", response_model=TablesResponse)
async def list_tables():
    """List all user-visible Iceberg tables across all schemas."""
    try:
        cur = _trino().cursor()
        # Get all schemas first
        cur.execute(f"SHOW SCHEMAS FROM {TRINO_CATALOG}")
        schemas = [row[0] for row in cur.fetchall() if _user_schema(row[0])]

        tables = []
        for schema in schemas:
            try:
                cur2 = _trino().cursor()
                cur2.execute(
                    f"SELECT table_name FROM {TRINO_CATALOG}.information_schema.tables "
                    f"WHERE table_schema='{schema}' AND table_type='BASE TABLE'"
                )
                for row in cur2.fetchall():
                    tbl = row[0]
                    if _user_table(schema, tbl):
                        tables.append(TableInfo(
                            name=tbl,
                            namespace=schema,
                            table_type="iceberg",
                        ))
            except Exception:
                continue

        return TablesResponse(tables=tables)
    except Exception as e:
        logger.error(f"catalog tables error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}", response_model=TableDetails)
async def get_table_details(namespace: str, table: str):
    """Get table schema, properties, and row count from Trino."""
    try:
        cur = _trino().cursor()

        # Columns
        cur.execute(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM {TRINO_CATALOG}.information_schema.columns "
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
            cur2 = _trino().cursor()
            cur2.execute(f"SELECT COUNT(*) FROM {TRINO_CATALOG}.{namespace}.{table}")
            row_count = cur2.fetchone()[0]
        except Exception:
            pass

        # Table properties (location, format)
        props: Dict[str, Any] = {}
        try:
            cur3 = _trino().cursor()
            cur3.execute(f"SHOW CREATE TABLE {TRINO_CATALOG}.{namespace}.{table}")
            ddl = cur3.fetchone()[0]
            if "location" in ddl.lower():
                import re
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


@router.get("/catalog/health")
async def catalog_health():
    try:
        cur = _trino().cursor()
        cur.execute(f"SHOW SCHEMAS FROM {TRINO_CATALOG}")
        schemas = [r[0] for r in cur.fetchall()]
        return {"status": "healthy", "catalog": TRINO_CATALOG, "schemas": schemas}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/catalog/schemas", response_model=CatalogTree)
async def get_catalog_tree():
    """Used by Query Lab schema browser."""
    try:
        cur = _trino().cursor()
        cur.execute("SHOW CATALOGS")
        catalogs_raw = [r[0] for r in cur.fetchall()]

        catalogs = []
        for cat in catalogs_raw:
            try:
                cur2 = _trino().cursor()
                cur2.execute(f"SHOW SCHEMAS FROM {cat}")
                schemas = []
                for (schema,) in cur2.fetchall():
                    if not _user_schema(schema):
                        continue
                    try:
                        cur3 = _trino().cursor()
                        cur3.execute(
                            f"SELECT table_name FROM {cat}.information_schema.tables "
                            f"WHERE table_schema='{schema}' AND table_type='BASE TABLE'"
                        )
                        tbls = [r[0] for r in cur3.fetchall()
                                if _user_table(schema, r[0])]
                        schemas.append({"name": schema, "tables": tbls})
                    except Exception:
                        schemas.append({"name": schema, "tables": []})
                catalogs.append({"name": cat, "schemas": schemas})
            except Exception:
                catalogs.append({"name": cat, "schemas": []})

        return CatalogTree(catalogs=catalogs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
