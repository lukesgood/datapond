"""The collection list carries the viewer's own member grant, so the console can let
an editor edit instead of telling them the collection is read-only."""
import asyncio
import uuid

from app.api import ai_vectors as av

UID = str(uuid.uuid4())


class _Conn:
    def __init__(self):
        self.calls = []

    async def fetchval(self, sql, *args):
        return 1

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return [{"name": "kb", "embed_model": "embed", "dim": 1024, "description": None,
                 "created_at": None, "owner_id": uuid.uuid4(), "chunk_access": None,
                 "member_role": "editor", "chunks": 3, "sources": 1, "last_ingested": None}]


class _Ctx:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


def _run(monkeypatch, user, **kw):
    conn = _Conn()

    class _Pool:
        def acquire(self):
            return _Ctx(conn)

    async def _pool():
        return _Pool()

    monkeypatch.setattr(av, "get_db_pool", _pool)
    out = asyncio.run(av.list_collections(user=user, q=kw.get("q"), limit=kw.get("limit"), offset=kw.get("offset")))
    return out, conn


def test_member_role_is_returned_and_bound_to_the_viewer(monkeypatch):
    out, conn = _run(monkeypatch, {"id": UID, "role": "data_scientist"}, q="k", limit=10)
    assert out["collections"][0]["member_role"] == "editor"
    sql, args = conn.calls[0]
    assert "member_role" in sql and args[-1] == uuid.UUID(UID)
    # Every placeholder the SQL names has an argument.
    assert f"${len(args)}" in sql and f"${len(args) + 1}" not in sql


def test_admin_listing_still_binds_cleanly(monkeypatch):
    out, conn = _run(monkeypatch, {"id": UID, "role": "admin"})
    sql, args = conn.calls[0]
    assert len(args) == 1 and "$1" in sql and "$2" not in sql
