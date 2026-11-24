"""
Data Catalog API — reads from Polaris (governance gate) + Trino for details.
Only data registered in Polaris is visible.
"""
import logging
import math
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
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




@router.get("/catalog/tables/{namespace}/{table}/keys",
            dependencies=[Depends(require_permission("catalog:read"))])
async def table_keys(namespace: str, table: str, catalog: Optional[str] = None,
                     user: dict = Depends(require_user)):
    """Primary and foreign keys the source database declares for this table, or for the
    source table it is synced from (app/source_keys.py). Tables in catalogs the caller
    may not use are left out of `referenced_by`."""
    import asyncio
    from app import source_keys
    _bare(namespace, table)
    access = await catalog_access.for_caller(user)
    entry = _entry(catalog, access)
    try:
        keys = await asyncio.wait_for(source_keys.all_keys(), timeout=20)
    except Exception as e:
        logger.info("[catalog] keys unavailable: %s", e)
        keys = []
    out = source_keys.for_table(keys, f"{entry.engine_catalog}.{namespace}.{table}")
    ok = lambda t: access.allows_sql_catalog(t.split(".", 1)[0])
    out["foreign"] = [f for f in out["foreign"] if ok(f["ref_table"])]
    out["referenced_by"] = [r for r in out["referenced_by"] if ok(r["table"])]
    return out


@router.get("/catalog/tables/{namespace}/{table}/profile",
            dependencies=[Depends(require_permission("catalog:read"))])
async def table_profile(namespace: str, table: str, catalog: Optional[str] = None,
                        user: dict = Depends(require_user)):
    """Whole-table profile from the table's statistics, no scan (app/table_profile.py):
    rows, per-column nulls / distinct / range, and Iceberg snapshots. Under a row policy
    the table-wide figures are withheld; masked and PII-bound columns show no range."""
    import asyncio
    from app import table_profile as tp
    _bare(namespace, table)
    entry = _entry(catalog, await catalog_access.for_caller(user))
    cat = entry.engine_catalog
    try:
        gov = await tp.governance(user, cat, namespace, table)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Not readable for you: {e}")
    try:
        prof = await asyncio.wait_for(asyncio.to_thread(
            tp.read, cat, namespace, table, entry.kind != "trino_source"), timeout=30)
    except Exception as e:
        logger.info("[catalog] profile of %s.%s.%s failed: %s", cat, namespace, table, e)
        raise HTTPException(status_code=502, detail="Statistics could not be read for this table.")
    if gov["restricted"]:
        return {"restricted": True, "rows": None, "snapshots": [],
                "columns": [{"name": c["name"]} for c in prof["columns"]],
                "note": "Row policies limit what you see in this table, so table-wide figures are not shown."}
    hidden = gov["masked"] | await tp.pii_columns(cat, namespace, table)
    return dict(tp.redact(prof, hidden), restricted=False)


@router.get("/catalog/search", dependencies=[Depends(require_permission("catalog:read"))])
async def catalog_search(q: str = "", user: dict = Depends(require_user)):
    """Find tables by table name, column name or business word (app/catalog_search.py).

    A business word is a concept name or alias; its approved bindings bring the columns
    that hold it and its segments. Metrics match by name, label and synonyms. Only the
    catalogs this caller may use are searched; nothing here reads a row."""
    import asyncio
    from app import catalog_search
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="Search for at most 200 characters.")
    access = await catalog_access.for_caller(user)
    cats = [e.engine_catalog for e in access.entries()]
    try:
        index = await asyncio.wait_for(
            asyncio.to_thread(catalog_search.column_index, cats), timeout=45)
    except Exception as e:
        logger.warning("[catalog] search index unavailable: %s", e)
        index = {}
    concepts, bindings, metrics = [], [], []
    try:
        from app.api.connectors import get_db_pool
        from app.api.ontology import load_concepts, ontology_enabled
        from app.semantic import concept_store
        if ontology_enabled():
            pool = await get_db_pool()
            concepts = await load_concepts(pool)
            bindings = await concept_store.list_bindings(pool, ("approved",))
    except Exception as e:
        logger.info("[catalog] concepts unavailable for search: %s", e)
    try:
        from app.semantic import context
        metrics = await context.for_caller(user)
    except Exception as e:
        logger.info("[catalog] metrics unavailable for search: %s", e)
    return catalog_search.search(q, index, concepts, bindings, metrics,
                                 access.allows_sql_catalog)


@router.get("/catalog/tables/{namespace}/{table}/columns/{column}/values",
            dependencies=[Depends(require_permission("query:run"))])
