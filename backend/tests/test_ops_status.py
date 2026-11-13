"""One line that says whether the lakehouse is healthy, and what to do when it is not
(design thinking C1). Each table's latest sync in the window decides; a later success
clears an earlier failure."""
from datetime import datetime, timedelta, timezone

from app.ops_status import summarize

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
TYPE = "Column 'payload' changed type from row(\"a\" varchar) to varchar; Iceberg cannot alter it in place."


def run(minutes_ago, cid, tables):
    return {"started_at": NOW - timedelta(minutes=minutes_ago), "connection_id": cid, "tables": tables}


SYNCS = [
    run(10, "c1", [{"table": "public.orders", "ok": True}, {"table": "public.api_events", "ok": False, "error": TYPE}]),
    run(90, "c1", [{"table": "public.orders", "ok": False, "error": "connect timed out"}]),
    run(30, "c2", [{"table": "public.invoices", "ok": True}]),
]
NAMES = {"c1": "Sample E-Commerce DB", "c2": "Sample Finance DB"}


def test_latest_attempt_per_table_decides_and_failures_carry_a_diagnosis():
    s = summarize(SYNCS, NAMES, stale=[], engine=None, catalogs=[], mirrors=[], queries_24h=12, now=NOW)
    assert s["state"] == "attention"
    assert s["syncs"] == {"window_hours": 24, "tables_ok": 2, "tables_failed": 1}
    (issue,) = [i for i in s["issues"] if i["kind"] == "sync_failed"]
    assert issue["source"] == "Sample E-Commerce DB" and issue["table"] == "public.api_events"
    assert issue["diagnosis"]["action"] == "recreate"
    assert s["queries_24h"] == 12


def test_all_quiet_is_ok():
    good = [run(5, "c2", [{"table": "public.invoices", "ok": True}])]
    s = summarize(good, NAMES, stale=[], engine={"ready": True, "restarting": False}, catalogs=[], mirrors=[],
                  queries_24h=0, now=NOW)
    assert s["state"] == "ok" and s["issues"] == []


def test_stale_sources_restarts_unreachable_catalogs_and_bad_mirrors_are_issues():
    s = summarize([], NAMES,
                  stale=[{"connection_id": "c2", "name": "Sample Finance DB", "last_sync_at": NOW - timedelta(days=3)}],
                  engine={"ready": False, "restarting": True},
                  catalogs=[{"name": "polaris_lake", "status": "error", "error": "401"},
                            {"name": "AwsDataCatalog", "status": "reachable", "error": None}],
                  mirrors=[{"mirror": "catb.raw.x", "owner": "iceberg.raw.x", "status": "diverged", "detail": "d"},
                           {"mirror": "catb.raw.y", "owner": "iceberg.raw.y", "status": "fresh", "detail": None}],
                  queries_24h=0, now=NOW)
    kinds = [i["kind"] for i in s["issues"]]
    assert kinds == ["engine_restarting", "catalog_unreachable", "mirror", "stale_source"]
    assert s["issues"][1]["catalog"] == "polaris_lake" and s["issues"][2]["status"] == "diverged"
    assert s["issues"][3]["hours"] == 72


def test_sync_runs_older_than_the_window_are_ignored():
    old = [run(60 * 30, "c1", [{"table": "public.orders", "ok": False, "error": "x"}])]
    s = summarize(old, NAMES, stale=[], engine=None, catalogs=[], mirrors=[], queries_24h=0, now=NOW)
    assert s["syncs"]["tables_failed"] == 0


# ── the route: each section only for callers who may see it ───────────────────
import asyncio  # noqa: E402

from app.api import ops  # noqa: E402


def test_the_route_gathers_only_what_the_caller_may_see(monkeypatch):
    seen = []

    async def _syncs(pool):
        seen.append("syncs")
        return SYNCS, NAMES, []

    async def _mirrors(pool):
        seen.append("mirrors")
        return [{"mirror": "catb.raw.x", "owner": "iceberg.raw.x", "status": "diverged", "detail": "d"}]

    async def _catalogs(user):
        seen.append("catalogs")
        return []

    async def _queries(pool, user):
        return 3

    async def _pool():
        return object()
    monkeypatch.setattr(ops, "_load_syncs", _syncs)
    monkeypatch.setattr(ops, "_load_mirrors", _mirrors)
    monkeypatch.setattr(ops, "_load_catalogs", _catalogs)
    monkeypatch.setattr(ops, "_count_queries", _queries)
    monkeypatch.setattr(ops, "_engine", lambda: None)
    monkeypatch.setattr(ops, "_pool", _pool)

    viewer = {"id": "u1", "role": "viewer"}
    monkeypatch.setattr(ops, "_permissions", lambda u: {"catalog:read", "query:run"})
    out = asyncio.run(ops.ops_status(user=viewer))
    assert seen == ["catalogs"] and "syncs" not in out and out["queries_24h"] == 3

    seen.clear()
    monkeypatch.setattr(ops, "_permissions", lambda u: {"catalog:read", "connector:read", "catalog:write"})
    out = asyncio.run(ops.ops_status(user={"id": "u2", "role": "data_engineer"}))
    assert set(seen) == {"syncs", "mirrors", "catalogs"}
    assert out["syncs"]["tables_failed"] == 1 and any(i["kind"] == "mirror" for i in out["issues"])
