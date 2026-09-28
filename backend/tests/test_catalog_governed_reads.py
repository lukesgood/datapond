"""The catalog routes read what the governed query path governs.

The preview returned `SELECT * … LIMIT 500` through its own reader: no permission, no
RLS, no masking, no audit. A key scoped to `knowledge:read` could read any table's
unmasked rows by asking for a preview instead of a query. And the Trino reader
formatted namespace and table straight into SQL, so the same call — or the MCP tool
that describes a table — could carry a UNION into another table.
"""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.catalog as catalog
from app.api.catalog_backend import PolarisCatalogReader
from app.api.queries import QueryResult


def _run(coro):
    return asyncio.run(coro)


def _markers(route):
    found, seen = set(), set()

    def walk(dependant):
        if id(dependant) in seen:
            return
        seen.add(id(dependant))
        marker = getattr(dependant.call, "__datapond_authorization__", None)
        if marker:
            found.add(marker)
        for sub in dependant.dependencies:
            walk(sub)

    walk(route.dependant)
    return found


def _route(path):
    import main
    return next(r for r in main.app.routes if getattr(r, "path", None) == path)


@pytest.mark.parametrize("path", [
    "/api/catalog/namespaces",
    "/api/catalog/tables",
    "/api/catalog/tables/{namespace}/{table}",
    "/api/catalog/schemas",
    "/api/catalog/columns",
    "/api/catalog/relationships",
])
def test_catalog_metadata_needs_catalog_read(path):
    assert "catalog:read" in _markers(_route(path))


def test_the_preview_needs_what_a_query_needs():
    assert {"catalog:read", "query:run"} <= _markers(
        _route("/api/catalog/tables/{namespace}/{table}/preview"))


def test_the_preview_runs_through_the_governed_query_path(monkeypatch):
    seen = {}

    async def governed(request, db, user):
        seen["sql"] = request.query
        seen["user"] = user
        # What comes back is already masked; the stats must be computed on it.
        return QueryResult(columns=["id", "phone"], rows=[[1, "***"], [2, None]],
                           execution_time_ms=1.0, row_count=2, pii_masked=1)

    def raw_reader():
        raise AssertionError("the preview must not read rows around the governed path")

    monkeypatch.setattr(catalog, "execute_query", governed)
    monkeypatch.setattr(catalog, "get_catalog_reader", raw_reader)

    user = {"id": "u-1", "role": "viewer"}
    out = _run(catalog.preview_table("sales", "orders", limit=10, db=None, user=user))

    assert seen["sql"] == "SELECT * FROM sales.orders LIMIT 10"
    assert seen["user"] is user
    assert out["rows"] == [{"id": 1, "phone": "***"}, {"id": 2, "phone": None}]
    phone = next(s for s in out["column_stats"] if s["column"] == "phone")
    assert phone["null_count"] == 1 and phone["max"] == "***"


@pytest.mark.parametrize("namespace,table", [
    ("sales", "orders LIMIT 1 UNION SELECT * FROM hr.salaries"),
    ("x' OR '1'='1", "orders"),
    ("sales", "orders;DROP TABLE t"),
])
def test_the_preview_refuses_anything_but_bare_identifiers(monkeypatch, namespace, table):
    async def governed(*a, **k):
        raise AssertionError("an unsafe name must not reach the engine")
    monkeypatch.setattr(catalog, "execute_query", governed)
    with pytest.raises(HTTPException) as exc:
        _run(catalog.preview_table(namespace, table, limit=10, db=None,
                                   user={"id": "u-1", "role": "viewer"}))
    assert exc.value.status_code == 400


def test_the_preview_caps_its_limit(monkeypatch):
    seen = {}

    async def governed(request, db, user):
        seen["sql"] = request.query
        return QueryResult(columns=[], rows=[], execution_time_ms=0, row_count=0)

    monkeypatch.setattr(catalog, "execute_query", governed)
    _run(catalog.preview_table("sales", "orders", limit=100000, db=None,
                               user={"id": "u-1", "role": "viewer"}))
    assert seen["sql"].endswith("LIMIT 500")


@pytest.mark.parametrize("method", ["get_columns", "get_location", "row_count", "preview"])
def test_the_trino_reader_never_formats_an_unsafe_name(monkeypatch, method):
    import app.api.trino_util as trino_util

    def no_connection(*a, **k):
        raise AssertionError("an unsafe name must not reach Trino")

    monkeypatch.setattr(trino_util, "trino_conn", no_connection)
    reader = PolarisCatalogReader()
    args = ("sales", "x' UNION SELECT a,b,'YES' FROM other.t --")
    if method == "preview":
        args += (10,)
    with pytest.raises(ValueError):
        getattr(reader, method)(*args)
