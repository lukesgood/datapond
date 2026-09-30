"""Airflow-free RAG freshness scheduler. A single asyncio loop (started at backend
startup) periodically re-embeds collections that have a saved source + interval.
Multi-replica safe via a Postgres advisory lock — only the replica that holds the
lock runs a given tick.

A schedule runs as its collection's owner, and whether that owner may still use the
source's data catalog (app/catalog_access.py) is checked on every run, not only when
the schedule was saved: a grant revoked since stops the next run. A collection with no
owner is searchable by every knowledge reader, so it runs as nobody in particular and
may read only a catalog open to every caller; so does one whose owner is gone or
disabled. A refused run reads nothing, sets `last_refresh_status` to "skipped: …" and
writes a `catalog:use` denial to security_audit naming the catalog (the audit log is
read by auditors; the status is shown to the collection's owner and does not)."""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app import security_audit

logger = logging.getLogger("rag_scheduler")

SKIPPED_NO_CATALOG_ACCESS = ("skipped: the collection's owner may no longer use this "
                             "source's data catalog")

# Fixed 64-bit key (derived from ASCII 'datapond', high bit cleared) for pg_try_advisory_lock.
# NOTE: pg_try_advisory_lock is SESSION-scoped. The backend connects to Aurora directly via
# asyncpg (no transaction-pooling proxy), so lock + tick statements share one session and the
# cross-replica exclusion holds. If a transaction-mode pooler (RDS Proxy / PgBouncer) is ever
# put in front, this exclusion breaks — switch to a row-lock/leader-row approach then.
LOCK_KEY = 7233183143331076964


def _is_due(last_refreshed_at, interval_minutes: int, now: datetime) -> bool:
    if last_refreshed_at is None:
        return True
    delta_min = (now - last_refreshed_at).total_seconds() / 60.0
    return delta_min >= interval_minutes


async def _owner(c, owner_id) -> dict:
    """The principal a schedule runs as: the owner's id, username and role as the
    users table has them now. An owner that is gone or disabled — and a collection
    with none — is the empty principal, which holds no grant."""
    if not owner_id:
        return {}
    row = await c.fetchrow(
        "SELECT id, username, role, is_active FROM users WHERE id = $1", owner_id)
    if row is None or not row["is_active"]:
        return {}
    return {"id": str(row["id"]), "username": row["username"] or "", "role": row["role"]}


async def catalog_refusal(c, owner_id, src) -> Optional[dict]:
    """None when this schedule may read its source now; otherwise the principal it
    ran as and the catalog it was refused (for the audit row). Only an Iceberg source
    reads a catalog. A catalog the registry no longer knows is not refused here —
    `_refresh_from_source` reports it, as it always has."""
    if src.type != "iceberg":
        return None
    from app import catalog_access, catalog_registry
    try:
        entry = catalog_registry.resolve(src.catalog)
    except catalog_registry.UnknownCatalog:
        return None
    principal = await _owner(c, owner_id)
    access = await catalog_access.for_caller(principal)
    if access.allows(entry):
        return None
    return {"principal": principal, "catalog": entry.name}


async def _refuse(name: str, refusal: dict) -> None:
    principal = refusal["principal"]
    await security_audit.record(
        actor=principal or {"username": "rag_scheduler"}, permission="catalog:use",
        route=f"rag_scheduler:{name}", method="SCHEDULE", outcome="denied",
        reason=(f"Scheduled re-embed of collection '{name}' skipped: "
                f"{'its owner' if principal else 'a collection with no active owner'} "
                f"may not use data catalog '{refusal['catalog']}'."))


async def tick(pool) -> int:
    """One scheduling pass. Returns the number of collections refreshed."""
    from app.api.ai_vectors import _refresh_from_source, SourceIngest
    refreshed = 0
    async with pool.acquire() as c:
        got = await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY)
        if not got:
            return 0
        try:
            rows = await c.fetch(
                """SELECT id, name, owner_id, refresh_source, refresh_interval_minutes,
                          last_refreshed_at
                   FROM ai_collections
                   WHERE refresh_enabled AND refresh_source IS NOT NULL""")
            now = datetime.now(timezone.utc)
            for r in rows:
                if not _is_due(r["last_refreshed_at"], r["refresh_interval_minutes"], now):
                    continue
                # Claim first (so a crash mid-run doesn't hot-loop this collection).
                await c.execute("UPDATE ai_collections SET last_refreshed_at = now() WHERE id = $1", r["id"])
                try:
                    src = SourceIngest(**json.loads(r["refresh_source"]))
                    refusal = await catalog_refusal(c, r.get("owner_id"), src)
                    if refusal is not None:
                        await _refuse(r["name"], refusal)
                        await c.execute(
                            "UPDATE ai_collections SET last_refresh_status = $2 WHERE id = $1",
                            r["id"], SKIPPED_NO_CATALOG_ACCESS)
                        continue
                    res = await _refresh_from_source(pool, r["id"], src)
                    status = f"ok: {res.get('chunks', 0)} chunks"
                    refreshed += 1
                except Exception as e:
                    status = f"error: {e}"[:500]
                    logger.warning("refresh failed for collection %s: %s", r["name"], e)
                await c.execute("UPDATE ai_collections SET last_refresh_status = $2 WHERE id = $1",
                                r["id"], status)
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    return refreshed


async def run_scheduler(pool) -> None:
    tick_seconds = int(os.getenv("RAG_SCHEDULER_TICK_SECONDS", "300"))
    logger.info("RAG freshness scheduler started (tick=%ss)", tick_seconds)
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            n = await tick(pool)
            if n:
                logger.info("RAG scheduler refreshed %s collection(s)", n)
        except Exception as e:                     # never let the loop die
            logger.warning("RAG scheduler tick error: %s", e)
