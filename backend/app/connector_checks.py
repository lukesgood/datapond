"""Periodic connection checks for sources.

A source's status is the outcome of its last real contact (app/api/connectors.py,
`_record_check`). Syncs, saves and the Check button are contact, but a source nobody
syncs is never contacted, and its status ages until the list marks it stale. This loop
checks every source whose last check is older than the interval, so a status is never
older than the interval plus one tick.

Multi-replica safe the same way as app/rag_scheduler.py: a Postgres advisory lock, so
only one replica runs a given tick. Each check runs off the request loop under a
deadline (`_test_isolated`), because it now happens without anyone asking for it.

It contacts customer systems on a schedule, so it has an off switch and an interval
(CONNECTOR_CHECK_ENABLED / CONNECTOR_CHECK_INTERVAL_MINUTES, Helm
backend.connectorChecks). A paused source is never checked.
"""
import asyncio
import logging
import os

logger = logging.getLogger("connector_checks")

# Same family as the other loops' keys (see app/rag_scheduler.py); unused elsewhere.
LOCK_KEY = 7233183143331076973

# One tick checks at most this many, oldest first. A large install catches up over a
# few ticks instead of opening a hundred connections at once.
BATCH = 25


def interval_minutes() -> int:
    try:
        return max(5, int(os.getenv("CONNECTOR_CHECK_INTERVAL_MINUTES", "60")))
    except ValueError:
        return 60


async def due_ids(conn, interval: int, limit: int = BATCH):
    rows = await conn.fetch(
        """SELECT id FROM connector_connections
           WHERE status IS DISTINCT FROM 'paused'
             AND (last_checked_at IS NULL
                  OR last_checked_at < now() - make_interval(mins => $1))
           ORDER BY last_checked_at NULLS FIRST
           LIMIT $2""", interval, limit)
    return [str(r["id"]) for r in rows]


async def tick(pool, check=None) -> int:
    """One pass. Returns how many sources were checked."""
    if check is None:
        from app.api.connectors import _check_connection as check
    checked = 0
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return 0
        try:
            for connection_id in await due_ids(c, interval_minutes()):
                try:
                    await check(connection_id)
                    checked += 1
                except Exception as e:      # a deleted row, a 404 — never the loop
                    logger.warning("connection check failed for %s: %s", connection_id, e)
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    return checked


async def run_checks(pool) -> None:
    tick_seconds = int(os.getenv("CONNECTOR_CHECK_TICK_SECONDS", "300"))
    logger.info("connector checks started (every %sm, tick %ss)", interval_minutes(), tick_seconds)
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            n = await tick(pool)
            if n:
                logger.info("checked %s source(s)", n)
        except Exception as e:                     # never let the loop die
            logger.warning("connector check tick error: %s", e)
