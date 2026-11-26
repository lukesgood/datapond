"""Scheduled-sync failure alerts (app/sync_alerts.py), the all-tables sync status, and the
Overview item for a scheduled run that never synced (app/ops_status.py)."""
import asyncio
from datetime import datetime, timezone

from app import sync_alerts as sa
from app import sync_scheduler as ss
from app.ops_status import schedule_problem, summarize


def test_only_the_turn_from_working_to_failing_alerts():
    assert sa.should_alert(None, "failed: 1 of 3 tables failed: orders")
    assert sa.should_alert("success: Synced 3 tables", "error: source unreachable")
    assert sa.should_alert("running", "skipped: whoever set this schedule is no longer an active user")
    assert not sa.should_alert("failed: x", "error: y")          # still broken: no second email
    assert not sa.should_alert("error: y", "success: Synced 3 tables")
    assert not sa.should_alert(None, "success: Synced 3 tables")


def test_the_email_says_what_happened_and_links_the_source(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://dp.example.com/")
    url = sa.source_url("abc")
    assert url == "https://dp.example.com/connectors/connections/abc"
    subject, text, html = sa.alert_email("Orders <db>", "failed: 1 of 3 tables failed: orders", url)
    assert subject == "The scheduled sync of Orders <db> failed"
    assert "1 of 3 tables failed: orders." in text and url in text
    assert "Orders &lt;db&gt;" in html and "<db>" not in html
    subject, text, _ = sa.alert_email("Orders", "skipped: whoever set this schedule may no longer change this source", None)
    assert "did not run" in subject and "save its schedule again" in text
    monkeypatch.delenv("APP_BASE_URL")
    assert sa.source_url("abc") is None


class _Conn:
    def __init__(self, users):
        self.users = users

    async def fetchrow(self, sql, *a):
        return self.users.get(a[0])


def test_the_owner_is_told_when_the_schedule_setter_is_gone():
    sent = []
    users = {"setter": {"email": "a@x", "is_active": False}, "owner": {"email": "o@x", "is_active": True}}

    def send(to, subject, text, html):
        sent.append(to)
        return True
    ok = asyncio.run(sa.notify(_Conn(users), connection_id="c", source="S", status="error: boom",
                               run_as="setter", owner_id="owner", send=send))
    assert ok and sent == ["o@x"]
    assert not asyncio.run(sa.notify(_Conn({}), connection_id="c", source="S", status="error: boom",
                                     run_as="setter", owner_id=None, send=send))


def test_a_mailer_that_raises_never_stops_the_scheduler():
    def send(*a):
        raise RuntimeError("SES down")
    users = {"u": {"email": "u@x", "is_active": True}}
    assert asyncio.run(sa.notify(_Conn(users), connection_id="c", source="S", status="error: x",
                                 run_as="u", owner_id=None, send=send)) is False


# --- the scheduler sends once, on the turn ------------------------------------

from tests.test_sync_scheduler import _Pool, _setup, kst, CID_DUE  # noqa: E402


def _tick(monkeypatch, previous, result):
    conn, _ = _setup(monkeypatch)
    conn.rows = [dict(conn.rows[0], schedule_last_status=previous, owner_id=None)]
    conn.users[conn.rows[0]["run_as"]]["email"] = "kim@x"
    sent = []

    async def sync(cid, principal):
        return result

    def send(to, subject, text, html):
        sent.append((to, subject))
        return True
    asyncio.run(ss.tick(_Pool(conn), now=kst(2026, 11, 25, 8, 1), sync=sync, send=send))
    return sent


def test_the_scheduler_emails_when_a_working_source_fails(monkeypatch):
    sent = _tick(monkeypatch, "success: Synced 3 tables", "failed: 1 of 3 tables failed: orders")
    assert sent == [("kim@x", "The scheduled sync of Orders failed")]


def test_the_scheduler_stays_quiet_while_a_source_keeps_failing_or_works(monkeypatch):
    async def not_fixed(c, cid, anchor):
        return False
    monkeypatch.setattr(sa, "fixed_since", not_fixed)
    assert _tick(monkeypatch, "failed: 1 of 3 tables failed: orders", "failed: 1 of 3 tables failed: orders") == []
    assert _tick(monkeypatch, None, "success: Synced 3 tables") == []


# --- Overview ---------------------------------------------------------------

def test_overview_lists_a_scheduled_run_that_never_synced():
    assert schedule_problem("skipped: no longer an active user") == "skipped"
    assert schedule_problem("error: Sync failed: timeout") == "error"
    assert schedule_problem("failed: 1 of 3 tables failed") is None   # listed per table already
    assert schedule_problem("success: ok") is None and schedule_problem(None) is None
    now = datetime(2026, 11, 26, tzinfo=timezone.utc)
    out = summarize([], {}, stale=[], engine=None, catalogs=[], mirrors=[], queries_24h=0, now=now,
                    schedules=[{"connection_id": "c1", "name": "Orders", "status": "skipped: no longer an active user"},
                           {"connection_id": "c2", "name": "Fine", "status": "success: Synced 2 tables"}])
    assert out["issues"] == [{"kind": "schedule_failed", "connection_id": "c1", "source": "Orders",
                              "reason": "skipped", "detail": "no longer an active user"}]
    assert out["state"] == "attention"


# --- one failed table fails an all-tables run ------------------------------------

def test_an_all_tables_run_with_one_failed_table_reports_failed(monkeypatch):
    from app.connectors.base import SyncJobStatus, SyncStatus
    from tests.test_connector_collect_integrity import SYNC_USER, _afn, _patch_api
    from app import sync_plan
    store = {"watermark_row": None, "existing_id": None, "executes": []}
    C = _patch_api(monkeypatch, store, {})
    monkeypatch.setattr(C, "_discover_tables", _afn(["customers", "orders", "items"]))
    monkeypatch.setattr(sync_plan, "heal", _afn(None))

    async def swr(connector, on_retry=None, **kw):
        bad = kw["source_table"] == "orders"
        return SyncJobStatus(job_id=None, status=SyncStatus.FAILED if bad else SyncStatus.SUCCESS,
                             started_at=datetime.utcnow(), completed_at=datetime.utcnow(),
                             rows_processed=0 if bad else 5, rows_failed=0,
                             error_message="boom" if bad else None)
    monkeypatch.setattr(C, "_sync_with_retry", swr)
    for name in ("_persist_sync_job", "_record_sync_outcome", "_persist_sync_session"):
        monkeypatch.setattr(C, name, _afn(None))
    res = asyncio.run(C.trigger_sync("11111111-1111-1111-1111-111111111111", C.SyncRequest(), SYNC_USER))
    assert res["status"] == "failed"            # the last table (items) succeeded
    assert res["failed_tables"] == ["orders"]
    assert res["message"] == "1 of 3 tables failed: orders"


def test_a_new_failure_after_a_manual_fix_emails_again(monkeypatch):
    async def fixed(c, cid, anchor):
        return True
    monkeypatch.setattr(sa, "fixed_since", fixed)
    sent = _tick(monkeypatch, "failed: 1 of 3 tables failed: orders", "error: source unreachable")
    assert sent == [("kim@x", "The scheduled sync of Orders failed")]


def test_still_failing_with_no_fix_in_between_stays_quiet(monkeypatch):
    async def not_fixed(c, cid, anchor):
        return False
    monkeypatch.setattr(sa, "fixed_since", not_fixed)
    assert _tick(monkeypatch, "error: x", "error: y") == []
