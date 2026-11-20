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

from app import catalog_access, catalog_registry
from app.api.auth import require_permission, require_user
from app.api.catalog_backend import get_catalog_reader, safe_identifier
from app.api.queries import execute_query
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


def _entry(catalog: Optional[str], access):
    """The registry entry a route was asked about; an unknown one is the caller's
    error, never a silent fall back to the default.

    404, and the same 404 for a catalog this caller may not use (app/catalog_access.py)
    as for one that does not exist: a detail route must not confirm that a hidden
    catalog is there. The "known catalogs" list names only the caller's."""
    try:
        return access.resolve(catalog)
    except catalog_registry.UnknownCatalog as e:
        raise HTTPException(status_code=404, detail=str(e))


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
    # What the table is, for the browser: a read-only mirror of another catalog's table
    # ("catalog.schema.table"), the source connection that syncs it, and whether it is
    # a live source database table (read through the engine, not copied).
    mirror_of: Optional[str] = None
    synced_from: Optional[Dict[str, Any]] = None
    live: bool = False

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
    catalog: Optional[str] = None
    table_type: str = "iceberg"
    location: Optional[str] = None
    columns: List[TableColumn] = []
    properties: Dict[str, Any] = {}
    snapshot_id: Optional[str] = None
    row_count: Optional[int] = None
    last_updated: Optional[str] = None
    mirror_of: Optional[str] = None
    synced_from: Optional[Dict[str, Any]] = None
    live: bool = False

class CatalogTree(BaseModel):
    catalogs: List[Dict[str, Any]] = []



# ── Endpoints ──────────────────────────────────────────────────────────────────

def _readers(access):
    """(entry, reader) for every enabled catalog this caller may use. With one catalog
    this is exactly the one reader the routes used before; a catalog that has no
    reader is skipped."""
    out = []
    for entry in access.entries():
        try:
            out.append((entry, get_catalog_reader(entry.name)))
        except Exception as e:
            logger.warning("catalog %s has no reader: %s", entry.name, e)
    return out


def _label(entry) -> str:
    """The catalog name to show and to write into SQL: the engine's name for it
    (`iceberg` by default; a pre-2.4 glue row keeps its registry name AwsDataCatalog
    but its engine_catalog is `iceberg`). Printing any other name for the default
    printed a name the engine would reject."""
    return entry.engine_catalog


@router.get("/catalog/namespaces", response_model=NamespacesResponse)
async def list_all_namespaces(user: dict = Depends(require_user)):
    """List namespaces of every enabled catalog the caller may use, each labelled with
    its catalog."""
    access = await catalog_access.for_caller(user)
    try:
        out, errors, readers = [], [], _readers(access)
        for entry, reader in readers:
            try:
                out.extend(NamespaceInfo(name=n, catalog=_label(entry))
                           for n in reader.list_namespaces())
            except Exception as e:
                errors.append(e)
        if errors and len(errors) == len(readers):
            raise errors[0]
        return NamespacesResponse(namespaces=out)
    except Exception as e:
        logger.error(f"catalog namespaces error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _utc_iso(ts) -> str:
    """Sync times are stored naive in UTC; say so, or a browser reads them as local."""
    from datetime import timezone
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).isoformat()


