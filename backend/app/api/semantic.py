"""Console routes for metric definitions (docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md).

Reading needs catalog:read and follows catalog grants. Authoring — a new metric, a new
version, a preview of a draft — needs governance:write. Approving, retiring and
approving a join need a signed-in administrator: require_admin refuses keys and IdP
tokens, so no agent can change what a metric means. Agents never reach these routes;
they use the metric.* actions.
"""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import catalog_access, catalog_registry, security_audit
from app.api.auth import require_admin, require_permission, require_user
from app.semantic import service, store
from app.semantic.compile import compile_metric
from app.semantic.model import DefinitionError
from app.semantic.validate import check_name, validate_filters, validate_grains, validate_measure

logger = logging.getLogger(__name__)
router = APIRouter()


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


# ── bodies ───────────────────────────────────────────────────────────────────

class DimensionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    column: str
    join_id: Optional[int] = None


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog: str
    base_table: str
    measure: str
    filters: Optional[str] = None
    time_column: Optional[str] = None
    grains: List[str] = Field(default_factory=list)
    max_period_days: int = Field(default=366, ge=1, le=3660)
    dimensions: List[DimensionBody] = Field(default_factory=list)
    change_note: str = ""


class MetricCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    label: str
    description: str = ""
    synonyms: List[str] = Field(default_factory=list)
    version: VersionBody


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    by: List[str] = Field(default_factory=list)
    period: Optional[str] = None
    grain: Optional[str] = None
    where: List[dict] = Field(default_factory=list)
    order_by: List[dict] = Field(default_factory=list)
    limit: Optional[int] = None


class JoinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog: str
    from_table: str
    to_table: str
    on_columns: List[List[str]]
    source: str = Field(pattern="^(history|naming|manual)$")


# ── helpers ──────────────────────────────────────────────────────────────────

def _bad(field: str, message: str, status: int = 422, **extra):
    raise HTTPException(status_code=status, detail={"field": field, "message": message, **extra})


def _columns(entry, table: str) -> Optional[List[str]]:
    """Column names of schema.table in that catalog, or None if it cannot be read."""
    from app.api.catalog_backend import get_catalog_reader
    try:
        schema, name = table.split(".", 1)
        return [c["name"] for c in get_catalog_reader(entry.name).get_columns(schema, name)]
    except Exception as e:
        logger.info("[semantic] columns of %s unreadable: %s", table, e)
        return None


async def _entry_for(user: dict, catalog: str):
    access = await catalog_access.for_caller(user)
    try:
        return access.resolve(catalog)
    except catalog_registry.UnknownCatalog as e:
        _bad("catalog", str(e))


def _is_admin(user: dict) -> bool:
    from app.api.auth import is_delegated_credential
    return user.get("role") == "admin" and not is_delegated_credential(user)


def _can_author(user: dict) -> bool:
    from app.api.auth import is_delegated_credential
    from app.chat.authz import held_permissions
    return "governance:write" in held_permissions(user) and not is_delegated_credential(user)


def _require_person(user: dict) -> None:
    """Authoring is a person's act. A key or IdP token holding governance:write is still
    software, and software must not define what a number means."""
    from app.api.auth import is_delegated_credential
    if is_delegated_credential(user):
        raise HTTPException(403, "Metric definitions are written by a signed-in person, "
                                 "not by an API key or access token.")


async def _audit(user: dict, permission: str, route: str, reason: str) -> None:
    await security_audit.record(actor=user, permission=permission, route=route,
                                method="POST", outcome="allowed", reason=reason)


