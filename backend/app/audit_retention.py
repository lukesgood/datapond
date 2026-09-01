"""Retention for the append-only audit tables, and an export that does not need a
database credential.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (B4)

**Retention.** B3 (migration `0005_audit_append_only`) made `security_audit_log`
(B2) and `auth_audit_log` (baseline) reject UPDATE and DELETE from a
`BEFORE UPDATE OR DELETE` trigger, and carved exactly one exception:
`prune_security_audit_log(cutoff_ts)` / `prune_auth_audit_log(cutoff_ts)`, two
`SECURITY DEFINER` functions that flip the trigger's escape-hatch GUC on, delete,
and flip it back off. `prune()` below calls only those two functions — a bare
`DELETE FROM security_audit_log ...` written here would hit the same trigger every
other caller does and raise, but only against a real Postgres, which is why
`tests/test_audit_retention.py` checks this module's own source text for a bare
DELETE rather than trusting a mock to catch the mistake before production does.

Why a floor instead of an off switch: `app/system_events.py` made this argument for
infrastructure events (30-day default, 1-day floor) and it applies here at a longer
horizon. A security audit log is what proves — or disproves — what a caller who
reached the API could and could not do, and that question is usually asked well
after the fact: an incident review, a customer's compliance evidence request, a
breach investigation triggered by something unrelated to the row in question. PCI
DSS 10.5.1 and the evidence SOC 2 auditors typically ask for both expect at least a
year of access-control logs, with the most recent three months retrievable without
delay — this module's 365-day default is sized to clear that bar rather than to
guess at a round number. The floor sits at 90 days: well under the default, but
still spanning a full quarterly review, which is the shortest cycle on which anyone
in practice asks "what happened here." `system_events.py`'s 1-day floor is right for
telemetry nobody keeps past a postmortem; it would be wrong here, because it would
let a misconfiguration erase compliance evidence rather than merely shorten how long
a graph goes back.

Runs its own loop (`run_retention`) rather than folding into
`system_events.run_collector`'s tick. The two share only "periodic, one leader" —
system_events reads Kubernetes and the node's uptime and can fail on something as
mundane as a missing RBAC verb (see its `degraded_event` docstring); this module
only ever calls two SQL functions against two tables it never has to reach a
cluster API for. Combining them would put a Kubernetes-read hiccup and an
audit-retention bug in one failure domain and one log line, and would make
understanding either module require reading both. Kept apart, each module's
docstring is a complete account of what its own loop does.

Multi-replica safety: its own Postgres advisory lock key (`LOCK_KEY`), distinct
from `system_events.LOCK_KEY` and `rag_scheduler.LOCK_KEY` — see
`test_lock_key_is_distinct_from_system_events_and_rag_scheduler`. Reusing either
would make audit retention and an unrelated loop take turns blocking on the same
lock for no shared reason; each holds its key only for the length of its own tick.
Same session-scoped caveat as those two modules: this holds because the backend
talks to Postgres directly, and a transaction-mode pooler in front would break the
mutual exclusion.

**Export.** `GET /audit/export` (wired in `app/api/audit_export.py`, gated on
`audit:read`) streams `security_audit_log` as NDJSON — one JSON object per line —
so the log can reach a SIEM without handing anyone a database credential. It reads
in pages ordered by `(occurred_at, id)` rather than one unbounded `SELECT *`,
because an audit log is the one table in this product a route is not allowed to
assume is small; `stream_security_audit_export` yields one page's rows at a time
and re-acquires a pool connection per page rather than holding one connection open
for however long a slow SIEM client takes to read the whole response.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional

logger = logging.getLogger("audit_retention")

# Distinct from system_events.LOCK_KEY (7233183143331076965) and
# rag_scheduler.LOCK_KEY (7233183143331076964) — arbitrary 64-bit constants, just
# far enough from either that a future third loop won't collide with any of the
# three by typo.
LOCK_KEY = 7233183143331076971

# See the module docstring for why this sits well above system_events' 1-day floor:
# this table is compliance evidence, not operational telemetry, and a floor near
# zero would let a misconfiguration erase what a security audit log exists to keep.
_MIN_RETENTION_DAYS = 90

_DEFAULT_RETENTION_DAYS = 365

_DEFAULT_PAGE_SIZE = 1000


def retention_cutoff(now: datetime, days: int) -> datetime:
    """Same shape as system_events.retention_cutoff: max() enforces the floor no
    matter how low, or negative, `days` is configured to be."""
    return now - timedelta(days=max(int(days), _MIN_RETENTION_DAYS))


def retention_days() -> int:
    try:
        return max(int(os.getenv("AUDIT_RETENTION_DAYS", str(_DEFAULT_RETENTION_DAYS))),
                   _MIN_RETENTION_DAYS)
    except (TypeError, ValueError):
        return _DEFAULT_RETENTION_DAYS


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# The only two statements this module ever sends to the audit tables. Kept as named
# constants rather than built with string formatting so a diff that changed either
# one is easy to spot, and so tests can assert against the literal text.
_PRUNE_SECURITY_SQL = "SELECT prune_security_audit_log($1)"
_PRUNE_AUTH_SQL = "SELECT prune_auth_audit_log($1)"


async def prune(conn, cutoff: datetime) -> dict:
    """Delete everything older than `cutoff` from both audit tables, through the
    sanctioned functions only — never a bare DELETE. See the module docstring and
    `tests/test_audit_retention.py::test_prune_calls_the_sanctioned_functions_not_a_bare_delete`.

    Returns the per-table row count each function reports, for the caller to log.
    """
    security_removed = await conn.fetchval(_PRUNE_SECURITY_SQL, cutoff)
    auth_removed = await conn.fetchval(_PRUNE_AUTH_SQL, cutoff)
    return {
        "security_audit_log": int(security_removed or 0),
        "auth_audit_log": int(auth_removed or 0),
    }


async def tick(pool) -> dict:
    """One retention pass. Single-leader via advisory lock: with two replicas both
    would otherwise call the prune functions at the same time, and while that is
    harmless (DELETE ... WHERE occurred_at < cutoff is idempotent) it doubles the
    transaction work for no benefit.

    Returns {} when another replica holds the lock, or the per-table counts from
    `prune()` otherwise.
    """
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return {}
        try:
            now = utcnow()
            return await prune(c, retention_cutoff(now, retention_days()))
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


async def run_retention(pool) -> None:
    """The loop `main.py` starts alongside `system_events.run_collector` and
    `rag_scheduler.run_scheduler` — one asyncio task, never let die by an exception
    in a single tick."""
    import asyncio
    tick_seconds = int(os.getenv("AUDIT_RETENTION_TICK_SECONDS", "3600"))
    logger.info("audit retention loop started (tick=%ss, retention=%sd)",
                tick_seconds, retention_days())
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            removed = await tick(pool)
            total = sum(removed.values())
            if total:
                logger.info("audit retention pruned %s row(s): %s", total, removed)
        except Exception as e:                       # never let the loop die
            logger.warning("audit retention tick error: %s", e)


# ── export ────────────────────────────────────────────────────────────────────

def security_audit_row_to_json(row: dict) -> str:
    """One `security_audit_log` row as a single JSON line, no trailing newline —
    the caller (`stream_security_audit_export`) owns line termination so this stays
    a pure, trivially testable mapping.

    `occurred_at` is written as ISO-8601 rather than left for `json.dumps`'s
    `default=str` to improvise on, so a SIEM's timestamp parser sees the same
    format on every row regardless of what type asyncpg happened to hand back.
    """
    occurred_at = row.get("occurred_at")
    return json.dumps({
        "id": row.get("id"),
        "actor_id": row.get("actor_id"),
        "actor_username": row.get("actor_username") or "",
        "permission": row.get("permission"),
        "route": row.get("route"),
        "method": row.get("method"),
        "outcome": row.get("outcome"),
        "reason": row.get("reason"),
        "client_address": row.get("client_address"),
        "occurred_at": occurred_at.isoformat() if hasattr(occurred_at, "isoformat")
                        else occurred_at,
    }, default=str)


_EXPORT_FIRST_PAGE_SQL = """
    SELECT id::text, actor_id::text, actor_username, permission, route, method,
           outcome, reason, client_address::text, occurred_at
    FROM security_audit_log
    WHERE occurred_at >= $1 AND occurred_at <= $2
    ORDER BY occurred_at ASC, id ASC
    LIMIT $3
