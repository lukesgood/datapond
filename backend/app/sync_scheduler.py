"""Scheduled source syncs without Airflow.

A source's schedule (`connector_connections.schedule`, a five-field cron) used to become
an Airflow DAG file. The AWS reference and the Core profiles run no Airflow, so a schedule
was stored and never fired, and the console hid the card there. This loop runs them in
the backend instead, on every profile, the same way as app/rag_scheduler.py and
app/connector_checks.py: one asyncio task per replica, and a Postgres advisory lock so
only one replica runs a given tick.

When a sync is due. `schedule_anchor_at` is when the scheduler last ran the source (or
when the schedule was saved). A source is due when its cron has a fire time after the
anchor and not after now. So a fire time missed while the node was off (the reference
node is stopped overnight and at weekends) runs once when it is back, not once per
missed time, and a schedule saved at 07:50 for 08:00 runs at 08:00, not at once.

Times are read in SCHEDULE_TIMEZONE (an IANA name, default UTC): "0 8 * * *" is 08:00
there. The schedule route returns the zone and the next run, so the console shows both.

Whom it runs as. The person who saved the schedule (`schedule_set_by`; the source's
owner for a schedule saved before that column existed), as the users table has them on
the run: active, holding connector:write, and still allowed to write this source. Any of
those gone and the run is skipped, `schedule_last_status` says why, and a denial goes to
the security audit log, so revoking someone's access also stops their schedules. A
paused source is never run.

A run is claimed (anchor moved to now) before it starts, so a sync that crashes the
process is not retried every tick; the next fire time runs it again.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# Same family as the other loops' keys (see app/rag_scheduler.py); unused elsewhere.
LOCK_KEY = 7233183143331076981

# Search no further back (for due) or ahead (for the next run) than this. Every cron the
# console builds fires at least monthly; one that fires less often is not missed, only
# never shown a next run.
HORIZON = timedelta(days=32)

_PRESETS = {
    "@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
}
_FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12),
           ("day of week", 0, 7))


class Cron:
    """A parsed five-field cron: minute hour day-of-month month day-of-week, each `*`,
    `n`, `a-b`, a step `*/s` or `a-b/s`, or a comma list of those. Day of week 0 and 7
    are Sunday. When both day fields are restricted a day matches either, as in cron."""

    def __init__(self, expr: str):
        text = _PRESETS.get((expr or "").strip().lower(), (expr or "").strip())
        parts = text.split()
        if len(parts) != 5:
            raise ValueError(f"'{expr}' is not a cron schedule: it needs five fields "
                             "(minute hour day month weekday)")
        sets: List[Set[int]] = [_field(p, *spec) for p, spec in zip(parts, _FIELDS)]
        self.expr = expr
        self.minutes, self.hours, self.days, self.months, dows = sets
        self.dows = {d % 7 for d in dows}
        self.any_day = parts[2] == "*"
        self.any_dow = parts[4] == "*"

    def matches(self, local: datetime) -> bool:
        if local.minute not in self.minutes or local.hour not in self.hours \
                or local.month not in self.months:
            return False
        day = local.day in self.days
        dow = (local.isoweekday() % 7) in self.dows
        if self.any_day and self.any_dow:
            return True
        if self.any_day:
            return dow
        if self.any_dow:
            return day
        return day or dow


def _field(text: str, name: str, lo: int, hi: int) -> Set[int]:
    out: Set[int] = set()
    for item in text.split(","):
        rng, _, step_s = item.partition("/")
        try:
            step = int(step_s) if step_s else 1
            if rng == "*":
                a, b = lo, hi
            elif "-" in rng:
                a_s, b_s = rng.split("-", 1)
                a, b = int(a_s), int(b_s)
            else:
                a = int(rng)
                b = hi if step_s else a
        except ValueError:
            raise ValueError(f"'{item}' is not a valid {name}") from None
        if step < 1 or a < lo or b > hi or a > b:
            raise ValueError(f"'{item}' is out of range for {name} ({lo}-{hi})")
        out.update(range(a, b + 1, step))
    return out


def parse(expr: str) -> Cron:
    """The parsed schedule, or ValueError saying what is wrong with it."""
    return Cron(expr)


def zone():
    """SCHEDULE_TIMEZONE as a tzinfo; UTC when unset or unknown (and logged)."""
    name = (os.getenv("SCHEDULE_TIMEZONE") or "UTC").strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        logger.warning("SCHEDULE_TIMEZONE %r is not a known time zone; using UTC", name)
        return timezone.utc


def zone_name() -> str:
    z = zone()
    return getattr(z, "key", None) or "UTC"


def _floor(t: datetime) -> datetime:
    return t.replace(second=0, microsecond=0)


def last_fire(cron: Cron, now: datetime, after: Optional[datetime], tz) -> Optional[datetime]:
    """The latest fire time in (after, now], in UTC, or None. Minute by minute, newest
    first, no further back than HORIZON."""
    t = _floor(now)
    stop = now - HORIZON
    if after is not None and after > stop:
        stop = after
    while t > stop:
        if cron.matches(t.astimezone(tz)):
            return t
        t -= timedelta(minutes=1)
    return None


def next_fire(cron: Cron, now: datetime, tz) -> Optional[datetime]:
    """The first fire time after `now`, in UTC, or None within HORIZON."""
    t = _floor(now) + timedelta(minutes=1)
    end = now + HORIZON
    while t <= end:
        if cron.matches(t.astimezone(tz)):
            return t
        t += timedelta(minutes=1)
    return None


def is_due(expr: str, anchor: Optional[datetime], now: datetime, tz) -> bool:
    """A fire time after the anchor and not after now. A schedule that does not parse
    is never due (the route refuses one; an old row may still carry it)."""
    try:
        cron = parse(expr)
    except ValueError:
        return False
    return last_fire(cron, now, anchor, tz) is not None


def next_run(expr: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """ISO time of the next run for the console, or None (no schedule, unparsable, or
    beyond HORIZON)."""
    if not expr:
        return None
    try:
        cron = parse(expr)
    except ValueError:
        return None
    t = next_fire(cron, now or datetime.now(timezone.utc), zone())
    return t.isoformat() if t else None


def enabled() -> bool:
    return os.getenv("SYNC_SCHEDULER_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


# ── the loop ────────────────────────────────────────────────────────────────────

async def _principal(c, user_id) -> dict:
    """The person a schedule runs as, as the users table has them now; {} when gone or
    disabled (which holds nothing)."""
    if not user_id:
        return {}
    row = await c.fetchrow("SELECT id, username, role, is_active FROM users WHERE id = $1", user_id)
    if row is None or not row["is_active"]:
        return {}
    return {"id": str(row["id"]), "username": row["username"] or "", "role": row["role"]}


async def refusal(c, connection_id: str, principal: dict) -> Optional[str]:
    """None when `principal` may sync this source now, else why not."""
    if not principal:
        return "skipped: whoever set this schedule is no longer an active user"
    from app.permissions import has_permission
    if not has_permission(principal.get("role"), "connector:write"):
        return "skipped: whoever set this schedule no longer holds connector:write"
    from fastapi import HTTPException
    from app.api.source_access import CONNECTOR, resolve
    try:
        await resolve(c, CONNECTOR, connection_id, principal, write=True)
    except HTTPException as e:
        if e.status_code == 404:
            return "skipped: the source no longer exists"
        return "skipped: whoever set this schedule may no longer change this source"
    return None


async def _audit(name: str, principal: dict, reason: str) -> None:
    try:
        from app import security_audit
        await security_audit.record(
            actor=principal or {"username": "scheduled-sync"}, permission="connector:write",
            route=f"sync_scheduler:{name}", method="SCHEDULE", outcome="denied",
            reason=f"Scheduled sync of source '{name}' {reason}.")
    except Exception as e:      # the audit write never stops the loop
        logger.warning("could not audit a refused scheduled sync of %s: %s", name, e)


async def _sync(connection_id: str, principal: dict) -> str:
    """Run the source's sync as `principal`; a one-line status."""
    from app.api.connectors import SyncRequest, trigger_sync
    out = await trigger_sync(connection_id, SyncRequest(), user=principal)
    status = (out or {}).get("status") or "done"
    msg = (out or {}).get("message") or ""
    return f"{status}: {msg}".strip(": ")[:500]


