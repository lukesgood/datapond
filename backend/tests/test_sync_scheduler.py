"""Scheduled source syncs run by the backend (app/sync_scheduler.py)."""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import sync_scheduler as ss

SEOUL = ZoneInfo("Asia/Seoul")
UTC = timezone.utc


def kst(*a):
    return datetime(*a, tzinfo=SEOUL).astimezone(UTC)


# --- cron -----------------------------------------------------------------------

def test_every_form_the_console_builds_parses():
    for expr in ("*/15 * * * *", "0 * * * *", "0 */6 * * *", "0 */12 * * *",
                 "0 8 * * *", "0 8 * * 1", "0 8 1 * *", "@daily", "@hourly", "0 8 * * 1-5"):
        ss.parse(expr)


@pytest.mark.parametrize("bad", ["", "0 8 * *", "60 * * * *", "0 24 * * *", "* * 0 * *",
                                 "x * * * *", "*/0 * * * *", "5-1 * * * *", "@once"])
def test_bad_schedules_say_what_is_wrong(bad):
    with pytest.raises(ValueError):
        ss.parse(bad)


def test_matching_reads_fields_like_cron():
    weekdays = ss.parse("30 8 * * 1-5")
    assert weekdays.matches(datetime(2026, 11, 25, 8, 30))        # Wednesday
    assert not weekdays.matches(datetime(2026, 11, 29, 8, 30))    # Sunday
    sunday = ss.parse("0 0 * * 7")
    assert sunday.matches(datetime(2026, 11, 29, 0, 0))
    # Both day fields restricted: either matches.
    either = ss.parse("0 0 1 * 1")
    assert either.matches(datetime(2026, 12, 1, 0, 0))            # 1st, a Tuesday
    assert either.matches(datetime(2026, 11, 30, 0, 0))           # a Monday
    assert not either.matches(datetime(2026, 12, 2, 0, 0))


# --- due --------------------------------------------------------------------------

def test_hours_are_read_in_the_configured_zone():
    # 08:00 KST is 23:00 UTC the day before.
    anchor = kst(2026, 11, 25, 7, 0)
    assert not ss.is_due("0 8 * * *", anchor, kst(2026, 11, 25, 7, 59), SEOUL)
    assert ss.is_due("0 8 * * *", anchor, kst(2026, 11, 25, 8, 0), SEOUL)
    assert not ss.is_due("0 8 * * *", anchor, kst(2026, 11, 25, 8, 0), UTC)


def test_a_time_missed_while_the_node_was_off_runs_once():
    # Daily 06:00; last run Friday 07:31; the node is back Monday 07:30.
    friday = kst(2026, 11, 20, 7, 31)
    monday = kst(2026, 11, 23, 7, 30)
    assert ss.is_due("0 6 * * *", friday, monday, SEOUL)
    # Once run (anchor moves to now) it waits for the next 06:00.
    assert not ss.is_due("0 6 * * *", monday, monday + timedelta(hours=8), SEOUL)


def test_saving_a_schedule_does_not_run_it_at_once():
    saved = kst(2026, 11, 25, 7, 50)
    assert not ss.is_due("0 6 * * *", saved, saved + timedelta(minutes=5), SEOUL)
    assert not ss.is_due("garbage", None, saved, SEOUL)


def test_next_run_is_reported_in_utc_iso(monkeypatch):
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "Asia/Seoul")
    assert ss.next_run("0 8 * * *", kst(2026, 11, 25, 9, 0)) == kst(2026, 11, 26, 8, 0).isoformat()
    assert ss.next_run(None) is None and ss.next_run("nope") is None
    assert ss.zone_name() == "Asia/Seoul"
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "Mars/Olympus")
    assert ss.zone_name() == "UTC"


# --- the tick -------------------------------------------------------------------

class _Conn:
    def __init__(self, rows, users, sources):
        self.rows, self.users, self.sources = rows, users, sources
        self.updates = []

    async def fetchval(self, sql, *a):
        return True

    async def fetch(self, sql, *a):
        return self.rows

    async def fetchrow(self, sql, *a):
        if "FROM users" in sql:
            return self.users.get(a[0])
        # source_access.resolve
        return self.sources.get(str(a[0]))

    async def execute(self, sql, *a):
        self.updates.append((sql, a))


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *e):
                return False
        return Ctx()


