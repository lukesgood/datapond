"""When a source's data is out of date, and why.

It used to be "active and no sync for 24 hours", for every source. That was wrong both
ways. A source synced by hand (no schedule) is synced when someone needs it, so it was
always "stale" a day later and Overview never cleared; a source scheduled for weekdays
at 08:00 was "stale" every Monday before its run (72 hours since Friday's); and the time
compared was the last attempt, which a failed sync also moves, so a source failing every
day never looked out of date.

Now a source is out of date only when it missed a run its own schedule asked for: its
cron has a fire time (more than GRACE ago) that is later than the source's last fully
successful sync, and the scheduler has not run it since that fire time either (a run it
did start and that failed is reported as that failure, with its cause, not again here).
A source without a schedule is never out of date; the Sources list shows how long since
it was synced instead.

The reasons a scheduled run goes missing: the scheduler is off (SYNC_SCHEDULER_ENABLED),
the node was off at the fire time and has not come back, or the backend could not take
the run. Each one is worth a look, which is the point of reporting it.

SOURCE_OVERDUE_GRACE_MINUTES (default 60): how late a scheduled run may be.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# The newest fully successful sync of the source: every table it synced succeeded.
LAST_SUCCESS_SQL = ("(SELECT max(h.started_at) FROM connector_sync_history h "
                    "WHERE h.metadata->>'connection_id' = {id}::text AND h.status = 'success')")
# The newest sync of any outcome, as "status|started_at" (one subquery for both).
LAST_RUN_SQL = ("(SELECT h.status || '|' || h.started_at::text FROM connector_sync_history h "
                "WHERE h.metadata->>'connection_id' = {id}::text ORDER BY h.started_at DESC LIMIT 1)")


def grace() -> timedelta:
    try:
        return timedelta(minutes=max(0, int(os.getenv("SOURCE_OVERDUE_GRACE_MINUTES", "60"))))
    except ValueError:
        return timedelta(minutes=60)


def aware(ts: Optional[datetime]) -> Optional[datetime]:
    """Stored times without a zone are UTC (connector_sync_history.started_at, last_sync_at)."""
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def missed_run(schedule: Optional[str], status: Optional[str], last_success: Optional[datetime],
               anchor: Optional[datetime], now: datetime, tz=None) -> Optional[datetime]:
    """The scheduled fire time (UTC) the source missed, or None when it is up to date,
    has no schedule, is not active, or its schedule does not parse."""
    if status != "active" or not (schedule or "").strip():
        return None
    from app import sync_scheduler
    try:
        cron = sync_scheduler.parse(schedule)
    except ValueError:
        return None
    fire = sync_scheduler.last_fire(cron, aware(now) - grace(), None, tz or sync_scheduler.zone())
    if fire is None:
        return None
    anchor, last_success = aware(anchor), aware(last_success)
    # The scheduler took it (anchor moved on claim) or the schedule was saved after that
    # time: either it ran, and a failure is reported as one, or it was not due yet.
    if anchor is not None and anchor >= fire:
        return None
    if last_success is not None and last_success >= fire:
        return None
    return fire


def freshness(row, now: datetime, tz=None) -> dict:
    """The fields the Sources list, the source page and Overview show for one source.
    `row` needs schedule, status, last_success_at, schedule_anchor_at and last_run
    (LAST_RUN_SQL)."""
    def get(k):
        try:
            return row[k]
        except (KeyError, IndexError):
            return None
    last_success = aware(get("last_success_at"))
    run_status, _, run_at = (get("last_run") or "").partition("|")
    try:
        last_run_at = aware(datetime.fromisoformat(run_at.strip())) if run_at else None
    except ValueError:
        last_run_at = None
    missed = missed_run(get("schedule"), get("status"), last_success, get("schedule_anchor_at"), now, tz)
    return {
        "last_success_at": last_success.isoformat() if last_success else None,
        "overdue_since": missed.isoformat() if missed else None,
        # The newest sync, whatever happened: when it is not the last success, it is
        # why the data is older than the last attempt suggests.
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "last_run_status": run_status or None,
    }
