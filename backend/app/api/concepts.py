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
    from app.semantic import om_glossary
    return {"can_approve": _is_admin(user), "can_propose": _can_author(user),
            "openmetadata": om_glossary.enabled()}


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


@router.get("/semantic/concepts/pii-gaps",
            dependencies=[Depends(require_permission("governance:read"))])
async def pii_gaps(user: dict = Depends(require_user)):
    """Columns bound to a PII concept with no enabled column mask: suggestions for
    Governance › Access policies, never applied here."""
    _require_enabled()
    from app.rls import loader as rls_loader
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    gaps = concepts.pii_gaps(await load_concepts(pool),
                             await concept_store.list_bindings(pool, ("approved",)),
                             await rls_loader.load_masks(), catalog_registry.canonical_catalog)
    return {"gaps": [g for g in gaps if access.allows_sql_catalog(g["catalog"])]}


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


class GlossaryImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The JSON OpenMetadata's API returns ({"data": [...]} or a list) or the CSV its
    # Glossary › Export writes. Absent: pull from the add-on running on this deployment.
    glossary: Optional[object] = None


def _known_engine(name: str) -> Optional[str]:
    try:
        return catalog_registry.resolve(name).engine_catalog
    except Exception:
        return None


@router.post("/semantic/concepts/import/openmetadata")
async def import_openmetadata(body: GlossaryImport, admin: dict = Depends(require_admin)):
    """Concepts from an OpenMetadata glossary (app/semantic/om_glossary.py). A pull also
    proposes bindings for columns tagged with a glossary term; none is approved here."""
    _require_enabled()
    from app.semantic import om_glossary
    pool = await _pool()
    tables: list = []
    if body.glossary is None:
        if not om_glossary.enabled():
            raise HTTPException(409, "OpenMetadata does not run on this deployment. Upload "
                                     "a glossary export (JSON or CSV) instead.")
        try:
            raw, tables = await om_glossary.pull()
        except Exception as e:
            logger.warning("[concepts] OpenMetadata pull failed: %s", e)
            raise HTTPException(502, f"Could not read the OpenMetadata glossary: {e}")
    else:
        raw = body.glossary
    if not isinstance(raw, (str, list, dict)):
        _bad("glossary", "Send the glossary as JSON or as the CSV text of an export.")
    terms = om_glossary.parse_terms(raw)
    if not terms:
        _bad("glossary", "No glossary terms found in what was sent.")
    saved = await om_glossary.save_concepts(pool, om_glossary.to_concepts(terms))
    proposed = 0
    if tables:
        access = await catalog_access.for_caller(admin)
        found = om_glossary.proposals_from_tables(tables, om_glossary.term_index(terms), _known_engine)
        fresh = om_glossary.new_proposals(found, await concept_store.list_bindings(pool))
        for p in fresh:
            if not access.allows_sql_catalog(p["catalog"]):
                continue
            cid = await concept_store.concept_id(pool, p["concept"])
            if not cid:
                continue
            await concept_store.upsert_binding(
                pool, concept_id=cid, catalog=p["catalog"], namespace=p["namespace"],
                table=p["table"], column=p["column"], role=p["role"], filter_sql=None,
                status="proposed", source=om_glossary.SOURCE, evidence=p["evidence"][:500],
                actor_id=admin.get("id"), actor_name="OpenMetadata import")
            proposed += 1
    await _audit(admin, "POST", "/api/semantic/concepts/import/openmetadata",
                 f"glossary import: {len(terms)} terms, {len(saved['created'])} concepts created, "
                 f"{saved['terms_added']} words added, {proposed} bindings proposed")
    return {"terms_read": len(terms), **saved, "bindings_proposed": proposed,
            "source": "upload" if body.glossary is not None else "openmetadata"}


@router.get("/semantic/concepts/feedback",
            dependencies=[Depends(require_permission("governance:read"))])
async def concept_feedback(days: int = 30, user: dict = Depends(require_user)):
    """Suggestions from /ai/sql use (app/semantic/concept_feedback.py): words no concept
    covers, joins between keys of different concepts, and condition values no segment
    states. Governance readers only: the rows hold other people's questions (masked)."""
    _require_enabled()
    from app.semantic import concept_feedback as fb
    days = max(1, min(int(days), 90))
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    rows = fb.visible_rows(await fb.load(pool, days),
                           lambda t: access.allows_sql_catalog(t.split(".", 1)[0]))
    try:
        from app.semantic import context as metric_context
        metrics = await metric_context.for_caller(user)
    except Exception:
        metrics = []
    out = fb.suggest(rows, await load_concepts(pool),
                     await concept_store.list_bindings(pool, ("approved",)), metrics)
    return dict(out, days=days, concept_use=dict(fb.counts(rows)))


class TermBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=2, max_length=100)


@router.post("/semantic/concepts/{name}/terms", status_code=201)
async def add_term(name: str, body: TermBody,
                   user: dict = Depends(require_permission("knowledge:write"))):
    """Add one word to a concept, leaving its parent, PII flag and description as they
    are (POST /ai/concepts replaces those). Used for an alias suggested by feedback."""
    _require_enabled()
    pool = await _pool()
    cid = await concept_store.concept_id(pool, name)
    if not cid:
        raise HTTPException(404, f"Unknown concept {name!r}.")
    term = body.term.strip()
    async with pool.acquire() as c:
        tag = await c.execute("INSERT INTO concept_terms (concept_id, term) VALUES ($1, $2) "
                              "ON CONFLICT DO NOTHING", cid, term)
    added = tag.endswith(" 1")
    if added:
        await _audit(user, "POST", f"/api/semantic/concepts/{name}/terms", f"concept {name}: term {term!r} added")
    return {"concept": name, "term": term, "added": added}