async def _table_facts():
    """Mirror links and, per lake table, the sync that writes it — both advisory: a
    failure (or a database before migrations 0028/0024) leaves the list as names only."""
    from app import sync_targets, table_links
    from app.api.connectors import get_db_pool
    links, synced = None, {}
    try:
        pool = await get_db_pool()
        links = await table_links.load(pool)
        default = catalog_registry.default_entry().engine_catalog
        async with pool.acquire() as c:
            rows = await c.fetch(
                """SELECT j.connection_id, cn.name, j.source_table, j.target_table, j.target_catalog,
                          j.last_run_at, j.rows_synced, j.last_run_status
                     FROM connector_sync_jobs j JOIN connector_connections cn ON cn.id = j.connection_id
                    WHERE j.enabled AND j.last_run_at IS NOT NULL""")
        for r in rows:
            ns, tbl = sync_targets.lake_table(r["source_table"], r["target_table"])
            key = ((r["target_catalog"] or default).lower(), ns.lower(), tbl.lower())
            prev = synced.get(key)
            if prev and prev["last_run_at"] >= _utc_iso(r["last_run_at"]):
                continue
            synced[key] = {"connection_id": str(r["connection_id"]), "connection": r["name"],
                           "last_run_at": _utc_iso(r["last_run_at"]), "rows": r["rows_synced"],
                           "status": r["last_run_status"]}
    except Exception as e:
        logger.info("catalog list: table facts unavailable: %s", e)
    return links, synced


@router.get("/catalog/tables", response_model=TablesResponse)
async def list_all_tables(user: dict = Depends(require_user)):
    """List all tables of every enabled catalog the caller may use, each labelled with
    its catalog."""
    access = await catalog_access.for_caller(user)
    try:
        tables, errors, readers = [], [], _readers(access)
        links, synced = await _table_facts()
        for entry, reader in readers:
            try:
                namespaces = reader.list_namespaces()
            except Exception as e:
                errors.append(e)
                continue
            live = entry.kind == "trino_source"
            for ns in namespaces:
                try:
                    for tbl in reader.list_tables(ns):
                        cat = _label(entry)
                        key = (cat.lower(), str(ns).lower(), str(tbl).lower())
                        owner = links.owner_of(key) if links else None
                        tables.append(TableInfo(
                            name=tbl, namespace=ns, catalog=cat, live=live,
                            table_type="source" if live else "iceberg",
                            mirror_of=".".join(owner) if owner else None,
                            synced_from=synced.get(key)))
                except Exception:
                    continue
        if errors and len(errors) == len(readers):
            raise errors[0]
        return TablesResponse(tables=tables)
    except Exception as e:
        logger.error(f"catalog tables error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/tables/{namespace}/{table}", response_model=TableDetails)
async def get_table_details(namespace: str, table: str, catalog: Optional[str] = None,
                            user: dict = Depends(require_user)):
    """Get table schema, location, and row count from the catalog asked for (default
    when omitted)."""
    _bare(namespace, table)
    entry = _entry(catalog, await catalog_access.for_caller(user))
    try:
        reader = get_catalog_reader(entry.name)
        columns = [TableColumn(**c) for c in reader.get_columns(namespace, table)]
        if not columns:
            raise HTTPException(status_code=404, detail=f"Table {namespace}.{table} not found")
        location = reader.get_location(namespace, table)
        row_count = reader.row_count(namespace, table)
        links, synced = await _table_facts()
        key = (_label(entry).lower(), namespace.lower(), table.lower())
        owner = links.owner_of(key) if links else None
        live = entry.kind == "trino_source"
        return TableDetails(
            name=table,
            namespace=namespace,
            catalog=_label(entry),
            table_type="source" if live else "iceberg",
            live=live,
            mirror_of=".".join(owner) if owner else None,
            synced_from=synced.get(key),
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
    entry = _entry(catalog, await catalog_access.for_caller(user))
    limit = max(1, min(int(limit), PREVIEW_MAX_ROWS))
    # Two parts for the default catalog — the engine's session catalog — exactly as
    # before; three for any other, or the preview would read the default's table.
    target = (f"{namespace}.{table}" if entry.is_default
              else f"{safe_identifier(entry.engine_catalog)}.{namespace}.{table}")
    request = QueryExecuteRequest(
        query=f"SELECT * FROM {target} LIMIT {limit}",
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
async def catalog_health(user: dict = Depends(require_user)):
    access = await catalog_access.for_caller(user)
    try:
        # Reachability check against the default catalog; the list names every one
        # this caller may use.
        get_catalog_reader().list_namespaces()
        return {"status": "healthy",
                "catalogs": [_label(e) for e in access.entries()]}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


