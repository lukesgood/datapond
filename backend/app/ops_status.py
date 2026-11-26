"""Is the lakehouse healthy, and what should I do if not — one summary for the top of
Overview (design thinking C1). The data engineer often runs the platform alone; this
replaces checking Sources, Catalog, Infrastructure and the mirrors list one by one.

`summarize` is pure: the route (app/api/ops.py) gathers its inputs, filtered by what the
caller may see. Issues, most urgent first: engine restarting, unreachable catalogs,
mirrors that diverged or errored, failed table syncs (latest attempt per table in the
window, with a diagnosis from app/sync_diagnosis.py), scheduled runs that were skipped or
errored before syncing anything, sources not synced within the window.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.sync_diagnosis import diagnose

WINDOW_HOURS = 24


def schedule_problem(status: Optional[str]) -> Optional[str]:
    """'skipped' or 'error' when a scheduled run never got to sync, else None. A run whose
    tables failed is already listed per table (sync_failed), with a diagnosis."""
    kind = (status or "").split(":", 1)[0].strip().lower()
    return kind if kind in ("skipped", "error") else None


def summarize(syncs: List[dict], names: Dict[str, str], *, stale: List[dict], engine: Optional[dict],
              catalogs: List[dict], mirrors: List[dict], queries_24h: int, now: datetime,
              schedules: Optional[List[dict]] = None) -> dict:
    since = now - timedelta(hours=WINDOW_HOURS)
    latest: Dict[tuple, tuple] = {}
    for run in syncs:
        started = run.get("started_at")
        if started is None or started < since:
            continue
        for t in run.get("tables") or []:
            key = (run.get("connection_id"), t.get("table"))
            if key not in latest or started > latest[key][0]:
                latest[key] = (started, t)
    failed = [(k, t) for k, (_, t) in latest.items() if not t.get("ok", True)]
    issues: List[dict] = []
    if engine and engine.get("restarting"):
        issues.append({"kind": "engine_restarting"})
    for c in catalogs:
        if c.get("status") == "error":
            issues.append({"kind": "catalog_unreachable", "catalog": c["name"], "error": c.get("error")})
    for m in mirrors:
        if m.get("status") in ("diverged", "error"):
            issues.append({"kind": "mirror", "mirror": m["mirror"], "owner": m.get("owner"),
                           "status": m["status"], "detail": m.get("detail")})
    for (cid, table), t in sorted(failed, key=lambda x: (str(x[0][0]), str(x[0][1]))):
        issues.append({"kind": "sync_failed", "connection_id": cid, "source": names.get(cid, cid),
                       "table": table, "error": t.get("error"), "diagnosis": diagnose(t.get("error"))})
    for sc in schedules or []:
        kind = schedule_problem(sc.get("status"))
        if kind:
            detail = sc["status"].split(":", 1)[1].strip() if ":" in sc["status"] else sc["status"]
            issues.append({"kind": "schedule_failed", "connection_id": sc["connection_id"], "source": sc["name"],
                           "reason": kind, "detail": detail})
    # A source whose run failed is already listed with the failure and its cause.
    reported = {i.get("connection_id") for i in issues if i["kind"] in ("sync_failed", "schedule_failed")}
    for s in stale:
        if s["connection_id"] in reported:
            continue
        hours = int((now - s["last_sync_at"]).total_seconds() // 3600) if s.get("last_sync_at") else None
        issues.append({"kind": "stale_source", "connection_id": s["connection_id"], "source": s["name"],
                       "hours": hours, "schedule": s.get("schedule"), "overdue_since": s.get("overdue_since"),
                       "last_success_at": s.get("last_success_at"), "last_run_at": s.get("last_run_at"),
                       "last_run_status": s.get("last_run_status")})
    return {
        "state": "attention" if issues else "ok",
        "syncs": {"window_hours": WINDOW_HOURS, "tables_ok": len(latest) - len(failed), "tables_failed": len(failed)},
        "queries_24h": queries_24h,
        "issues": issues,
        "checked_at": now.isoformat(),
    }
