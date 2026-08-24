"""POST /queries/plan — review a statement without running it.

Answers "what will this actually read" before the user hits execute. Bare table
names are resolved first, exactly as execute_query does, or EXPLAIN would fail on
names the engine cannot resolve.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.queries as q
from app.api.table_resolver import CatalogIndex

USER = {"id": "00000000-0000-0000-0000-0000000000aa"}
IO_ONE_TABLE = """{
  "inputTableColumnInfos": [
    {"table": {"schemaTable": {"schema": "sales", "table": "orders"}},
     "constraint": {"columnConstraints": []},
     "estimate": {"outputRowCount": "NaN"}}
  ]
}"""


def _index():
    return CatalogIndex(namespaces=("sales",), tables={"orders": ("sales",)})


class _Req:
    def __init__(self, sql, deep=False):
        self.sql = sql
        self.deep = deep


def test_plan_reports_the_tables_the_query_reads(monkeypatch):
    monkeypatch.setattr(q, "get_catalog_index", _index)
    monkeypatch.setattr(q, "explain_statement",
                        lambda sql, kind="IO, FORMAT JSON": (True, None, IO_ONE_TABLE))

    res = asyncio.run(q.review_plan(_Req("SELECT * FROM sales.orders"), user=USER))

    assert [f"{t['schema']}.{t['table']}" for t in res["accessed"]] == ["sales.orders"]
    assert res["validated"] is True


def test_plan_resolves_a_bare_table_name_before_explaining(monkeypatch):
    seen = {}

    def _explain(sql, kind="IO, FORMAT JSON"):
        seen["sql"] = sql
        return True, None, IO_ONE_TABLE

    monkeypatch.setattr(q, "get_catalog_index", _index)
    monkeypatch.setattr(q, "explain_statement", _explain)

    asyncio.run(q.review_plan(_Req("SELECT * FROM orders"), user=USER))

    assert "sales.orders" in seen["sql"], "EXPLAIN cannot resolve a bare name"


def test_plan_returns_the_engine_error_for_invalid_sql(monkeypatch):
    monkeypatch.setattr(q, "get_catalog_index", _index)
    monkeypatch.setattr(q, "explain_statement",
                        lambda sql, kind="IO, FORMAT JSON": (False, "COLUMN_NOT_FOUND: nope", ""))

    res = asyncio.run(q.review_plan(_Req("SELECT nope FROM sales.orders"), user=USER))

    assert res["validated"] is False
    assert "COLUMN_NOT_FOUND" in res["validation_error"]
    assert res["accessed"] == []


def test_plan_skips_the_second_round_trip_unless_asked(monkeypatch):
    kinds = []

    def _explain(sql, kind="IO, FORMAT JSON"):
        kinds.append(kind)
        return True, None, IO_ONE_TABLE

    monkeypatch.setattr(q, "get_catalog_index", _index)
    monkeypatch.setattr(q, "explain_statement", _explain)

    asyncio.run(q.review_plan(_Req("SELECT * FROM sales.orders"), user=USER))
    assert len(kinds) == 1

    kinds.clear()
    asyncio.run(q.review_plan(_Req("SELECT * FROM sales.orders", deep=True), user=USER))
    assert len(kinds) == 2 and any("DISTRIBUTED" in k for k in kinds)


def test_plan_rejects_an_empty_statement(monkeypatch):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(q.review_plan(_Req("   "), user=USER))
    assert ei.value.status_code == 400
