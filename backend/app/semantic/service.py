"""Who may see which metric, and running one through the governed path.

Visibility: an approved metric whose catalog the caller may use. Anything else — a
missing name, a hidden catalog, a retired or never-approved metric, someone else's
draft — is the same 404, so the answer does not reveal what exists.

Execution goes through queries._execute_query_impl, the body of /queries/execute:
write classifier, hidden-catalog refusal, RLS, masking, PII guard and LIMIT apply
exactly as to any statement. The wrapper is not used, so its `query.execute` audit row
is not written; this module writes one `metric.query` row instead.
"""
import json
import os
import time
from dataclasses import replace
from datetime import date, datetime
from typing import Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app import catalog_access, tool_call_log
from app.semantic import store
from app.semantic.compile import compile_metric
from app.semantic.model import MetricInputError, MetricVersion

TOOL = "metric.query"


class MetricNotFound(Exception):
    pass


def _not_found(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown metric {name!r}.")


def today_local() -> date:
    return datetime.now(ZoneInfo(os.getenv("SEMANTIC_TIMEZONE", "Asia/Seoul"))).date()


def _dialect() -> str:
    from app.api.query_engine import get_engine
    return get_engine().rls_dialect


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


def _may_preview(user: dict, v: MetricVersion) -> bool:
    from app.api.auth import is_delegated_credential
    if is_delegated_credential(user):
        return False
    return user.get("role") == "admin" or (v.created_by and v.created_by == str(user.get("id")))


async def resolve_visible(user: dict, name: str, version: Optional[int] = None):
    pool = await _pool()
    meta = await store.get_metric(pool, name)
    if not meta or meta["status"] == "retired":
        raise MetricNotFound(name)
    if version is None:
        if meta["status"] != "approved" or not meta["current_version"]:
            raise MetricNotFound(name)
        v = await store.get_version(pool, meta["id"], name, meta["current_version"])
    else:
        v = await store.get_version(pool, meta["id"], name, version)
        # Agents use only the approved current version; any other (draft or superseded)
        # is for its author or a signed-in admin.
        if v is None or (version != meta["current_version"] and not _may_preview(user, v)):
            raise MetricNotFound(name)
        if v.approved_at is None and not _may_preview(user, v):
            raise MetricNotFound(name)
    if v is None:
        raise MetricNotFound(name)
    access = await catalog_access.for_caller(user)
    if not access.allows(v.catalog):
        raise MetricNotFound(name)
    return meta, v, access.resolve(v.catalog)


async def _execute(sql: str, user: dict, origin: str = "metric") -> dict:
    """`origin` labels the query_history row: "metric" for a metric's statement (kept out
    of the relationship graph), "internal" for a console check such as join uniqueness."""
    from app.api.queries import QueryExecuteRequest, _execute_query_impl
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        r = await _execute_query_impl(
            QueryExecuteRequest(query=sql, save_history=True, origin=origin), db, user)
    finally:
        db.close()
    return {"columns": r.columns, "rows": r.rows, "row_count": r.row_count,
            "truncated": r.truncated, "pii_masked": r.pii_masked}


async def run_metric_query(user: dict, *, metric: str, by: Sequence[str] = (),
                           period: Optional[str] = None, grain: Optional[str] = None,
                           where: Sequence[dict] = (), version: Optional[int] = None,
                           order_by: Sequence[dict] = (), limit: Optional[int] = None) -> dict:
    request = {"metric": metric, "by": by, "period": period, "grain": grain,
               "where": where or [], "version": version,
               "order_by": order_by or [], "limit": limit}

    def build(v: MetricVersion, entry):
        return compile_metric(v, engine_catalog=entry.engine_catalog, dialect=_dialect(),
                              today=today_local(), by=by, period=period,
                              grain=grain, where=where or [],
                              order_by=order_by or [], limit=limit)
    out = await _governed(user, tool=TOOL, metric=metric, request=request, version=version,
                          build=build, limit=limit)
    if where and not out["rows"]:
        out["note"] = ("No rows. If a where value may be spelled differently in the data, "
                       "metric_values lists the values a dimension takes.")
    return out


VALUES_TOOL = "metric.values"
VALUES_LIMIT = 20


async def run_dimension_values(user: dict, *, metric: str, dimension: str,
                               period: Optional[str] = None) -> dict:
    """The values one dimension takes within the metric's own scope (base table, default
    filters, approved join), most rows first — so an agent filters on a value that
    exists instead of guessing its spelling. The metric is run with COUNT(*) as its
    measure through the same compiler and governed path, so RLS and masking apply to
    the values exactly as to a query. Without a period the time column is not bounded."""
    request = {"metric": metric, "dimension": dimension, "period": period}

    def build(v: MetricVersion, entry):
        counted = replace(v, metric="rows", measure="COUNT(*)",
                          time_column=v.time_column if period is not None else None)
        return compile_metric(counted, engine_catalog=entry.engine_catalog, dialect=_dialect(),
                              today=today_local(), by=[dimension], period=period,
                              order_by=[{"field": "rows", "desc": True}], limit=VALUES_LIMIT)
    out = await _governed(user, tool=VALUES_TOOL, metric=metric, request=request, version=None,
                          build=build, limit=VALUES_LIMIT)
    out["dimension"] = dimension
    return out


async def _governed(user: dict, *, tool: str, metric: str, request: dict,
                    version: Optional[int], build, limit: Optional[int]) -> dict:
    """Resolve the visible version, compile, execute through the governed path, and
    write one audit row whatever happens."""
    from app.api.queries import rls_applied_ids
    started = time.perf_counter()
    request_text = tool_call_log.masked_for_log(
        json.dumps(request, ensure_ascii=False, default=str))

    async def audit(outcome, *, cite=None, sql=None, hits=0, pii=0):
        await tool_call_log.record(
            actor=user, tool=tool, resource_kind="metric", resource=[metric],
            request_text=request_text, hit_count=hits, citation_sources=cite,
            pii_masked=pii, outcome=outcome, response_text=sql,
            duration_ms=int((time.perf_counter() - started) * 1000))

    try:
        _meta, v, entry = await resolve_visible(user, metric, version)
        compiled = build(v, entry)
    except MetricNotFound:
        await audit("refused")
        raise _not_found(metric)
    except MetricInputError as e:
        await audit("refused")
        allowed = f" Allowed: {json.dumps(e.allowed, ensure_ascii=False)}" if e.allowed else ""
        raise HTTPException(status_code=400, detail=f"{e}{allowed}")
    except Exception:
        await audit("error")
        raise

    cite = [f"metric:{v.metric}@v{v.version}"]
    try:
        with rls_applied_ids() as applied:
            result = await _execute(compiled.sql, user)
    except HTTPException as e:
        refused = e.status_code in (401, 403)
        await audit("refused" if refused else "error", cite=cite, sql=compiled.sql)
        if refused:
            raise
        raise HTTPException(status_code=e.status_code,
                            detail=f"{e.detail} The metric definition may need re-validation "
                                   "against the current table.")
    except Exception:
        await audit("error", cite=cite, sql=compiled.sql)
        raise
    await audit("ok", cite=cite, sql=compiled.sql, hits=int(result["row_count"] or 0),
                pii=int(result.get("pii_masked") or 0))
    citation = dict(compiled.citation, metric=v.metric, version=v.version,
                    rls_applied=bool(applied), pii_masked=int(result.get("pii_masked") or 0))
    return {"columns": result["columns"], "rows": result["rows"],
            "row_count": result["row_count"],
            # A caller's LIMIT hides the engine's own cap, so a full page may not be all.
            "truncated": bool(result["truncated"]) or (
                limit is not None and int(result["row_count"] or 0) >= limit),
            "citation": citation}


def _public(meta: dict, v: Optional[MetricVersion]) -> dict:
    out = {"name": meta["name"], "label": meta["label"], "description": meta["description"],
           "synonyms": list(meta["synonyms"] or [])}
    if v is not None:
        out.update({"version": v.version, "catalog": v.catalog, "base_table": v.base_table,
                    "measure": v.measure, "filters": v.filters, "time_column": v.time_column,
                    "grains": list(v.grains), "max_period_days": v.max_period_days,
                    "dimensions": [d.name for d in v.dimensions],
                    "approved_by": v.approved_by, "approved_at": v.approved_at})
    return out


async def list_visible(user: dict, catalog: Optional[str] = None) -> list:
    pool = await _pool()
    access = await catalog_access.for_caller(user)
    out = []
    for m in await store.list_metrics(pool):
        if m["status"] != "approved" or not m["current_version"] or not m.get("catalog"):
            continue
        if not access.allows(m["catalog"]):
            continue
        if catalog and m["catalog"].lower() != catalog.lower():
            continue
        out.append({"name": m["name"], "label": m["label"], "description": m["description"],
                    "synonyms": list(m["synonyms"] or [])})
    return out


async def describe_visible(user: dict, name: str) -> dict:
    try:
        meta, v, _entry = await resolve_visible(user, name)
    except MetricNotFound:
        raise _not_found(name)
    return _public(meta, v)