CID_DUE = "00000000-0000-0000-0000-0000000000a1"
CID_LATER = "00000000-0000-0000-0000-0000000000a2"
CID_VIEWER = "00000000-0000-0000-0000-0000000000a3"
ENGINEER = "00000000-0000-0000-0000-00000000000e"
VIEWER = "00000000-0000-0000-0000-00000000000f"


def _setup(monkeypatch):
    monkeypatch.setattr(ss, "zone", lambda: SEOUL)
    audits = []

    async def record(**kw):
        audits.append(kw)
    from app import security_audit
    monkeypatch.setattr(security_audit, "record", record)
    anchor = kst(2026, 11, 25, 7, 0)
    rows = [
        {"id": CID_DUE, "name": "Orders", "schedule": "0 8 * * *", "schedule_anchor_at": anchor, "run_as": ENGINEER},
        {"id": CID_LATER, "name": "Later", "schedule": "0 17 * * *", "schedule_anchor_at": anchor, "run_as": ENGINEER},
        {"id": CID_VIEWER, "name": "Demoted", "schedule": "0 8 * * *", "schedule_anchor_at": anchor, "run_as": VIEWER},
    ]
    users = {ENGINEER: {"id": ENGINEER, "username": "kim", "role": "data_engineer", "is_active": True},
             VIEWER: {"id": VIEWER, "username": "lee", "role": "viewer", "is_active": True}}
    sources = {cid: {"id": cid, "owner_id": ENGINEER, "member_role": None} for cid in (CID_DUE, CID_LATER, CID_VIEWER)}
    return _Conn(rows, users, sources), audits


def test_tick_runs_due_sources_as_whoever_set_them(monkeypatch):
    conn, audits = _setup(monkeypatch)
    ran = []

    async def sync(cid, principal):
        ran.append((cid, principal["username"]))
        return "success: Synced 3 tables (120 rows)"

    n = asyncio.run(ss.tick(_Pool(conn), now=kst(2026, 11, 25, 8, 1), sync=sync))
    assert n == 1 and ran == [(CID_DUE, "kim")]
    statuses = {a[0]: a[1] for sql, a in conn.updates if "schedule_last_status = $2" in sql}
    assert statuses[CID_DUE].startswith("success")
    # The viewer no longer holds connector:write: skipped, said why, audited.
    assert "connector:write" in statuses[CID_VIEWER]
    assert audits and audits[0]["outcome"] == "denied" and audits[0]["permission"] == "connector:write"
    assert CID_LATER not in statuses
    # Claimed before running, so a crash is not retried every tick.
    claims = [a[0] for sql, a in conn.updates if "schedule_anchor_at = now()" in sql]
    assert claims == [CID_DUE, CID_VIEWER]


def test_a_failed_sync_is_recorded_not_raised(monkeypatch):
    conn, _ = _setup(monkeypatch)
    conn.rows = conn.rows[:1]

    async def sync(cid, principal):
        raise RuntimeError("source unreachable")

    assert asyncio.run(ss.tick(_Pool(conn), now=kst(2026, 11, 25, 8, 1), sync=sync)) == 0
    status = [a[1] for sql, a in conn.updates if "schedule_last_status = $2" in sql][0]
    assert status == "error: source unreachable"


def test_a_gone_user_skips(monkeypatch):
    conn, audits = _setup(monkeypatch)
    conn.rows = [dict(conn.rows[0], run_as=None)]
    asyncio.run(ss.tick(_Pool(conn), now=kst(2026, 11, 25, 8, 1), sync=None))
    status = [a[1] for sql, a in conn.updates if "schedule_last_status = $2" in sql][0]
    assert "no longer an active user" in status and audits


def test_scheduled_sync_capability_needs_no_airflow():
    from app.capabilities import compute_capabilities as build_capabilities
    env = {"FEATURE_TRINO": "true", "FEATURE_CONNECTORS": "true"}
    caps = build_capabilities(env)
    assert caps["scheduled_sync"] is caps["connectors"]
    assert build_capabilities({**env, "SYNC_SCHEDULER_ENABLED": "false"})["scheduled_sync"] is False
