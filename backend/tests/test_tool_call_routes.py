from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, tool_call_routes

_REAL_REQUIRE_USER = auth.require_user
AUDITOR = {"id": "33333333-3333-3333-3333-333333333333", "username": "aud", "role": "auditor",
           "permissions": {"audit:read"}}


def _app():
    app = FastAPI()
    app.include_router(tool_call_routes.router, prefix="/api")

    async def _override():
        return AUDITOR
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


class _Conn:
    def __init__(self, rows, total):
        self.rows, self.total, self.sql = rows, total, []

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return self.rows

    async def fetchval(self, sql, *args):
        return self.total

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _patch(monkeypatch, conn):
    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(tool_call_routes, "get_db_pool", _pool)


def _row():
    return {"id": 1, "occurred_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
            "actor_id": "22222222-2222-2222-2222-222222222222", "actor_username": "svc-bot",
            "actor_kind": "service", "tool": "ai.rag", "resource_kind": "collection",
            "resource": ["faq"], "request_hash": "h", "request_masked": "q", "hit_count": 2,
            "citation_sources": ["a.md"], "pii_masked": 1, "outcome": "ok",
            "duration_ms": 5, "client_address": None, "via": "api"}


def test_list_requires_tz_aware_window(monkeypatch):
    _patch(monkeypatch, _Conn([], 0))
    r = TestClient(_app()).get("/api/audit/tool-calls?since=2026-09-01T00:00:00")
    assert r.status_code == 400


def test_list_returns_rows_total_capped(monkeypatch):
    _patch(monkeypatch, _Conn([_row()], 250))
    r = TestClient(_app()).get("/api/audit/tool-calls?limit=1")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 250 and d["capped"] is True and d["rows"][0]["tool"] == "ai.rag"


def test_summary_groups_by_actor(monkeypatch):
    conn = _Conn([{"actor_id": "2", "actor_username": "svc-bot", "actor_kind": "service",
                   "calls": 3, "ok": 2, "degraded": 1, "error": 0,
                   "collections": ["faq"], "tables": [], "hits": 5, "pii_masked": 1}], 0)
    _patch(monkeypatch, conn)
    r = TestClient(_app()).get("/api/audit/tool-calls/summary")
    assert r.status_code == 200
    assert r.json()["by_actor"][0]["actor_username"] == "svc-bot"
    assert "GROUP BY" in conn.sql[0]


def test_export_streams_ndjson(monkeypatch):
    _patch(monkeypatch, _Conn([_row()], 0))
    r = TestClient(_app()).get("/api/audit/tool-calls/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert r.text.count("\n") == 1


def test_summary_sql_counts_each_call_once():
    # No DB is available in this test module (fake pool never executes real SQL),
    # so this pins the query's shape statically rather than its runtime result:
    # count(*)/FILTER counts must live in the CTE built over the base table, not
    # in the part of the query that unnest()s resource (which fans a row with N
    # resources out into N rows and would multiply every count/sum by N).
    sql = tool_call_routes._SUMMARY_SQL
    before_unnest, _, after_unnest = sql.partition("unnest(")
    assert "count(*)" in before_unnest
    assert "count(*)" not in after_unnest
    assert sql.count("GROUP BY actor_id, actor_username, actor_kind") == 1
    # names CTE must group by all three too — actor_id alone cross-attributes
    # resources between distinct actors that share a NULL actor_id (e.g. two
    # different service accounts with no actor_id set).
    _, _, after_names = sql.partition("names AS (")
    names_cte, _, _ = after_names.partition(")\nSELECT")
    assert "GROUP BY b.actor_id, b.actor_username, b.actor_kind" in names_cte
    assert "n.actor_username = c.actor_username" in sql
    assert "n.actor_kind = c.actor_kind" in sql
    assert "ORDER BY c.calls DESC, c.actor_username ASC" in sql
