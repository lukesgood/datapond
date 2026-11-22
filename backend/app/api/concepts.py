"""Console routes for concept bindings (app/semantic/concepts.py, migration 0031).

Reading needs catalog:read and shows only bindings on catalogs the caller may use. A
signed-in administrator's binding is approved at once and an administrator approves,
rejects and retires; a person holding governance:write proposes. Keys and IdP tokens
never write: what a business word means is a person's decision, as with metrics.

Behind the ontology capability (FEATURE_ONTOLOGY), like the concept store itself.
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import catalog_access, catalog_registry, security_audit
from app.api.auth import require_admin, require_permission, require_user
from app.api.ontology import _require_enabled, load_concepts
from app.database.connection import get_db
from app.semantic import concept_store, concepts, store
from app.semantic.model import DefinitionError
from app.semantic.validate import validate_filters

logger = logging.getLogger(__name__)
router = APIRouter()


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


class BindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept: str
    catalog: str
    table: str                                   # namespace.table
    column: str
    role: str = Field(pattern="^(key|attribute|filter)$")
    filter_sql: Optional[str] = None
    source: str = Field(default="manual", pattern="^(naming|comment|history|manual|openmetadata)$")
    evidence: str = Field(default="", max_length=500)
    # An administrator may record a rejection instead (a suggestion they do not want
    # offered again). Anyone else's binding is a proposal whatever this says.
    status: str = Field(default="approved", pattern="^(approved|rejected)$")


def _bad(field: str, message: str, status: int = 422):
    raise HTTPException(status_code=status, detail={"field": field, "message": message})


def _viewer(user: dict) -> dict:
    from app.api.semantic import _can_author, _is_admin
    return {"can_approve": _is_admin(user), "can_propose": _can_author(user)}


async def _audit(user: dict, method: str, route: str, reason: str) -> None:
    await security_audit.record(actor=user, permission="admin", route=route, method=method,
                                outcome="allowed", reason=reason)


@router.get("/semantic/concepts", dependencies=[Depends(require_permission("catalog:read"))])
async def list_concepts_with_bindings(user: dict = Depends(require_user)):
    _require_enabled()
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    rows = await concept_store.list_bindings(pool, ("proposed", "approved"))
    return {"concepts": await load_concepts(pool),
            "bindings": [b for b in rows if access.allows_sql_catalog(b["catalog"])],
            "viewer": _viewer(user)}


@router.get("/semantic/concepts/table", dependencies=[Depends(require_permission("catalog:read"))])
async def concepts_of_table(catalog: str, namespace: str, table: str,
                            user: dict = Depends(require_user)):
    """{columns: {column: [{concept, role, filter_sql, pii}]}} for one table's approved
    bindings, for the Catalog's column chips. Empty, not 404, when concepts are off: the
    table page asks on every open and must not show an error for a feature not in use."""
    from app.semantic import concept_context
    try:
        found = await concept_context.for_caller(user)
    except Exception as e:
        logger.info("[concepts] table chips unavailable: %s", e)
        found = []
    canonical = catalog_registry.canonical_catalog(catalog) or catalog
    return {"columns": concept_context.for_table(found, canonical, namespace, table)}


@router.get("/semantic/concepts/proposals",
            dependencies=[Depends(require_permission("catalog:read"))])
async def binding_proposals(db: Session = Depends(get_db), user: dict = Depends(require_user)):
    """Suggestions from column names and from joins (query history and approved joins).
    Computed on request and never stored; approving or rejecting one stores it."""
    _require_enabled()
    from app.api.queries import _catalog_schema_for_graph, catalog_relationships
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    schema = {k: v for k, v in (await asyncio.to_thread(_catalog_schema_for_graph)).items()
              if access.allows_sql_catalog(k.split(".", 1)[0])}
    try:
        graph = await catalog_relationships(days=30, include_ai=False, db=db, user=user)
        edges = list(graph.get("edges") or [])
    except Exception as e:
        logger.warning("[concepts] relationship history unavailable: %s", e)
        edges = []
    joins = [j for j in await store.list_joins(pool) if access.allows(j["catalog"])]
    edges += concepts.approved_join_edges(joins, catalog_registry.canonical_catalog)
    found = concepts.propose(await load_concepts(pool), schema,
                             await concept_store.list_bindings(pool), edges)
    return {"proposals": [p for p in found if access.allows_sql_catalog(p["catalog"])],
            "tables_inspected": len(schema)}


@router.post("/semantic/concepts/bindings", status_code=201)
async def create_binding(body: BindingBody,
                         user: dict = Depends(require_permission("governance:write"))):
    _require_enabled()
    from app.api.query_engine import get_engine
    from app.api.semantic import _columns, _entry_for
    viewer = _viewer(user)
    if not (viewer["can_approve"] or viewer["can_propose"]):
        raise HTTPException(403, "Binding a concept needs a signed-in administrator, or "
                                 "governance:write to propose one.")
    status = body.status if viewer["can_approve"] else "proposed"
    pool = await _pool()
    cid = await concept_store.concept_id(pool, body.concept.strip())
    if not cid:
        _bad("concept", f"Unknown concept {body.concept!r}.")
    entry = await _entry_for(user, body.catalog)
    if body.table.count(".") != 1:
        _bad("table", "Use namespace.table.")
    namespace, table = (p.strip().lower() for p in body.table.split("."))
    column = body.column.strip().lower()
    filter_sql = (body.filter_sql or "").strip() or None
    if status != "rejected":
        cols = await asyncio.to_thread(_columns, entry, f"{namespace}.{table}")
        if cols is None:
            _bad("table", f"Cannot read the columns of {namespace}.{table}.")
        if column not in {c.lower() for c in cols}:
            _bad("column", f"{namespace}.{table} has no column {column!r}.")
        if body.role == "filter":
            if not filter_sql:
                _bad("filter_sql", "A segment needs its condition, e.g. tier = 'VIP'.")
            try:
                validate_filters(filter_sql, cols, get_engine().rls_dialect)
            except DefinitionError as e:
                _bad("filter_sql", str(e))
    if body.role != "filter" and filter_sql:
        _bad("filter_sql", "Only a segment (role filter) has a condition.")
    bid = await concept_store.upsert_binding(
        pool, concept_id=cid, catalog=entry.engine_catalog.lower(), namespace=namespace,
        table=table, column=column, role=body.role, filter_sql=filter_sql, status=status,
        source=body.source, evidence=body.evidence, actor_id=user.get("id"),
        actor_name=user.get("username"))
    if status != "proposed":
        await _audit(user, "POST", "/api/semantic/concepts/bindings",
                     f"concept {body.concept} -> {entry.engine_catalog}.{namespace}.{table}.{column} {status}")
    return {"id": bid, "status": status}


async def _decide(binding_id: int, admin: dict, from_status: str, to_status: str,
                  method: str, route: str):
    _require_enabled()
    pool = await _pool()
    b = await concept_store.get_binding(pool, binding_id)
    if not b:
        raise HTTPException(404, f"Unknown binding {binding_id}.")
    if not await concept_store.decide(pool, binding_id, from_status=from_status,
                                      to_status=to_status, actor_id=admin.get("id"),
                                      actor_name=admin.get("username")):
        raise HTTPException(409, f"Binding {binding_id} is {b['status']}, not {from_status}.")
    await _audit(admin, method, route,
                 f"concept {b['concept']} -> {b['catalog']}.{b['namespace']}.{b['table']}.{b['column']} {to_status}")
    return {"id": binding_id, "status": to_status}


@router.post("/semantic/concepts/bindings/{binding_id}/approve")
async def approve_binding(binding_id: int, admin: dict = Depends(require_admin)):
    return await _decide(binding_id, admin, "proposed", "approved", "POST",
                         f"/api/semantic/concepts/bindings/{binding_id}/approve")


@router.post("/semantic/concepts/bindings/{binding_id}/reject")
async def reject_binding(binding_id: int, admin: dict = Depends(require_admin)):
    return await _decide(binding_id, admin, "proposed", "rejected", "POST",
                         f"/api/semantic/concepts/bindings/{binding_id}/reject")


@router.delete("/semantic/concepts/bindings/{binding_id}")
async def retire_binding(binding_id: int, admin: dict = Depends(require_admin)):
    return await _decide(binding_id, admin, "approved", "retired", "DELETE",
                         f"/api/semantic/concepts/bindings/{binding_id}")
