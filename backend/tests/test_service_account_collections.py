from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, service_account_routes as sar

_REAL_REQUIRE_ADMIN = auth.require_admin
ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ACCT = "22222222-2222-2222-2222-222222222222"


def _app():
    app = FastAPI()
    app.include_router(sar.router, prefix="/api")

    async def _override():
        return ADMIN
    app.dependency_overrides[_REAL_REQUIRE_ADMIN] = _override
    return app


class _Conn:
    def __init__(self, account_row, rows):
        self.account_row, self.rows, self.sql = account_row, rows, []

    async def fetchrow(self, sql, *args):
        self.sql.append(sql)
        return self.account_row

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return self.rows

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
    monkeypatch.setattr(sar, "_get_pool", _pool)   # the module imports _get_pool from app.api.auth


def test_unknown_account_is_404(monkeypatch):
    _patch(monkeypatch, _Conn(None, []))
    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/collections")
    assert r.status_code == 404


def test_lists_owned_member_and_global_collections(monkeypatch):
    conn = _Conn({"id": ACCT, "auth_method": "service"},
                 [{"name": "faq", "access": "reader", "chunks": 12},
                  {"name": "mine", "access": "owner", "chunks": 3},
                  {"name": "public", "access": "global", "chunks": 0}])
    _patch(monkeypatch, conn)
    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/collections")
    assert r.status_code == 200
    d = r.json()
    assert d["account_id"] == ACCT
    assert [c["name"] for c in d["collections"]] == ["faq", "mine", "public"]
    assert "ai_collection_members" in conn.sql[-1] and "owner_id IS NULL" in conn.sql[-1]
