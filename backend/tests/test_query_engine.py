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
    res = asyncio.get_event_loop().run_until_complete(q.execute_query(_Req(), db=None, user={"id": "00000000-0000-0000-0000-0000000000aa"}))
    assert res.columns == ["id", "name"] and res.rows == [[1, "a"]] and res.row_count == 1