async def _checked_version(user: dict, body: VersionBody, metric_name: str) -> dict:
    """Validate a version body against the live table; return the row fields to store."""
    from app.api.query_engine import get_engine
    dialect = get_engine().rls_dialect
    entry = await _entry_for(user, body.catalog)
    if body.base_table.count(".") != 1:
        _bad("base_table", "Use schema.table.")
    cols = await asyncio.to_thread(_columns, entry, body.base_table)
    if cols is None:
        _bad("base_table", f"Cannot read the columns of {body.base_table} in {entry.name}.")
    try:
        validate_measure(body.measure, cols, dialect)
        validate_filters(body.filters, cols, dialect)
        grains = validate_grains(body.grains)
    except DefinitionError as e:
        _bad(e.field, str(e))
    lower = {c.lower() for c in cols}
    if body.time_column and body.time_column.lower() not in lower:
        _bad("time_column", f"Unknown column {body.time_column!r} on the base table.")
    if grains and not body.time_column:
        _bad("grains", "Grains need a time column.")
    pool = await _pool()
    dims, names, join_by_target = [], set(), {}
    for d in body.dimensions:
        try:
            check_name(d.name)
        except DefinitionError:
            _bad("dimensions", f"Dimension name {d.name!r}: lowercase letters, digits and _.")
        if d.name in names or d.name in grains:
            _bad("dimensions", f"Dimension {d.name!r} is defined twice.")
        if d.name == metric_name:
            _bad("dimensions", f"Dimension {d.name!r} has the metric's name; the output "
                               "column would collide.")
        names.add(d.name)
        if d.join_id is None:
            if d.column.lower() not in lower:
                _bad("dimensions", f"Unknown column {d.column!r} on the base table.")
            dims.append({"name": d.name, "column": d.column})
            continue
        j = await store.get_join(pool, d.join_id)
        if (not j or j["catalog"].lower() != entry.name.lower()
                or j["from_table"].lower() != body.base_table.lower()):
            _bad("dimensions", f"Dimension {d.name!r}: join {d.join_id} is not an approved join "
                               f"from {body.base_table}.")
        # The compiler shares one alias per to_table, so one table takes one join.
        if join_by_target.setdefault(j["to_table"].lower(), j["id"]) != j["id"]:
            _bad("dimensions", f"Dimension {d.name!r}: {j['to_table']} is already reached "
                               "through a different join.")
        target_cols = await asyncio.to_thread(_columns, entry, j["to_table"])
        if target_cols is None or d.column.lower() not in {c.lower() for c in target_cols}:
            _bad("dimensions", f"Unknown column {d.column!r} on {j['to_table']}.")
        dims.append({"name": d.name, "column": d.column,
                     "join": {"to_table": j["to_table"], "on": j["on_columns"]}})
    return {"catalog": entry.name, "base_table": body.base_table, "measure": body.measure,
            "filters": body.filters or None, "time_column": body.time_column or None,
            "grains": list(grains), "max_period_days": body.max_period_days, "dimensions": dims}


async def _target_unique(user: dict, entry, to_table: str, columns: List[str]):
    """(unique, duplicate_groups) — run as the approving admin through the governed path,
    so it sees only the rows that admin's RLS allows. `columns` are the catalog's own
    spelling (quoted identifiers are case-sensitive on some engines)."""
    from sqlglot import exp
    from app.api.query_engine import get_engine
    schema, name = to_table.split(".", 1)
    keys = [exp.column(c) for c in columns]
    inner = (exp.select(*keys).from_(exp.Table(this=exp.to_identifier(name),
                                               db=exp.to_identifier(schema),
                                               catalog=exp.to_identifier(entry.engine_catalog)))
             .group_by(*[k.copy() for k in keys]).having("COUNT(*) > 1"))
    sql = exp.select("COUNT(*)").from_(inner.subquery("d")).sql(
        dialect=get_engine().rls_dialect, identify=True)
    result = await service._execute(sql, user, origin="internal")
    dupes = int(result["rows"][0][0]) if result["rows"] else 0
    return dupes == 0, dupes


async def _recent_queries(name: str) -> int:
    pool = await _pool()
    try:
        async with pool.acquire() as c:
            return int(await c.fetchval(
                "SELECT COUNT(*) FROM tool_call_log WHERE tool = 'metric.query' "
                "AND $1 = ANY(resource) AND occurred_at > now() - interval '30 days'", name))
    except Exception as e:
        logger.info("[semantic] recent query count unavailable: %s", e)
        return 0


# ── metrics ──────────────────────────────────────────────────────────────────

@router.get("/semantic/metrics", dependencies=[Depends(require_permission("catalog:read"))])
async def list_metrics(user: dict = Depends(require_user)):
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    author, admin = _can_author(user), _is_admin(user)
    out = []
    for m in await store.list_metrics(pool):
        if not m.get("catalog") or not access.allows(m["catalog"]):
            continue
        if m["status"] != "approved" and not (author or admin):
            continue
        out.append({k: m[k] for k in ("name", "label", "description", "synonyms", "owner_name",
                                      "status", "current_version", "catalog")})
    return {"metrics": out, "viewer": {"can_author": author, "can_approve": admin}}


def _example_sql(name: str, v, entry) -> Optional[str]:
    from app.api.query_engine import get_engine
    try:
        return compile_metric(v, engine_catalog=entry.engine_catalog,
                              dialect=get_engine().rls_dialect, today=service.today_local(),
                              period="last_month" if v.time_column else None).sql
    except Exception as e:
        logger.info("[semantic] example SQL for %s v%s failed: %s", name, v.version, e)
        return None


