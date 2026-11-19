"""Streaming DDL: names are identifiers, values are escaped literals, credentials
never come back out of rw_catalog definitions, and view rows need pipeline:write."""
import asyncio

import pytest
from fastapi import HTTPException

import app.api.streaming as s


def test_ident_refuses_anything_but_plain_names():
    assert s._ident("orders_cdc") == "orders_cdc"
    for bad in ("x; DROP SINK y", "a b", "1x", "", "x" * 64, 'x"'):
        with pytest.raises(HTTPException):
            s._ident(bad)


def test_literal_doubles_quotes():
    assert s._lit("pa'ss") == "'pa''ss'"
    assert s._props_sql({"password": "a'); DROP SOURCE x; --"}) == "password = 'a''); DROP SOURCE x; --'"
    with pytest.raises(HTTPException):
        s._props_sql({"bad key = 'x', other": "v"})


def test_redact_hides_passwords_and_keys():
    d = ("CREATE SOURCE x WITH (connector = 'postgres-cdc', hostname = 'db', password = 'it''s secret', "
         "username = 'etl', s3.secret.key = 'SK', s3.access.key = 'AK', table.name = 't')")
    out = s._redact(d)
    for leaked in ("it''s secret", "'SK'", "'AK'"):
        assert leaked not in out
    assert "hostname = 'db'" in out and "username = 'etl'" in out and "table.name = 't'" in out
    assert s._redact(None) is None


def test_lists_redact_definitions(monkeypatch):
    monkeypatch.setattr(s, "_execute", lambda sql, fetch=True: [
        {"name": "x", "definition": "CREATE SOURCE x WITH (password = 'hunter2')"}])
    for fn in (s.list_sources, s.list_sinks, s.list_cdc_pipelines):
        rows = asyncio.run(fn())
        assert "hunter2" not in rows[0]["definition"]


def test_preview_refuses_sql_in_the_name_and_clamps_limit(monkeypatch):
    seen = []
    monkeypatch.setattr(s, "_execute", lambda sql, fetch=True: seen.append(sql) or [])
    with pytest.raises(HTTPException):
        asyncio.run(s.preview_view("x; DROP TABLE y", 10))
    asyncio.run(s.preview_view("orders_mv", 100000))
    assert seen == ["SELECT * FROM orders_mv LIMIT 500"]


def test_preview_needs_pipeline_write():
    route = next(r for r in s.router.routes
                 if getattr(r, "path", "") == "/streaming/views/{name}/data")
    assert route.dependencies, "preview must carry a permission dependency"


def test_cdc_pipeline_escapes_password_and_returns_no_ddl(monkeypatch):
    ran = []
    monkeypatch.setattr(s, "_execute", lambda sql, fetch=True: ran.append(sql) or [])
    req = s.CdcPipelineRequest(pipeline_name="orders", tables=["customers"], db_host="db",
                               db_name="shop", db_user="etl", db_password="pa'ss")
    out = asyncio.run(s.create_cdc_pipeline(req, {"id": "u"}))
    assert out["tables_success"] == 1 and "sqls" not in out["results"][0]
    assert "password = 'pa''ss'" in ran[0]
    with pytest.raises(HTTPException):
        asyncio.run(s.create_cdc_pipeline(
            s.CdcPipelineRequest(pipeline_name="orders", tables=["x; DROP SOURCE y"], db_host="db",
                                 db_name="shop", db_user="etl"), {"id": "u"}))


def test_cdc_needs_a_source_or_a_connection():
    with pytest.raises(HTTPException):
        asyncio.run(s._db_target(s.CdcTestRequest(), {"id": "u"}))