async def tick(pool, now: Optional[datetime] = None, sync=None) -> int:
    """One pass. Returns how many sources were synced."""
    sync = sync or _sync
    tz = zone()
    ran = 0
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return 0
        try:
            rows = await c.fetch(
                """SELECT id, name, schedule, schedule_anchor_at,
                          COALESCE(schedule_set_by, owner_id) AS run_as
                   FROM connector_connections
                   WHERE schedule IS NOT NULL AND schedule <> ''
                     AND status IS DISTINCT FROM 'paused'
                   ORDER BY schedule_anchor_at NULLS FIRST""")
            when = now or datetime.now(timezone.utc)
            for r in rows:
                if not is_due(r["schedule"], r["schedule_anchor_at"], when, tz):
                    continue
                cid = str(r["id"])
                await c.execute(
                    "UPDATE connector_connections SET schedule_anchor_at = now(), "
                    "schedule_last_status = 'running' WHERE id = $1", r["id"])
                principal = await _principal(c, r["run_as"])
                why = await refusal(c, cid, principal)
                if why:
                    status = why
                    await _audit(r["name"], principal, why[len("skipped: "):])
                else:
                    try:
                        status = await sync(cid, principal)
                        ran += 1
                    except Exception as e:
                        detail = getattr(e, "detail", None) or str(e)
                        status = f"error: {detail}"[:500]
                        logger.warning("scheduled sync of %s failed: %s", r["name"], detail)
                await c.execute("UPDATE connector_connections SET schedule_last_status = $2 WHERE id = $1",
                                r["id"], status)
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    return ran


async def run(pool) -> None:
    tick_seconds = int(os.getenv("SYNC_SCHEDULER_TICK_SECONDS", "60"))
    logger.info("source sync scheduler started (tick %ss, zone %s)", tick_seconds, zone_name())
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            n = await tick(pool)
            if n:
                logger.info("ran %s scheduled sync(s)", n)
        except Exception as e:                     # never let the loop die
            logger.warning("sync scheduler tick error: %s", e)