@router.get("/semantic/metrics/{name}", dependencies=[Depends(require_permission("catalog:read"))])
async def describe_metric(name: str, user: dict = Depends(require_user)):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta:
        raise HTTPException(404, f"Unknown metric {name!r}.")
    versions = await store.list_versions(pool, meta["id"])
    shown = meta["current_version"] or (versions[0]["version"] if versions else None)
    v = await store.get_version(pool, meta["id"], name, shown) if shown else None
    access = await catalog_access.for_caller(user)
    if v is None or not access.allows(v.catalog):
        raise HTTPException(404, f"Unknown metric {name!r}.")
    insider = _can_author(user) or _is_admin(user)
    if meta["status"] != "approved" and not insider:
        raise HTTPException(404, f"Unknown metric {name!r}.")
    entry = access.resolve(v.catalog)
    broken_reason = None
    cols = await asyncio.to_thread(_columns, entry, v.base_table)
    if cols is None:
        broken_reason = f"Cannot read {v.base_table}."
    else:
        from app.api.query_engine import get_engine
        try:
            validate_measure(v.measure, cols, get_engine().rls_dialect)
            validate_filters(v.filters, cols, get_engine().rls_dialect)
            for c in [v.time_column] + [d.column for d in v.dimensions if d.join is None]:
                if c and c.lower() not in {x.lower() for x in cols}:
                    raise DefinitionError("dimensions", f"Unknown column {c!r} on the base table.")
        except DefinitionError as e:
            broken_reason = str(e)
    # The newest version, if no one has approved it yet: what "Approve vN" would approve,
    # shown with its own SQL. Drafts and their notes are for authors and approvers only.
    pending = None
    if insider and versions and not versions[0]["approved_at"]:
        p = await store.get_version(pool, meta["id"], name, versions[0]["version"])
        if p is not None and access.allows(p.catalog):
            pending = {"version": p.version, "catalog": p.catalog, "base_table": p.base_table,
                       "measure": p.measure, "filters": p.filters,
                       "example_sql": _example_sql(name, p, access.resolve(p.catalog))}
    # A version on a catalog this caller cannot use is not shown, as the metric would
    # not be if its current version were there.
    versions = [x for x in versions if access.allows(x["catalog"])
                and (insider or x["approved_at"])]
    return {"metric": dict(service._public(meta, v), status=meta["status"],
                           owner_name=meta["owner_name"], current_version=meta["current_version"]),
            "versions": versions, "pending": pending, "broken": broken_reason is not None,
            "broken_reason": broken_reason, "example_sql": _example_sql(name, v, entry),
            "partition_info": "unknown", "recent_queries": await _recent_queries(name)}


@router.post("/semantic/metrics", status_code=201)
async def create_metric(body: MetricCreate, user: dict = Depends(require_permission("governance:write"))):
    _require_person(user)
    try:
        check_name(body.name)
    except DefinitionError as e:
        _bad("name", str(e))
    if not body.label.strip():
        _bad("label", "Required.")
    fields = await _checked_version(user, body.version, body.name)
    pool = await _pool()
    if await store.get_metric(pool, body.name):
        _bad("name", f"A metric named {body.name!r} exists.", 409)
    mid = await store.create_metric(pool, name=body.name, label=body.label.strip(),
                                    description=body.description, synonyms=body.synonyms,
                                    owner_id=user.get("id"), owner_name=user.get("username"))
    n = await store.insert_version(pool, metric_id=mid, fields=fields, created_by=user.get("id"),
                                   created_by_name=user.get("username"),
                                   change_note=body.version.change_note)
    await _audit(user, "governance:write", "/api/semantic/metrics", f"metric {body.name} v{n} created")
    return {"name": body.name, "version": n}


@router.post("/semantic/metrics/{name}/versions", status_code=201)
async def create_version(name: str, body: VersionBody,
                         user: dict = Depends(require_permission("governance:write"))):
    _require_person(user)
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta or meta["status"] == "retired":
        raise HTTPException(404, f"Unknown metric {name!r}.")
    # A metric this caller cannot see (its catalog is hidden) is a missing one: the same
    # 404, and no version written over it.
    shown = meta["current_version"] or max((x["version"] for x in
                                            await store.list_versions(pool, meta["id"])), default=None)
    v = await store.get_version(pool, meta["id"], name, shown) if shown else None
    if v is None or not (await catalog_access.for_caller(user)).allows(v.catalog):
        raise HTTPException(404, f"Unknown metric {name!r}.")
    # The spec gates authoring on governance:write and is silent on whose metric; a new
    # version changes what an approver is asked to approve, so it is the owner's act or
    # a signed-in admin's, not any author's.
    if not (_is_admin(user) or (meta.get("owner_id") and meta["owner_id"] == str(user.get("id")))):
        raise HTTPException(403, f"Only the owner of {name!r} or an administrator can add a version.")
    fields = await _checked_version(user, body, name)
    n = await store.insert_version(pool, metric_id=meta["id"], fields=fields,
                                   created_by=user.get("id"), created_by_name=user.get("username"),
                                   change_note=body.change_note)
    await _audit(user, "governance:write", f"/api/semantic/metrics/{name}/versions",
                 f"metric {name} v{n} created")
    return {"name": name, "version": n}


