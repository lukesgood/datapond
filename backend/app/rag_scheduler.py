"""Airflow-free RAG freshness scheduler. A single asyncio loop (started at backend
startup) periodically re-embeds collections that have a saved source + interval.
Multi-replica safe via a Postgres advisory lock — only the replica that holds the
lock runs a given tick."""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("rag_scheduler")

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
                """SELECT id, name, refresh_source, refresh_interval_minutes, last_refreshed_at
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
