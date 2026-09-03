"""Policy coverage and the governance summary, for the assistant."""
import asyncio
import threading
from contextlib import contextmanager

from app.chat.analysis import governance as mod


def _run(c):
    return asyncio.run(c)


def test_policy_coverage_passes_the_caller(monkeypatch):
    seen = {}

    async def _fake(user=None):
        seen["user"] = user
        return {"covered": 3, "uncovered": 1}

    monkeypatch.setattr("app.api.governance.rls_coverage", _fake)
    user = {"id": "u1"}
    out = _run(mod.policy_coverage({}, user))
    assert seen["user"] is user
    assert out["coverage"]["covered"] == 3


class _FakeQuery:
    """Stands in for the `db.query(...).filter(...).scalar()` chain
    `get_governance_stats` runs for `queries_today`."""

    def __init__(self, value):
        self._value = value

    def filter(self, *a, **k):
        return self

    def scalar(self):
        return self._value


class _FakeSession:
    def __init__(self, queries_today=0):
        self._queries_today = queries_today

    def query(self, *a, **k):
        return _FakeQuery(self._queries_today)


def test_summary_stats_opens_and_closes_a_session(monkeypatch):
    """The DB work is sync and takes a Session as a Depends default. Called with no
    session it would receive a Depends object and fail inside SQLAlchemy."""
    closed = {"value": False}
    session = _FakeSession(queries_today=4)

    @contextmanager
    def _ctx():
        try:
            yield session
        finally:
            closed["value"] = True

    monkeypatch.setattr("app.database.connection.get_db_context", _ctx)
    monkeypatch.setattr("app.api.governance._scan_pii_tables", lambda: [])

    out = _run(mod.summary_stats({}, {"id": "u1"}))
    assert out["stats"]["queries_today"] == 4
    assert closed["value"] is True


# ── Important 3: "no scan ran" must not read as "0 detections" ─────────────────
# `get_governance_stats` (the route) computes `pii_detections = ... if pii_tables
# else 0`, so None (could not scan) and [] (scanned, clean) both become 0. This
# executor must tell them apart the same way `pii_summary` already does: an absent
# key plus a `not_checked` note, never a confident zero.

def test_summary_stats_omits_pii_detections_when_no_scan_could_run(monkeypatch):
    @contextmanager
    def _ctx():
        yield _FakeSession(queries_today=2)

    monkeypatch.setattr("app.database.connection.get_db_context", _ctx)
    monkeypatch.setattr("app.api.governance._scan_pii_tables", lambda: None)

    out = _run(mod.summary_stats({}, {"id": "u1"}))
    assert "pii_detections" not in out["stats"]
    assert out["stats"]["not_checked"]
    assert out["stats"]["queries_today"] == 2


def test_summary_stats_reports_pii_detections_when_a_scan_ran(monkeypatch):
    class _Entry:
        def __init__(self, n):
            self.pii_columns = list(range(n))

    @contextmanager
    def _ctx():
        yield _FakeSession(queries_today=0)

    monkeypatch.setattr("app.database.connection.get_db_context", _ctx)
    monkeypatch.setattr("app.api.governance._scan_pii_tables",
                        lambda: [_Entry(2), _Entry(1)])

    out = _run(mod.summary_stats({}, {"id": "u1"}))
    assert out["stats"]["pii_detections"] == 3
    assert "not_checked" not in out["stats"]


# ── Important 4: the sync scan must not run on the event loop ──────────────────
# `_scan_pii_tables()` can be a ~10s Trino connect or a sequential walk of up to 200
# Glue tables with a per-table S3 GET. The real routes are `def` (FastAPI runs them
# in a threadpool); these executors are `async def`, so without `asyncio.to_thread`
# that work lands on the event loop instead.

def test_summary_stats_runs_the_scan_off_the_event_loop(monkeypatch):
    caller_thread = threading.get_ident()
    seen = {}

    @contextmanager
    def _ctx():
        yield _FakeSession(queries_today=0)

    def _scan():
        seen["thread"] = threading.get_ident()
        return []

    monkeypatch.setattr("app.database.connection.get_db_context", _ctx)
    monkeypatch.setattr("app.api.governance._scan_pii_tables", _scan)

    _run(mod.summary_stats({}, {"id": "u1"}))
    assert seen["thread"] != caller_thread


def test_pii_summary_runs_the_scan_off_the_event_loop(monkeypatch):
    caller_thread = threading.get_ident()
    seen = {}

    def _scan():
        seen["thread"] = threading.get_ident()
        return None

    monkeypatch.setattr("app.api.governance._scan_pii_tables", _scan)

    _run(mod.pii_summary({}, {"id": "u1"}))
    assert seen["thread"] != caller_thread


def test_both_are_reads_on_governance_read():
    for action_id in ("governance.policy_coverage", "governance.summary_stats"):
        action = next(a for a in mod.ACTIONS if a.id == action_id)
        assert action.kind.value == "read"
        assert action.permission == "governance:read"
        assert action.capability is None
