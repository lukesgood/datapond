def test_get_engine_selection(monkeypatch):
    import app.api.query_engine as qe
    monkeypatch.setenv("QUERY_ENGINE", "athena")
    assert qe.get_engine().__class__.__name__ == "AthenaEngine"
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    assert qe.get_engine().__class__.__name__ == "TrinoEngine"
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    assert qe.get_engine().__class__.__name__ == "TrinoEngine"  # default


def test_engine_props():
    import app.api.query_engine as qe
    t, a = qe.TrinoEngine(), qe.AthenaEngine()
    assert t.rls_dialect == "trino" and a.rls_dialect == "athena"
    assert t.default_catalog == "iceberg" and a.default_catalog == "AwsDataCatalog"
    assert "Trino" in t.ai_dialect_prompt and "Athena" in a.ai_dialect_prompt
    assert t.ai_table_prefix == "iceberg" and a.ai_table_prefix == "AwsDataCatalog"


def test_trino_map_error():
    import app.api.query_engine as qe
    t = qe.TrinoEngine()
    st, detail, code = t.map_error(Exception('...message="Table x not found", query_id=1 TABLE_NOT_FOUND'))
    assert code == 400 and "Table not found" in detail
    st2, d2, c2 = t.map_error(Exception("query exceeded timeout"))
    assert st2 == "timeout" and c2 == 504


def test_athena_map_error():
    import app.api.query_engine as qe
    a = qe.AthenaEngine()
    st, detail, code = a.map_error(Exception("SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved"))
    assert code == 400 and ("Syntax" in detail or "column" in detail.lower())
    st2, d2, c2 = a.map_error(Exception("TABLE_NOT_FOUND: Table awsdatacatalog.db.t does not exist"))
    assert c2 in (400, 404) and "not found" in d2.lower()
    st3, d3, c3 = a.map_error(Exception("AccessDeniedException: not authorized"))
    assert c3 == 403


def test_execute_query_uses_engine(monkeypatch):
    import asyncio, app.api.queries as q

    class _Eng:
        default_catalog = "AwsDataCatalog"; default_schema = "db"; rls_dialect = "athena"
        def execute(self, sql, user): return [[1, "a"]], ["id", "name"]
        def map_error(self, exc): return ("error", "x", 400)
    monkeypatch.setattr(q, "get_engine", lambda: _Eng())
    monkeypatch.setattr(q, "RLS_ENABLED", False)

    class _Req:
        query = "select 1"; save_history = False
    res = asyncio.run(q.execute_query(_Req(), db=None, user={"id": "00000000-0000-0000-0000-0000000000aa"}))
    assert res.columns == ["id", "name"] and res.rows == [[1, "a"]] and res.row_count == 1


# ── Unqualified table resolution (app/api/table_resolver.py) ──────────────────
# `FROM orders` must become `FROM sales.orders` BEFORE RLS runs: RLS keys policies
# on the qualified name, so an unqualified reference would miss its policy and,
# with RLS_DEFAULT_DENY off, run unfiltered.

_UID = {"id": "00000000-0000-0000-0000-0000000000aa"}


class _RecordingEngine:
    default_catalog = "AwsDataCatalog"
    default_schema = "db"
    rls_dialect = "athena"

    def __init__(self):
        self.sql = None

    def execute(self, sql, user):
        self.sql = sql
        return [[1]], ["id"]

    def map_error(self, exc):
        return ("error", str(exc), 400)


def _index(tables, namespaces):
    from app.api.table_resolver import CatalogIndex
    return CatalogIndex(namespaces=tuple(namespaces),
                        tables={k: tuple(v) for k, v in tables.items()})


class _Req:
    def __init__(self, query):
        self.query = query
        self.save_history = False


def test_execute_query_qualifies_an_unqualified_table(monkeypatch):
    import asyncio, app.api.queries as q
    eng = _RecordingEngine()
    monkeypatch.setattr(q, "get_engine", lambda: eng)
    monkeypatch.setattr(q, "RLS_ENABLED", False)
    monkeypatch.setattr(q, "get_catalog_index", lambda: _index({"orders": ["sales"]}, ["sales"]))

    asyncio.run(q.execute_query(_Req("SELECT * FROM orders"), db=None, user=_UID))

    assert "sales.orders" in eng.sql


def test_execute_query_rejects_an_ambiguous_table_with_400(monkeypatch):
    import asyncio, pytest as _pytest, app.api.queries as q
    from fastapi import HTTPException
    monkeypatch.setattr(q, "get_engine", lambda: _RecordingEngine())
    monkeypatch.setattr(q, "RLS_ENABLED", False)
    monkeypatch.setattr(q, "get_catalog_index",
                        lambda: _index({"orders": ["sales", "ops"]}, ["sales", "ops"]))

    with _pytest.raises(HTTPException) as ei:
        asyncio.run(q.execute_query(_Req("SELECT * FROM orders"), db=None, user=_UID))

    assert ei.value.status_code == 400
    assert "sales.orders" in ei.value.detail and "ops.orders" in ei.value.detail


def test_execute_query_fails_closed_when_the_catalog_cannot_be_read(monkeypatch):
    """An unresolvable bare name must not reach the engine — that is the RLS gap."""
    import asyncio, pytest as _pytest, app.api.queries as q
    from fastapi import HTTPException
    eng = _RecordingEngine()
    monkeypatch.setattr(q, "get_engine", lambda: eng)
    monkeypatch.setattr(q, "RLS_ENABLED", False)

    def _boom():
        raise RuntimeError("glue unreachable")
    monkeypatch.setattr(q, "get_catalog_index", _boom)

    with _pytest.raises(HTTPException) as ei:
        asyncio.run(q.execute_query(_Req("SELECT * FROM orders"), db=None, user=_UID))

    assert ei.value.status_code == 400
    assert eng.sql is None


def test_execute_query_leaves_a_qualified_query_alone_without_reading_the_catalog(monkeypatch):
    import asyncio, app.api.queries as q
    eng = _RecordingEngine()
    monkeypatch.setattr(q, "get_engine", lambda: eng)
    monkeypatch.setattr(q, "RLS_ENABLED", False)

    def _boom():
        raise AssertionError("catalog must not be read for a qualified query")
    monkeypatch.setattr(q, "get_catalog_index", _boom)

    asyncio.run(q.execute_query(_Req("SELECT * FROM sales.orders"), db=None, user=_UID))

    assert "sales.orders" in eng.sql


def test_rls_sees_the_qualified_table_name(monkeypatch):
    """Regression: a policy on sales.orders must apply to `FROM orders`."""
    import asyncio, types, app.api.queries as q
    eng = _RecordingEngine()
    monkeypatch.setattr(q, "get_engine", lambda: eng)
    monkeypatch.setattr(q, "get_catalog_index", lambda: _index({"orders": ["sales"]}, ["sales"]))
    monkeypatch.setattr(q, "RLS_ENABLED", True)
    monkeypatch.setattr(q, "_RLS_IMPORTS_OK", True)

    seen = {}

    def _enforce(sql, ctx, policies, masks, dialect="trino"):
        seen["sql"] = sql
        return types.SimpleNamespace(sql=sql)

    class _Loader:
        async def load_user_context(self, user):
            return types.SimpleNamespace(username="u")

        async def load_policies(self):
            return []

        async def load_masks(self):
            return []

    monkeypatch.setattr(q, "enforce", _enforce)
    monkeypatch.setattr(q, "rls_loader", _Loader())

    asyncio.run(q.execute_query(_Req("SELECT * FROM orders"), db=None, user=_UID))

    assert "sales.orders" in seen["sql"], "RLS must receive the qualified name"
