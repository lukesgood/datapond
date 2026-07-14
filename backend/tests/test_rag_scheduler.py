import asyncio
from datetime import datetime, timedelta, timezone


def test_is_due():
    import app.rag_scheduler as s
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    assert s._is_due(None, 60, now) is True                          # never run
    assert s._is_due(now - timedelta(minutes=61), 60, now) is True   # overdue
    assert s._is_due(now - timedelta(minutes=10), 60, now) is False  # not yet


class _Conn:
    def __init__(self, lock=True, rows=None, sink=None):
        self._lock = lock
        self._rows = rows or []
        self.sink = sink if sink is not None else []
    async def fetchval(self, sql, *a):
        if "pg_try_advisory_lock" in sql:
            return self._lock
        return None
    async def fetch(self, sql, *a):
        if "FROM ai_collections" in sql:
            return self._rows
        return []
    async def execute(self, sql, *a):
        self.sink.append((sql, a))
    async def __aenter__(self): return self
    async def __aexit__(self, *e): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return self._c


def test_tick_skips_when_lock_not_acquired():
    import app.rag_scheduler as s
    conn = _Conn(lock=False, rows=[{"id": "c1", "name": "kb", "refresh_source": "{}",
                                    "refresh_interval_minutes": 60, "last_refreshed_at": None}])
    n = asyncio.get_event_loop().run_until_complete(s.tick(_Pool(conn)))
    assert n == 0


def test_tick_refreshes_due_and_records_status(monkeypatch):
    import app.rag_scheduler as s
    import app.api.ai_vectors as v
    calls = []
    async def fake_refresh(pool, coll_id, src):
        calls.append((coll_id, src.type))
        return {"documents": 1, "chunks": 2, "pii_masked": 0}
    monkeypatch.setattr(v, "_refresh_from_source", fake_refresh)
    row = {"id": "c1", "name": "kb",
           "refresh_source": '{"type": "s3", "bucket": "b", "prefix": "p/"}',
           "refresh_interval_minutes": 60, "last_refreshed_at": None}
    conn = _Conn(lock=True, rows=[row])
    n = asyncio.get_event_loop().run_until_complete(s.tick(_Pool(conn)))
    assert n == 1 and calls == [("c1", "s3")]
    statuses = [a for (sql, a) in conn.sink if "last_refresh_status" in sql]
    assert statuses and "ok" in str(statuses[0])
