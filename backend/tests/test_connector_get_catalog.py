"""GET /connectors/{id} returns the source's catalog the way the list does.

`catalog` is not a column of connector_connections; it comes from the source's
data_catalogs row. Selecting it as a column 500'd the route for every source.
"""
import asyncio
import uuid

from app.api import connectors as cx

CID = uuid.uuid4()


class _Conn:
    def __init__(self):
        self.sql = None

    async def fetchrow(self, sql, *a):
        self.sql = sql
        return {"id": CID, "name": "db", "connector_type": "postgresql", "status": "active",
                "created_at": None, "last_sync_at": None, "schedule": None, "owner_id": None,
                "last_checked_at": None, "last_check_message": None, "catalog": "src_db"}


class _Ctx:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


def test_catalog_comes_from_data_catalogs(monkeypatch):
    conn = _Conn()

    class _Pool:
        def acquire(self):
            return _Ctx(conn)

    async def _pool():
        return _Pool()

    async def _ok(*a, **k):
        return None

    monkeypatch.setattr(cx, "get_db_pool", _pool)
    monkeypatch.setattr(cx, "require_access", _ok)
    out = asyncio.run(cx.get_connection(str(CID), user={"id": str(uuid.uuid4()), "role": "admin"}))
    assert out["catalog"] == "src_db"
    sql = " ".join(conn.sql.split())
    assert "LEFT JOIN data_catalogs d" in sql and "d.engine_catalog AS catalog" in sql
    assert "last_check_message, catalog" not in sql