@router.post("/semantic/metrics/{name}/preview")
async def preview(name: str, body: PreviewBody,
                  user: dict = Depends(require_permission("governance:write"))):
    _require_person(user)
    return await service.run_metric_query(user, metric=name, by=body.by, period=body.period,
                                          grain=body.grain, where=body.where, version=body.version,
                                          order_by=body.order_by, limit=body.limit)


class QueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: List[str] = Field(default_factory=list)
    period: Optional[str] = None
    grain: Optional[str] = None
    where: List[dict] = Field(default_factory=list)
    order_by: List[dict] = Field(default_factory=list)
    limit: Optional[int] = None


@router.post("/semantic/metrics/{name}/query")
async def query(name: str, body: QueryBody, user: dict = Depends(require_permission("query:run"))):
    """The console's way to metric.query (SQL Lab's "Query as metric"). Same service,
    same single `metric.query` audit row as the MCP tool."""
    return await service.run_metric_query(user, metric=name, by=body.by, period=body.period,
                                          grain=body.grain, where=body.where,
                                          order_by=body.order_by, limit=body.limit)


@router.post("/semantic/metrics/{name}/versions/{version}/approve")
async def approve(name: str, version: int, admin: dict = Depends(require_admin)):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    v = await store.get_version(pool, meta["id"], name, version) if meta else None
    if v is None or meta["status"] == "retired":
        raise HTTPException(404, f"Unknown metric {name!r}.")
    if v.approved_at is not None:
        raise HTTPException(409, f"{name} v{version} is already approved.")
    if meta["current_version"] and version < meta["current_version"]:
        raise HTTPException(409, f"{name} v{version} is older than the approved "
                                 f"v{meta['current_version']}; approving it would roll the "
                                 "metric back. Write a new version instead.")
    try:
        await store.approve_version(pool, metric_id=meta["id"], version=version,
                                    approver_id=admin.get("id"),
                                    approver_name=admin.get("username"))
    except store.NotApprovable:
        raise HTTPException(409, f"{name} v{version} cannot be approved; reload and retry.")
    await _audit(admin, "admin", f"/api/semantic/metrics/{name}/versions/{version}/approve",
                 f"metric {name} v{version} approved")
    return {"name": name, "version": version}


@router.post("/semantic/metrics/{name}/retire")
async def retire(name: str, admin: dict = Depends(require_admin)):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta:
        raise HTTPException(404, f"Unknown metric {name!r}.")
    await store.retire_metric(pool, meta["id"])
    await _audit(admin, "admin", f"/api/semantic/metrics/{name}/retire", f"metric {name} retired")
    return {"name": name, "status": "retired"}


# ── joins ────────────────────────────────────────────────────────────────────

@router.get("/semantic/joins", dependencies=[Depends(require_permission("catalog:read"))])
async def list_joins(catalog: Optional[str] = None, user: dict = Depends(require_user)):
    access = await catalog_access.for_caller(user)
    return {"joins": [j for j in await store.list_joins(await _pool(), catalog)
                      if access.allows(j["catalog"])]}


@router.post("/semantic/joins", status_code=201)
async def approve_join(body: JoinBody, admin: dict = Depends(require_admin)):
    entry = await _entry_for(admin, body.catalog)
    for t in (body.from_table, body.to_table):
        if t.count(".") != 1:
            _bad("table", "Use schema.table.")
    if not body.on_columns or any(len(p) != 2 for p in body.on_columns):
        _bad("on_columns", "Give [from_column, to_column] pairs.")
    from_cols = await asyncio.to_thread(_columns, entry, body.from_table)
    to_cols = await asyncio.to_thread(_columns, entry, body.to_table)
    if from_cols is None or to_cols is None:
        _bad("table", "Cannot read the columns of one of the tables.")
    fl = {c.lower() for c in from_cols}
    tl = {c.lower(): c for c in to_cols}
    for a, b in body.on_columns:
        if a.lower() not in fl or b.lower() not in tl:
            _bad("on_columns", f"Unknown column in pair [{a}, {b}].")
    unique, dupes = await _target_unique(admin, entry, body.to_table,
                                         [tl[b.lower()] for _, b in body.on_columns])
    if not unique:
        _bad("on_columns", f"{body.to_table} has {dupes} key value(s) that repeat; only "
                           "many-to-one joins are allowed.", duplicates=dupes)
    jid = await store.insert_join(await _pool(), catalog=entry.name, from_table=body.from_table,
                                  to_table=body.to_table, on_columns=body.on_columns,
                                  source=body.source, approver_id=admin.get("id"),
                                  approver_name=admin.get("username"))
    await _audit(admin, "admin", "/api/semantic/joins",
                 f"join {body.from_table} -> {body.to_table} approved")
    return {"id": jid}
