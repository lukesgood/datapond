"""Infrastructure → Events: the durable event history.

Design: docs/superpowers/specs/2026-08-27-system-event-history-design.md

The collection logic is in app/system_events.py. This is the read side, gated on
`service:manage` — the same permission as the page that shows it, so this adds no new
vocabulary. `auditor` holds `audit:read` but not `service:manage`, so it cannot reach
Infrastructure at all today; widening that is a separate decision.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.auth import require_permission
from app.api.connectors import get_db_pool
from app.system_events import build_filters

logger = logging.getLogger(__name__)
router = APIRouter()

_SEVERITIES = ("info", "warning", "critical")


@router.get("/system/events", dependencies=[Depends(require_permission("service:manage"))])
async def list_system_events(
    severity: Optional[str] = Query(None, description="info | warning | critical"),
    kind: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    hours: int = Query(168, ge=1, le=24 * 90, description="How far back to look"),
    limit: int = Query(200, ge=1, le=1000),
):
    """What happened to this deployment, oldest occurrence and latest both kept.

    Repeats are one row: `occurrences` with `first_seen`/`last_seen`, not N rows of the
    same probe timing out.
    """
    where, args = build_filters(hours, severity, kind, source)
    # Severity counts come from the same window but ignore the severity filter, so the
    # badges stay stable while the user filters by one of them.
    count_where, count_args = build_filters(hours, None, kind, source)

    pool = await get_db_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            f"""SELECT id::text, dedup_key, kind, severity, source, object, message,
                       details, first_seen, last_seen, occurrences
                FROM system_events WHERE {where}
                ORDER BY last_seen DESC LIMIT ${len(args) + 1}""",
            *args, limit)
        counts = await c.fetch(
            f"""SELECT severity, count(*) AS n FROM system_events
                WHERE {count_where} GROUP BY severity""",
            *count_args)

    import json
    def _details(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return {}
        return v or {}

    by_severity = {s: 0 for s in _SEVERITIES}
    for r in counts:
        by_severity[r["severity"]] = r["n"]

    return {
        "events": [{
            "id": r["id"],
            "kind": r["kind"],
            "severity": r["severity"],
            "source": r["source"],
            "object": r["object"],
            "message": r["message"],
            "details": _details(r["details"]),
            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            "occurrences": r["occurrences"],
        } for r in rows],
        "counts": by_severity,
        "window_hours": hours,
        # Stated in the response, not only in the docs: nothing is collected while the
        # backend is down, so an empty window is not proof that nothing happened.
        "collection_gap_possible": True,
    }
