"""GET /api/ops/status — the one-line health summary at the top of Overview (C1).

Each section is gathered only for callers allowed to see it: syncs and stale sources need
`connector:read`, catalog reachability `catalog:read` (only catalogs the caller may use),
mirrors `catalog:write`; the engine state is shown to everyone signed in. Queries today
count the whole deployment for admins and the caller's own otherwise.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.api.auth import require_user
from app.ops_status import WINDOW_HOURS, summarize

router = APIRouter()


def _permissions(user: dict) -> set:
    from app.permissions import permissions_for
    return set(user.get("permissions") or permissions_for(user.get("role")))


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


def _aware(ts):
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def _load_syncs(pool, user):
    """Syncs, stale sources and scheduled runs of the sources `user` may see: the same
    owner/member/unowned rule as the Sources list (source_access.visible_clause), so
    Overview never names a source, or its errors, that the list would hide."""
    from app.api.source_access import CONNECTOR, visible_clause
    since = datetime.utcnow() - timedelta(hours=WINDOW_HOURS)
    clause, args = visible_clause(CONNECTOR, user, "c", 1)
    async with pool.acquire() as c:
        rows = await c.fetch(
            """SELECT started_at, metadata FROM connector_sync_history
                WHERE started_at >= $1 ORDER BY started_at DESC LIMIT 500""", since)
        from app.sync_alerts import FIXED_SINCE_SQL
        from app.source_freshness import LAST_RUN_SQL, LAST_SUCCESS_SQL
        fixed = FIXED_SINCE_SQL.format(id="c.id", anchor="c.schedule_anchor_at")
        conns = await c.fetch("SELECT c.id, c.name, c.last_sync_at, c.status, c.schedule, c.schedule_last_status, "
                              f"c.schedule_anchor_at, {fixed} AS fixed_since_schedule, "
                              f"{LAST_SUCCESS_SQL.format(id='c.id')} AS last_success_at, "
                              f"{LAST_RUN_SQL.format(id='c.id')} AS last_run "
                              "FROM connector_connections c" + (f" WHERE {clause}" if clause else ""), *args)
    visible = {str(c["id"]) for c in conns}
    syncs = []
    for r in rows:
        meta = r["metadata"] or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        if str(meta.get("connection_id")) not in visible:
            continue
        syncs.append({"started_at": _aware(r["started_at"]), "connection_id": meta.get("connection_id"),
                      "tables": meta.get("tables", [])})
    names = {str(c["id"]): c["name"] for c in conns}
    # Out of date = missed a run its own schedule asked for (app/source_freshness.py),
    # not "no sync for a day": a source synced by hand is never stale.
    from app.source_freshness import freshness
    now = datetime.now(timezone.utc)
    stale = []
    for c in conns:
        f = freshness(c, now)
        if f["overdue_since"]:
            stale.append({"connection_id": str(c["id"]), "name": c["name"], "schedule": c.get("schedule"),
                          "last_sync_at": _aware(c.get("last_success_at")), **f})
    paused = sum(1 for c in conns if c["status"] == "paused")
    schedules = [{"connection_id": str(c["id"]), "name": c["name"], "status": c["schedule_last_status"]}
                 for c in conns if c["status"] != "paused" and (c["schedule"] or "").strip()
                 and c["schedule_last_status"] and not c.get("fixed_since_schedule")]
    return syncs, names, stale, paused, schedules


async def _load_duplicate_syncs(pool):
    """Source tables synced by two jobs of one connection (app/sync_targets.py)."""
    from app import catalog_registry, sync_targets
    try:
        async with pool.acquire() as c:
            rows = [dict(r) for r in await c.fetch(
                """SELECT connection_id, source_table, target_table, target_catalog, enabled, last_run_at
                     FROM connector_sync_jobs""")]
    except Exception:            # before migration 0028
        return []
    try:
        default = catalog_registry.default_entry().engine_catalog
    except Exception:
        default = None
    groups = sync_targets.duplicates(rows)
    for g in groups:
        for j in g["jobs"]:
            j["catalog"] = j["catalog"] or default
            j["last_run_at"] = _aware(j["last_run_at"])
    return groups


async def _load_mirrors(pool):
    try:
        async with pool.acquire() as c:
            rows = await c.fetch(
                """SELECT mirror_catalog || '.' || mirror_schema || '.' || mirror_table AS mirror,
                          owner_catalog || '.' || owner_schema || '.' || owner_table AS owner, status, detail
                     FROM catalog_table_links""")
        return [dict(r) for r in rows]
    except Exception:            # before migration 0028
        return []


async def _load_catalogs(user):
    from app import catalog_access
    from app.api import catalog_admin
    access = await catalog_access.for_caller(user)
    entries = access.entries()
    results = await asyncio.gather(*(catalog_admin._health_of(e) for e in entries))
    return [{"name": e.name, **r} for e, r in zip(entries, results)]


async def _count_queries(pool, user):
    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    try:
        async with pool.acquire() as c:
            if user.get("role") == "admin" and user.get("auth_method") != "service":
                return int(await c.fetchval("SELECT count(*) FROM query_history WHERE created_at >= $1", since))
            import uuid
            return int(await c.fetchval("SELECT count(*) FROM query_history WHERE created_at >= $1 AND user_id = $2",
                                        since, uuid.UUID(str(user["id"]))))
    except Exception:
        return None


def _now():
    return datetime.now(timezone.utc)


def _engine():
    from app.connectors import trino_catalogs
    if not trino_catalogs.enabled():
        return None
    try:
        return trino_catalogs.engine_status(trino_catalogs.RealKube())
    except Exception:
        return None


@router.get("/ops/status")
async def ops_status(user: dict = Depends(require_user)):
    perms = _permissions(user)
    pool = await _pool()
    syncs, names, stale, paused, schedules = ([], {}, [], 0, [])
    if "connector:read" in perms:
        syncs, names, stale, paused, schedules = await _load_syncs(pool, user)
    mirrors = await _load_mirrors(pool) if "catalog:write" in perms else []
    catalogs = await _load_catalogs(user) if "catalog:read" in perms else []
    engine = await asyncio.to_thread(_engine)
    out = summarize(syncs, names, stale=stale, engine=engine, catalogs=catalogs, mirrors=mirrors,
                    queries_24h=await _count_queries(pool, user), now=_now(), schedules=schedules)
    if "connector:read" in perms:
        for d in await _load_duplicate_syncs(pool):
            if d["connection_id"] not in names:      # a source this caller may not see
                continue
            out["issues"].append({"kind": "duplicate_sync", "connection_id": d["connection_id"],
                                  "source": names.get(d["connection_id"], d["connection_id"]),
                                  "table": f'{d["namespace"]}.{d["table"]}',
                                  "jobs": [{"source_table": j["source_table"], "catalog": j["catalog"],
                                            "last_run_at": j["last_run_at"].isoformat() if j["last_run_at"] else None}
                                           for j in d["jobs"]]})
            out["state"] = "attention"
    if user.get("role") == "admin":
        from app.api.infra_aws import over_budget
        ob = over_budget()
        if ob:
            out["issues"].append({"kind": "cost_over_budget", **ob})
            out["state"] = "attention"
    if "connector:read" not in perms:
        out.pop("syncs", None)
    else:
        out["syncs"]["paused_sources"] = paused   # counted, never listed: pausing is a person's choice
    return out
