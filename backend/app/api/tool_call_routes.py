"""Read side of the tool call log: a paged list, a per-actor summary, and an NDJSON
export. All three answer 'which caller read what' — the question the compliance
reviewer asks and security_audit_log cannot answer."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.auth import require_permission
from app.api.connectors import get_db_pool
from app.audit_retention import (retention_days, stream_tool_call_export,
                                 tool_call_row_to_json, utcnow)
from app.tool_call_log import TOOLS

router = APIRouter(dependencies=[Depends(require_permission("audit:read"))])

_MAX_LIMIT = 200

_LIST_COLUMNS = ("id, occurred_at, actor_id::text AS actor_id, actor_username, actor_kind, "
                 "tool, resource_kind, resource, request_hash, request_masked, hit_count, "
                 "citation_sources, pii_masked, outcome, duration_ms, client_address, via")

_SUMMARY_SQL = """
SELECT actor_id::text AS actor_id, actor_username, actor_kind,
       count(*)                                    AS calls,
       count(*) FILTER (WHERE outcome = 'ok')       AS ok,
       count(*) FILTER (WHERE outcome = 'degraded') AS degraded,
       count(*) FILTER (WHERE outcome = 'error')    AS error,
       array_remove(array_agg(DISTINCT r) FILTER (WHERE resource_kind = 'collection'), NULL) AS collections,
       array_remove(array_agg(DISTINCT r) FILTER (WHERE resource_kind = 'tables'), NULL)     AS tables,
       coalesce(sum(hit_count), 0)                  AS hits,
       coalesce(sum(pii_masked), 0)                 AS pii_masked
  FROM public.tool_call_log t
  LEFT JOIN LATERAL unnest(t.resource) AS r ON true
 WHERE occurred_at >= $1 AND occurred_at <= $2
 GROUP BY actor_id, actor_username, actor_kind
 ORDER BY calls DESC
"""


def _window(since: Optional[datetime], until: Optional[datetime]):
    now = utcnow()
    since_ts = since or (now - timedelta(days=retention_days()))
    until_ts = until or now
    for ts in (since_ts, until_ts):
        if ts.tzinfo is None:
            raise HTTPException(status_code=400, detail="since/until must include a timezone")
    if since_ts > until_ts:
        raise HTTPException(status_code=400, detail="since must not be after until")
    return since_ts, until_ts


@router.get("/audit/tool-calls")
async def list_tool_calls(
    since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
    actor_id: Optional[str] = Query(None), tool: Optional[str] = Query(None),
    limit: int = Query(_MAX_LIMIT, ge=1, le=_MAX_LIMIT), offset: int = Query(0, ge=0),
):
    """Page through tool_call_log rows in [since, until], newest first."""
    since_ts, until_ts = _window(since, until)
    if tool is not None and tool not in TOOLS:
        raise HTTPException(status_code=400, detail=f"tool must be one of {list(TOOLS)}")
    where = ["occurred_at >= $1", "occurred_at <= $2"]
    args = [since_ts, until_ts]
    if actor_id:
        args.append(actor_id); where.append(f"actor_id::text = ${len(args)}")
    if tool:
        args.append(tool); where.append(f"tool = ${len(args)}")
    clause = " AND ".join(where)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM public.tool_call_log WHERE {clause}", *args)
        rows = await conn.fetch(
            f"SELECT {_LIST_COLUMNS} FROM public.tool_call_log WHERE {clause} "
            f"ORDER BY occurred_at DESC, id DESC LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}",
            *args, limit, offset)
    out = []
    for r in rows:
        d = dict(r)
        d["occurred_at"] = d["occurred_at"].isoformat()
        d["resource"] = list(d.get("resource") or [])
        d["citation_sources"] = list(d.get("citation_sources") or [])
        out.append(d)
    return {"rows": out, "total": int(total or 0), "capped": int(total or 0) > offset + len(out)}


@router.get("/audit/tool-calls/summary")
async def summarize_tool_calls(
    since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
):
    """Per-actor rollup of calls, outcomes, resources touched, hits and PII masked."""
    since_ts, until_ts = _window(since, until)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SUMMARY_SQL, since_ts, until_ts)
    by_actor = []
    for r in rows:
        d = dict(r)
        d["collections"] = list(d.get("collections") or [])
        d["tables"] = list(d.get("tables") or [])
        by_actor.append(d)
    return {"since": since_ts.isoformat(), "until": until_ts.isoformat(), "by_actor": by_actor}


@router.get("/audit/tool-calls/export")
async def export_tool_calls(
    since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
):
    """Stream tool_call_log rows in [since, until] as NDJSON, one object per line."""
    since_ts, until_ts = _window(since, until)
    pool = await get_db_pool()
    return StreamingResponse(
        stream_tool_call_export(pool, since_ts, until_ts),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="tool-call-log.ndjson"'},
    )
