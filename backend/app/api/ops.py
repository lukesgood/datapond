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


async def _load_syncs(pool):
    since = datetime.utcnow() - timedelta(hours=WINDOW_HOURS)
    async with pool.acquire() as c:
        rows = await c.fetch(
            """SELECT started_at, metadata FROM connector_sync_history
                WHERE started_at >= $1 ORDER BY started_at DESC LIMIT 500""", since)
        conns = await c.fetch("SELECT id, name, last_sync_at, status FROM connector_connections")
    syncs = []
    for r in rows:
        meta = r["metadata"] or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        syncs.append({"started_at": _aware(r["started_at"]), "connection_id": meta.get("connection_id"),
                      "tables": meta.get("tables", [])})
    names = {str(c["id"]): c["name"] for c in conns}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    stale = [{"connection_id": str(c["id"]), "name": c["name"], "last_sync_at": _aware(c["last_sync_at"])}
             for c in conns if c["status"] == "active" and c["last_sync_at"] and _aware(c["last_sync_at"]) < cutoff]
    return syncs, names, stale


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
    syncs, names, stale = ([], {}, [])
    if "connector:read" in perms:
        syncs, names, stale = await _load_syncs(pool)
    mirrors = await _load_mirrors(pool) if "catalog:write" in perms else []
    catalogs = await _load_catalogs(user) if "catalog:read" in perms else []
    engine = await asyncio.to_thread(_engine)
    out = summarize(syncs, names, stale=stale, engine=engine, catalogs=catalogs, mirrors=mirrors,
                    queries_24h=await _count_queries(pool, user), now=datetime.now(timezone.utc))
    if "connector:read" not in perms:
        out.pop("syncs", None)
    return out
