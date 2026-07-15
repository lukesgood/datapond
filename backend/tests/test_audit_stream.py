"""
Unit tests for the unified audit stream (/governance/audit-stream).

Merges query_history + auth_audit_log + connector_sync_history into one
time-ordered feed. Pins: admin-only gate, cross-source time ordering, per-source
best-effort (a failing source is omitted from `sources`, the rest still return,
session rolled back), the source filter, and input validation.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import app.api.governance as gov

ADMIN = {"id": "u1", "role": "admin"}
VIEWER = {"id": "u2", "role": "viewer"}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _stub_admin_gate(monkeypatch):
    """Replace the RLS-coupled _require_admin with a role check, so stream tests
    don't depend on the RLS loader / _RLS_ADMIN_OK. (Real gate covered by the
    non-admin test, which asserts a role!=admin is rejected.)"""
    async def _fake(user):
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required")
        return user
    monkeypatch.setattr(gov, "_require_admin", _fake)


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows_by_table, fail_tables=None):
        self.rows_by_table = rows_by_table
        self.fail_tables = fail_tables or set()
        self.rolled_back = 0

    def execute(self, stmt, params=None):
        sql = str(stmt)
        for tbl, rows in self.rows_by_table.items():
            if tbl in sql:
                if tbl in self.fail_tables:
                    raise RuntimeError(f"boom {tbl}")
                return _Result(rows)
        return _Result([])

    def rollback(self):
        self.rolled_back += 1


def _dt(day, tz=True):
    d = datetime(2026, 7, day, 12, 0, 0)
    return d.replace(tzinfo=timezone.utc) if tz else d


# query_history.created_at is naive (utcnow); auth is tz-aware (TIMESTAMPTZ);
# connector.started_at is naive (TIMESTAMP) — mix exercises _sort_epoch.
QUERY_ROWS = [_Row(id="q1", status="success", user_id="u1", catalog="AwsDataCatalog",
                   schema="sales", query_text="SELECT 1", created_at=_dt(3, tz=False))]
AUTH_ROWS = [_Row(id="a1", event_type="login", user_email="admin@x", user_id="u1",
                  resource=None, action="login", result="success",
                  failure_reason=None, created_at=_dt(5))]
CONN_ROWS = [_Row(id="c1", status="failed", rows_processed=0, rows_failed=3,
                  error_message="boom", started_at=_dt(4, tz=False), source_table="orders")]


def _db(fail=None):
    return _FakeDB({"query_history": QUERY_ROWS, "auth_audit_log": AUTH_ROWS,
                    "connector_sync_history": CONN_ROWS}, fail_tables=fail)


def _call(source=None, limit=100, user=ADMIN, db=None):
    return _run(gov.get_audit_stream(source=source, limit=limit, user=user, db=db or _db()))


def test_requires_admin():
    with pytest.raises(HTTPException) as e:
        _call(user=VIEWER)
    assert e.value.status_code == 403


def test_merges_all_sources_time_ordered():
    resp = _call()
    assert resp.sources == ["query", "auth", "connector"]
    # newest first across sources: auth(day5) > connector(day4) > query(day3)
    assert [i.id for i in resp.items] == ["a1", "c1", "q1"]
    assert resp.total == 3


def test_normalizes_each_source():
    by_id = {i.id: i for i in _call().items}
    assert by_id["q1"].event_type == "query_executed" and by_id["q1"].target == "AwsDataCatalog.sales"
    assert by_id["a1"].source == "auth" and by_id["a1"].actor == "admin@x"
    assert by_id["c1"].source == "connector" and by_id["c1"].detail == "boom" and by_id["c1"].target == "orders"


def test_source_filter_restricts():
    resp = _call(source="query")
    assert resp.sources == ["query"] and {i.source for i in resp.items} == {"query"}


def test_best_effort_skips_failing_source():
    db = _db(fail={"auth_audit_log"})
    resp = _call(db=db)
    assert "auth" not in resp.sources          # failed source omitted (not "clean")
    assert set(resp.sources) == {"query", "connector"}
    assert db.rolled_back == 1                  # session rolled back after the failure
    assert "a1" not in {i.id for i in resp.items}


def test_limit_validation():
    with pytest.raises(HTTPException) as e:
        _call(limit=0)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        _call(limit=9999)


def test_bad_source_rejected():
    with pytest.raises(HTTPException) as e:
        _call(source="nope")
    assert e.value.status_code == 400
