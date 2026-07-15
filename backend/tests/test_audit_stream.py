"""
Unit tests for the unified audit stream (/governance/audit-stream).

Merges query_history + auth_audit_log + connector_sync_history into one
time-ordered feed. Pins: cross-source time ordering, per-source best-effort (a
failing source is omitted from `sources`, the rest still return, session rolled
back), the source filter, and input validation.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import app.api.governance as gov


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


QUERY_ROWS = [_Row(id="q1", status="success", user_id="u1", catalog="AwsDataCatalog",
                   schema="sales", query_text="SELECT 1", created_at=_dt(3))]
AUTH_ROWS = [_Row(id="a1", event_type="login", user_email="admin@x", user_id="u1",
                  resource=None, action="login", result="success",
                  failure_reason=None, created_at=_dt(5))]
# connector uses naive timestamps (TIMESTAMP column) — must still sort correctly
CONN_ROWS = [_Row(id="c1", status="failed", rows_processed=0, rows_failed=3,
                  error_message="boom", started_at=_dt(4, tz=False), source_table="orders")]


def _db(fail=None):
    return _FakeDB({"query_history": QUERY_ROWS, "auth_audit_log": AUTH_ROWS,
                    "connector_sync_history": CONN_ROWS}, fail_tables=fail)


def test_merges_all_sources_time_ordered():
    resp = gov.get_audit_stream(source=None, limit=100, db=_db())
    assert resp.sources == ["query", "auth", "connector"]
    # newest first: auth(day5) > connector(day4) > query(day3)
    assert [i.id for i in resp.items] == ["a1", "c1", "q1"]
    assert resp.total == 3


def test_normalizes_each_source():
    resp = gov.get_audit_stream(source=None, limit=100, db=_db())
    by_id = {i.id: i for i in resp.items}
    assert by_id["q1"].event_type == "query_executed" and by_id["q1"].target == "AwsDataCatalog.sales"
    assert by_id["a1"].source == "auth" and by_id["a1"].actor == "admin@x"
    assert by_id["c1"].source == "connector" and by_id["c1"].detail == "boom" and by_id["c1"].target == "orders"


def test_source_filter_restricts():
    resp = gov.get_audit_stream(source="query", limit=100, db=_db())
    assert resp.sources == ["query"] and {i.source for i in resp.items} == {"query"}


def test_best_effort_skips_failing_source():
    db = _db(fail={"auth_audit_log"})
    resp = gov.get_audit_stream(source=None, limit=100, db=db)
    assert "auth" not in resp.sources          # failed source omitted (not "clean")
    assert set(resp.sources) == {"query", "connector"}
    assert db.rolled_back == 1                  # session rolled back after the failure
    assert "a1" not in {i.id for i in resp.items}


def test_limit_validation():
    with pytest.raises(HTTPException) as e:
        gov.get_audit_stream(source=None, limit=0, db=_db())
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        gov.get_audit_stream(source=None, limit=9999, db=_db())


def test_bad_source_rejected():
    with pytest.raises(HTTPException) as e:
        gov.get_audit_stream(source="nope", limit=10, db=_db())
    assert e.value.status_code == 400
