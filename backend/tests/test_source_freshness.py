"""A source is out of date only when it missed a run its own schedule asked for
(app/source_freshness.py), not after a fixed 24 hours."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.ops_status import summarize
from app.source_freshness import freshness, missed_run

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS_8 = "0 8 * * 1-5"


def kst(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=KST).astimezone(timezone.utc)


FRI_RUN = kst(2026, 11, 27, 8, 1)       # Friday's 08:00 run succeeded


def test_monday_before_the_run_is_not_stale():
    """72 hours since Friday's run, but Monday's has not been due yet."""
    for now in (kst(2026, 11, 30, 7, 35), kst(2026, 11, 30, 8, 30)):   # before / within grace
        assert missed_run(WEEKDAYS_8, "active", FRI_RUN, FRI_RUN, now, KST) is None


def test_a_missed_run_is_stale_from_the_fire_time():
    now = kst(2026, 11, 30, 10, 0)       # Monday 10:00, the 08:00 run never happened
    assert missed_run(WEEKDAYS_8, "active", FRI_RUN, FRI_RUN, now, KST) == kst(2026, 11, 30, 8, 0)


def test_a_run_that_started_and_failed_is_not_reported_twice():
    """The scheduler took it (anchor moved): the failure is listed with its cause."""
    now = kst(2026, 11, 30, 10, 0)
    assert missed_run(WEEKDAYS_8, "active", FRI_RUN, kst(2026, 11, 30, 8, 0, ), now, KST) is None


def test_a_schedule_saved_after_the_fire_time_is_not_due_yet():
    now = kst(2026, 11, 30, 10, 0)
    old = kst(2026, 11, 2, 9, 0)
    assert missed_run(WEEKDAYS_8, "active", old, kst(2026, 11, 30, 9, 0), now, KST) is None


def test_manual_paused_and_unparsable_sources_are_never_stale():
    now = kst(2026, 12, 20, 10, 0)
    assert missed_run(None, "active", None, None, now, KST) is None
    assert missed_run(WEEKDAYS_8, "paused", None, None, now, KST) is None
    assert missed_run("not a cron", "active", None, None, now, KST) is None


def test_freshness_reports_the_last_success_and_the_last_run():
    row = {"schedule": WEEKDAYS_8, "status": "active", "schedule_anchor_at": FRI_RUN,
           "last_success_at": FRI_RUN.replace(tzinfo=None),          # stored without a zone (UTC)
           "last_run": "failed|2026-11-28 01:00:00.5"}
    f = freshness(row, kst(2026, 11, 30, 10, 0), KST)
    assert f["overdue_since"] == kst(2026, 11, 30, 8, 0).isoformat()
    assert f["last_success_at"] == FRI_RUN.isoformat()
    assert f["last_run_status"] == "failed" and f["last_run_at"].startswith("2026-11-28T01:00:00")
    assert freshness({"status": "active"}, kst(2026, 11, 30, 10, 0), KST) == {
        "last_success_at": None, "overdue_since": None, "last_run_at": None, "last_run_status": None}


def test_overview_lists_a_stale_source_with_why_unless_its_failure_is_listed():
    now = datetime(2026, 11, 30, 1, 0, tzinfo=timezone.utc)
    stale = [{"connection_id": "a", "name": "A", "schedule": WEEKDAYS_8, "last_sync_at": FRI_RUN,
              "overdue_since": "2026-11-29T23:00:00+00:00", "last_success_at": FRI_RUN.isoformat(),
              "last_run_at": None, "last_run_status": None},
             {"connection_id": "b", "name": "B", "schedule": WEEKDAYS_8, "last_sync_at": FRI_RUN,
              "overdue_since": "2026-11-29T23:00:00+00:00"}]
    syncs = [{"started_at": now, "connection_id": "b", "tables": [{"table": "t", "ok": False, "error": "x"}]}]
    out = summarize(syncs, {"a": "A", "b": "B"}, stale=stale, engine=None, catalogs=[], mirrors=[],
                    queries_24h=0, now=now)
    st = [i for i in out["issues"] if i["kind"] == "stale_source"]
    assert [i["connection_id"] for i in st] == ["a"]
    assert st[0]["overdue_since"] and st[0]["schedule"] == WEEKDAYS_8 and st[0]["hours"] == 73
