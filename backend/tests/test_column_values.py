"""Data Map step 3b: one column's values (app/column_values.py + the route)."""
import asyncio

import pytest

from app import column_values as cv


def test_listable_types():
    for t in ("varchar", "varchar(20)", "bigint", "integer", "boolean", "date", "decimal(10,2)", "uuid"):
        assert cv.listable(t), t
    for t in ("array(varchar)", "map(varchar,integer)", "row(a int)", "varbinary", "json",
              "timestamp(6)", "double", "", None):
        assert not cv.listable(t), t


def test_find_column_uses_the_tables_spelling():
    cols = [{"name": "Status", "type": "varchar"}]
    assert cv.find_column(cols, "status")["name"] == "Status"
    assert cv.find_column(cols, 'status"; drop') is None


def test_statements_quote_the_column():
    counts, top = cv.statements("default.orders", 'we"ird')
    assert '"we""ird"' in counts and "approx_distinct" in counts
    assert top.endswith(f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {cv.TOP}")
    assert "approx_distinct" not in cv.counts_only("default.orders", "email")


class _Res:
    def __init__(self, columns, rows):
        self.columns, self.rows = columns, rows


@pytest.fixture
def route(monkeypatch):
    import app.api.catalog as catalog
    import app.table_profile as tp

    class Reader:
        def get_columns(self, ns, t):
            return [{"name": "status", "type": "varchar"}, {"name": "email", "type": "varchar"},
                    {"name": "tags", "type": "array(varchar)"}]

    class Entry:
        name = engine_catalog = "iceberg"
        is_default = True

    class Access:
        def resolve(self, c):
            return Entry()

    sent = []

    async def execute_query(req, db, user):
        sent.append(req.query)
        if "approx_distinct" in req.query:
            return _Res(["total", "non_null", "distinct_est"], [[6000, 5990, 5]])
        if req.query.startswith("SELECT count(*)"):
            return _Res(["total", "non_null"], [[6000, 6000]])
        return _Res(["value", "n"], [["delivered", 2953], ["pending", 1030], [None, 10]])

    async def for_caller(user):
        return Access()

    async def governance(user, cat, ns, t):
        return {"restricted": False, "masked": {"email"} if user.get("masked") else set()}

    async def pii_columns(cat, ns, t):
        return {"email"}

    monkeypatch.setattr(catalog, "get_catalog_reader", lambda name: Reader())
    monkeypatch.setattr(catalog, "execute_query", execute_query)
    monkeypatch.setattr(catalog.catalog_access, "for_caller", for_caller)
    monkeypatch.setattr(tp, "governance", governance)
    monkeypatch.setattr(tp, "pii_columns", pii_columns)
    return catalog.column_values, sent


def test_values_through_the_governed_path(route):
    fn, sent = route
    r = asyncio.run(fn("default", "orders", "STATUS", None, db=None, user={"role": "viewer"}))
    assert r["column"] == "status" and r["hidden"] is False
    assert r["values"][:2] == [{"value": "delivered", "rows": 2953}, {"value": "pending", "rows": 1030}]
    assert r["values"][2] == {"value": None, "rows": 10}
    assert r["nulls"] == 10 and r["distinct"] == 5
    assert len(sent) == 2 and all('"status"' in s for s in sent)


def test_pii_column_returns_counts_only(route):
    fn, sent = route
    r = asyncio.run(fn("default", "orders", "email", None, db=None, user={"role": "viewer"}))
    assert r["hidden"] is True and r["values"] == [] and "PII" in r["reason"]
    assert len(sent) == 1 and "GROUP BY" not in sent[0]


def test_unlisted_type_and_unknown_column(route):
    from fastapi import HTTPException
    fn, _ = route
    r = asyncio.run(fn("default", "orders", "tags", None, db=None, user={"role": "viewer"}))
    assert r["hidden"] is True and "array" in r["reason"]
    with pytest.raises(HTTPException) as e:
        asyncio.run(fn("default", "orders", "nope", None, db=None, user={"role": "viewer"}))
    assert e.value.status_code == 404
