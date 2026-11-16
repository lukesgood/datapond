"""Pausing a source a team does not use: it leaves the dashboard checklist (only active
sources can be stale — app/api/ops.py) and the background check (app/connector_checks.py),
and a check result never un-pauses it (connectors._record_check). Until 2.7 nothing could
set the status; the live checklist carried five unused sample sources for days."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from app.api import connectors as mod

CID = "6f1b8a2e-0000-4000-8000-000000000001"
USER = {"id": "6f1b8a2e-0000-4000-8000-0000000000aa", "username": "eng", "role": "data_engineer"}


class _Conn:
    def __init__(self, row):
        self.row, self.calls = row, []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.row

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "UPDATE 1"


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


@pytest.fixture
def db(monkeypatch):
    conn = _Conn({"id": CID, "name": "Sample FX Rates API", "status": "active"})

    async def _pool():
        return _Pool(conn)

    async def _access(kind, cid, user, write=False):
        assert write is True
    monkeypatch.setattr(mod, "get_db_pool", _pool)
    monkeypatch.setattr(mod, "require_access", _access)
    return conn


def _updates(conn):
    return [c for c in conn.calls if c[0] == "execute" and "UPDATE connector_connections" in c[1]]


def _audits(conn):
    return [c for c in conn.calls if c[0] == "execute" and "auth_audit_log" in c[1]]


def test_pausing_sets_the_status_and_is_audited(db):
    out = asyncio.run(mod.pause_connection(CID, user=USER))
    assert out == {"id": CID, "name": "Sample FX Rates API", "status": "paused"}
    (_, sql, args), = _updates(db)
    assert "status" in sql and "paused" in args
    (_, _, aargs), = _audits(db)
    assert aargs[0] == "connector_paused" and json.loads(aargs[-1])["connection_id"] == CID


def test_resuming_makes_it_active_again(db):
    db.row = {"id": CID, "name": "Sample FX Rates API", "status": "paused"}
    out = asyncio.run(mod.resume_connection(CID, user=USER))
    assert out["status"] == "active"
    assert "active" in _updates(db)[0][2] and _audits(db)[0][2][0] == "connector_resumed"


def test_an_unknown_source_is_404_and_writes_nothing(db):
    db.row = None
    with pytest.raises(HTTPException) as e:
        asyncio.run(mod.pause_connection(CID, user=USER))
    assert e.value.status_code == 404 and not _updates(db) and not _audits(db)


def test_both_routes_need_connector_write():
    from main import app
    want = {f"/api/connectors/{{connection_id}}/{v}" for v in ("pause", "resume")}
    found = {}
    for r in app.routes:
        if getattr(r, "path", None) in want:
            found[r.path] = [getattr(d.call, "__datapond_authorization__", None) for d in r.dependant.dependencies]
    assert set(found) == want
    assert all("connector:write" in str(v) for v in found.values())