async def column_values(namespace: str, table: str, column: str, catalog: Optional[str] = None,
                        db: Session = Depends(get_db), user: dict = Depends(require_user)):
    """One column's top values by rows, its empty share and a distinct estimate, for the
    Data Map's column drill-down (app/column_values.py).

    Read through the governed query path as the caller — grants, row policies, masks,
    the PII guardrail and the tool-call audit apply, so the figures describe the rows
    and values the caller may see. A column masked for the caller, or bound to a PII
    concept, returns counts only (`hidden`)."""
    import asyncio
    from app import column_values as cv
    from app import table_profile as tp
    _bare(namespace, table)
    entry = _entry(catalog, await catalog_access.for_caller(user))
    cat = entry.engine_catalog
    try:
        cols = await asyncio.to_thread(get_catalog_reader(entry.name).get_columns, namespace, table)
    except Exception as e:
        logger.info("[catalog] columns of %s.%s.%s unreadable: %s", cat, namespace, table, e)
        raise HTTPException(status_code=404, detail=f"{namespace}.{table} could not be read.")
    col = cv.find_column(cols, column)
    if col is None:
        raise HTTPException(status_code=404, detail=f"{namespace}.{table} has no column {column!r}.")
    name, typ = col["name"], str(col.get("type") or "")
    try:
        gov = await tp.governance(user, cat, namespace, table)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Not readable for you: {e}")
    hidden_reason = None
    if name.lower() in gov["masked"]:
        hidden_reason = "A column mask hides this column's values from you."
    elif name.lower() in {c.lower() for c in await tp.pii_columns(cat, namespace, table)}:
        hidden_reason = "This column is bound to a PII concept, so its values are not listed."
    elif not cv.listable(typ):
        hidden_reason = f"Values of {typ or 'this type'} are not listed."
    target = (f"{namespace}.{table}" if entry.is_default
              else f"{safe_identifier(cat)}.{namespace}.{table}")

    async def run(sql: str):
        res = await execute_query(QueryExecuteRequest(query=sql, save_history=False, origin="ui"), db, user)
        return [dict(zip(list(res.columns), r)) for r in res.rows]

    try:
        if hidden_reason:
            counts = (await run(cv.counts_only(target, name)))[0]
            values = []
        else:
            counts_sql, top_sql = cv.statements(target, name)
            counts = (await run(counts_sql))[0]
            values = [{"value": None if r["value"] is None else str(r["value"]), "rows": int(r["n"])}
                      for r in await run(top_sql)]
    except HTTPException:
        raise
    except Exception as e:
        logger.info("[catalog] values of %s.%s.%s.%s failed: %s", cat, namespace, table, name, e)
        raise HTTPException(status_code=502, detail="The column's values could not be read.")
    total = int(counts.get("total") or 0)
    non_null = int(counts.get("non_null") or 0)
    return {"column": name, "type": typ, "rows": total,
            "nulls": total - non_null, "null_fraction": (total - non_null) / total if total else None,
            "distinct": counts.get("distinct_est"),
            "values": values, "hidden": bool(hidden_reason), "reason": hidden_reason,
            "restricted": bool(gov["restricted"]), "top": cv.TOP}


def _holds(user: dict, permission: str) -> bool:
    """Whether the caller holds `permission`, decided as require_permission decides it
    (a key's scopes when present, else the role) but without a refusal or audit row:
    used to leave optional detail out, not to refuse."""
    from app.permissions import has_permission
    granted = user.get("permissions")
    return (permission in granted) if granted is not None else has_permission(user.get("role"), permission)


IMPACT_DAYS = 30


@router.get("/catalog/impact", dependencies=[Depends(require_permission("catalog:read"))])
async def table_impact(table: List[str] = Query(default=[]), user: dict = Depends(require_user)):
    """What depends on each table (app/table_impact.py): governed metrics built on it,
    concepts bound to its columns, saved dashboards whose query reads it, and how often it
    was queried in the last 30 days (the tool-call log).

    `table` is `catalog.namespace.table`, repeated, at most 12. Tables in catalogs the
    caller may not use are left out. Metrics and dashboards are the ones the caller can
    see; who queried is named only for a governance reader, the counts for everyone who
    may see the table. Nothing here reads a row of the table itself."""
    from app import table_impact as ti
    from app.api.connectors import get_db_pool
    from app.tool_call_log import table_names
    if len(table) > ti.MAX_TABLES:
        raise HTTPException(status_code=400, detail=f"Ask for at most {ti.MAX_TABLES} tables.")
    access = await catalog_access.for_caller(user)
    canonical = catalog_registry.canonical_catalog
    wanted = [t for t in table
              if (tid := ti.table_id(t, canonical)) and access.allows_sql_catalog(tid.split(".", 1)[0])]
    if not wanted:
        return {"tables": {}, "days": IMPACT_DAYS}
    pool = await get_db_pool()

    metrics: list = []
    try:
        from app.semantic import context
        metrics = await context.for_caller(user)
    except Exception as e:
        logger.info("[catalog] metrics unavailable for impact: %s", e)

    bindings: list = []
    try:
        from app.api.ontology import ontology_enabled
        from app.semantic import concept_store
        if ontology_enabled():
            bindings = await concept_store.list_bindings(pool, ("approved",))
    except Exception as e:
        logger.info("[catalog] concepts unavailable for impact: %s", e)

    dashboards: list = []
    try:
        async with pool.acquire() as c:
            if user.get("role") == "admin":
                rows = await c.fetch("SELECT id, name, query_text FROM dashboards")
            else:
                rows = await c.fetch("SELECT id, name, query_text FROM dashboards "
                                     "WHERE user_id::text = $1 OR is_public", str(user.get("id") or ""))
        dashboards = [{"id": str(r["id"]), "name": r["name"], "tables": table_names(r["query_text"] or "")}
                      for r in rows]
    except Exception as e:
        logger.info("[catalog] dashboards unavailable for impact: %s", e)

    calls: list = []
    try:
        async with pool.acquire() as c:
            rows = await c.fetch(
                "SELECT t AS table, actor_username AS actor, actor_kind AS kind, count(*) AS n "
                "FROM tool_call_log, unnest(resource) AS t "
                "WHERE resource_kind = 'tables' AND outcome = 'ok' "
                "AND occurred_at > now() - make_interval(days => $1) "
                "GROUP BY 1, 2, 3", IMPACT_DAYS)
        calls = [dict(r) for r in rows]
    except Exception as e:
        logger.info("[catalog] tool-call counts unavailable for impact: %s", e)

    return {"tables": ti.impact(wanted, metrics=metrics, bindings=bindings, dashboards=dashboards,
                                calls=calls, canonical=canonical,
                                show_callers=_holds(user, "governance:read")),
            "days": IMPACT_DAYS}
