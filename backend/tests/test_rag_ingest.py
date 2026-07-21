import asyncio


def _aval(value):
    async def _coro(): return value
    return _coro()


class _FakeConn:
    def __init__(self, sink): self.sink = sink
    async def execute(self, sql, *a): self.sink.append(sql)
    async def executemany(self, sql, rows): self.sink.append(("many", sql, list(rows)))
    async def fetchrow(self, sql, *a): return None
    async def fetch(self, sql, *a): return []
    def transaction(self):
        outer = self
        class _Tx:
            async def __aenter__(self_): return outer
            async def __aexit__(self_, *a): return False
        return _Tx()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self): self.sql = []
    def acquire(self): return _FakeConn(self.sql)


def test_ensure_vector_schema_adds_schedule_columns(monkeypatch):
    import app.api.ai_vectors as v
    pool = _FakePool()
    asyncio.run(v.ensure_vector_schema(pool))
    joined = " ".join(s if isinstance(s, str) else s[1] for s in pool.sql)
    assert "refresh_source" in joined and "JSONB" in joined.upper()
    assert "refresh_interval_minutes" in joined
    assert "refresh_enabled" in joined
    assert "last_refreshed_at" in joined
    assert "last_refresh_status" in joined
    assert "source_group" in joined
    assert "ai_chunks_group_idx" in joined


def test_source_group_iceberg_and_s3():
    import app.api.ai_vectors as v
    ice = v.SourceIngest(type="iceberg", schema="sales", table="orders", text_column="note")
    s3 = v.SourceIngest(type="s3", bucket="b", prefix="docs/")
    assert v._source_group(ice) == "iceberg:sales.orders.note"
    assert v._source_group(s3) == "s3:b/docs/"


def test_ingest_documents_replaces_when_group_given(monkeypatch):
    import app.api.ai_vectors as v
    sink = []
    pool = _FakePool(); pool.acquire = lambda: _FakeConn(sink)
    monkeypatch.setattr(v, "get_db_pool", lambda: _aval(pool))
    monkeypatch.setattr(v, "_embed", lambda texts: _aval([[0.0] for _ in texts]))
    docs = [("s3://b/a.txt", "hello world", {"k": 1})]
    asyncio.run(v._ingest_documents("cid", docs, 1000, 150, source_group="s3:b/"))
    dels = [s for s in sink if isinstance(s, str) and s.strip().upper().startswith("DELETE")]
    assert dels and "source_group" in dels[0]


def test_ingest_documents_appends_when_no_group(monkeypatch):
    import app.api.ai_vectors as v
    sink = []
    pool = _FakePool(); pool.acquire = lambda: _FakeConn(sink)
    monkeypatch.setattr(v, "get_db_pool", lambda: _aval(pool))
    monkeypatch.setattr(v, "_embed", lambda texts: _aval([[0.0] for _ in texts]))
    asyncio.run(v._ingest_documents("cid", [("s", "text", {})], 1000, 150))
    dels = [s for s in sink if isinstance(s, str) and s.strip().upper().startswith("DELETE")]
    assert not dels


def test_refresh_from_source_purges_legacy_untagged_chunks(monkeypatch):
    import app.api.ai_vectors as v
    sink = []
    pool = _FakePool(); pool.acquire = lambda: _FakeConn(sink)
    monkeypatch.setattr(v, "_read_s3_docs", lambda b, p, m: [])
    async def fake_ingest(coll_id, docs, cs, ov, source_group=None):
        return {"chunks": 0, "pii_masked": 0}
    monkeypatch.setattr(v, "_ingest_documents", fake_ingest)
    src = v.SourceIngest(type="s3", bucket="b", prefix="p/")
    asyncio.run(v._refresh_from_source(pool, "cid", src))
    legacy = [s for s in sink if isinstance(s, str) and "source_group IS NULL" in s]
    assert legacy and "LIKE" in legacy[0]


def test_preset_to_minutes():
    import pytest
    import app.api.ai_vectors as v
    assert v._preset_to_minutes(None, 90) == 90
    assert v._preset_to_minutes("@hourly", None) == 60
    assert v._preset_to_minutes("@daily", None) == 1440
    assert v._preset_to_minutes("@weekly", None) == 10080
    assert v._preset_to_minutes(None, None) == 1440
    with pytest.raises(Exception):
        v._preset_to_minutes(None, 0)
