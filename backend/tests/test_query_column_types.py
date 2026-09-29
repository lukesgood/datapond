"""A query result says what kind of value each column holds.

The console picked chart axes by position — first column on X, second on Y — because
the result carried column names only. A second column of text drew an empty chart, and
a date column was treated like any label. Trino and Athena both report each column's
type in the cursor description; the result now carries it, normalised to the handful
of kinds a chart can use.
"""
import asyncio

import pytest

from app.api import queries
from app.api.query_engine import TrinoEngine, column_kind
from app.schemas.query import QueryExecuteRequest


@pytest.mark.parametrize("engine_type,kind", [
    ("bigint", "quantitative"), ("integer", "quantitative"), ("double", "quantitative"),
    ("decimal(18,2)", "quantitative"), ("real", "quantitative"), ("tinyint", "quantitative"),
    ("date", "temporal"), ("timestamp(3)", "temporal"),
    ("timestamp(6) with time zone", "temporal"), ("time", "temporal"),
    ("boolean", "boolean"),
    ("varchar", "text"), ("varchar(255)", "text"), ("char(2)", "text"), ("json", "text"),
    ("uuid", "text"),
    ("array(varchar)", "other"), ("map(varchar,bigint)", "other"), ("row(a bigint)", "other"),
    ("varbinary", "other"), (None, "unknown"), ("", "unknown"),
])
def test_engine_types_normalise_to_chartable_kinds(engine_type, kind):
    assert column_kind(engine_type) == kind


class _Cursor:
    description = [("day", "date", None, None, None, None, None),
                   ("orders", "bigint", None, None, None, None, None)]

    def execute(self, sql):
        pass

    def fetchall(self):
        return [["2026-09-01", 3]]

    def close(self):
        pass


class _Conn:
    def cursor(self):
        return _Cursor()

    def close(self):
        pass


def test_the_trino_engine_reports_its_column_types(monkeypatch):
    monkeypatch.setattr(queries, "get_trino_connection", lambda user: _Conn())
    engine = TrinoEngine()
    rows, cols = engine.execute("SELECT 1", "u")
    assert cols == ["day", "orders"]
    assert engine.column_types == ["temporal", "quantitative"]


class _FakeEngine:
    default_catalog, default_schema, rls_dialect = "iceberg", "default", "trino"

    def execute(self, sql, user):
        self.column_types = ["temporal", "quantitative"]
        return [["2026-09-01", 3]], ["day", "orders"]


def test_the_execute_route_returns_the_kinds(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "off")
    monkeypatch.setattr(queries, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(queries, "RLS_ENABLED", False)
    req = QueryExecuteRequest(query="SELECT day, orders FROM sales.daily", save_history=False)
    user = {"id": "11111111-1111-1111-1111-111111111111", "role": "analyst"}
    result = asyncio.run(queries._execute_query_impl(req, None, user))
    assert result.column_types == ["temporal", "quantitative"]


def test_an_engine_that_reports_nothing_yields_unknowns(monkeypatch):
    class _Silent(_FakeEngine):
        def execute(self, sql, user):
            return [["x", 1]], ["a", "b"]
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "off")
    monkeypatch.setattr(queries, "get_engine", lambda: _Silent())
    monkeypatch.setattr(queries, "RLS_ENABLED", False)
    req = QueryExecuteRequest(query="SELECT a, b FROM s.t", save_history=False)
    user = {"id": "11111111-1111-1111-1111-111111111111", "role": "analyst"}
    result = asyncio.run(queries._execute_query_impl(req, None, user))
    assert result.column_types == ["unknown", "unknown"]