"""

_EXPORT_NEXT_PAGE_SQL = """
    SELECT id::text, actor_id::text, actor_username, permission, route, method,
           outcome, reason, client_address::text, occurred_at
    FROM security_audit_log
    WHERE occurred_at >= $1 AND occurred_at <= $2 AND (occurred_at, id) > ($3, $4)
    ORDER BY occurred_at ASC, id ASC
    LIMIT $5
"""


async def stream_security_audit_export(
    pool, since: datetime, until: datetime, page_size: int = _DEFAULT_PAGE_SIZE,
) -> AsyncIterator[str]:
    """`security_audit_log` between `since` and `until` (inclusive), oldest first,
    as NDJSON lines — each one ending in `\\n`, ready to write straight to the
    response body.

    Paged by `(occurred_at, id)` rather than `OFFSET`, which degrades on a table
    this is explicitly meant to work on however large it gets: `OFFSET n` still
    scans and discards the first `n` rows on every page. A connection is acquired
    and released per page instead of held for the whole response, so one slow SIEM
    client reading the stream does not tie up a pool connection for as long as it
    takes that client to finish.
    """
    last_occurred: Optional[datetime] = None
    last_id: Optional[str] = None
    while True:
        async with pool.acquire() as c:
            if last_id is None:
                rows = await c.fetch(_EXPORT_FIRST_PAGE_SQL, since, until, page_size)
            else:
                rows = await c.fetch(
                    _EXPORT_NEXT_PAGE_SQL, since, until, last_occurred, last_id, page_size)
        if not rows:
            return
        for row in rows:
            yield security_audit_row_to_json(dict(row)) + "\n"
        last_row = rows[-1]
        last_occurred, last_id = last_row["occurred_at"], last_row["id"]
        if len(rows) < page_size:
            return
