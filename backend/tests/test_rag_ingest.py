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


# ── FIX #5: block mode must not store/embed raw PII ──────────────────────────────

def test_ingest_documents_block_mode_redacts_pii(monkeypatch):
    """PII_GUARDRAIL_MODE=block: pii_ko.apply() returns the ORIGINAL text + blocked=True,
    but _ingest_documents must redact before it embeds/persists — raw PII must never
    reach the embedding provider nor land in ai_chunks."""
    import app.api.ai_vectors as v
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "block")
    sink = []
    captured = {}
    pool = _FakePool(); pool.acquire = lambda: _FakeConn(sink)
    monkeypatch.setattr(v, "get_db_pool", lambda: _aval(pool))

    def fake_embed(texts):
        captured["texts"] = list(texts)
        return _aval([[0.0] for _ in texts])
    monkeypatch.setattr(v, "_embed", fake_embed)

    docs = [("s", "reach me at hong@example.com anytime", {})]
    res = asyncio.run(v._ingest_documents("cid", docs, 1000, 150))

    # raw email must not be embedded ...
    assert captured["texts"] and all("hong@example.com" not in t for t in captured["texts"])
    assert any("[이메일]" in t for t in captured["texts"])
    # ... nor persisted to ai_chunks
    inserts = [s for s in sink if isinstance(s, tuple) and s[0] == "many"]
    assert inserts, "expected an executemany INSERT"
    stored = [row[3] for row in inserts[0][2]]   # content column
    assert all("hong@example.com" not in c for c in stored)
    assert res["pii_masked"] >= 1


def test_ingest_documents_mask_mode_unchanged(monkeypatch):
    """Default mask mode behaviour is preserved: content is masked, still stored/embedded."""
    import app.api.ai_vectors as v
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    sink = []
    captured = {}
    pool = _FakePool(); pool.acquire = lambda: _FakeConn(sink)
    monkeypatch.setattr(v, "get_db_pool", lambda: _aval(pool))

    def fake_embed(texts):
        captured["texts"] = list(texts)
        return _aval([[0.0] for _ in texts])
    monkeypatch.setattr(v, "_embed", fake_embed)

    res = asyncio.run(v._ingest_documents("cid", [("s", "mail hong@example.com", {})], 1000, 150))
    assert captured["texts"] and "[이메일]" in captured["texts"][0]
    assert "hong@example.com" not in captured["texts"][0]
    assert res["pii_masked"] >= 1


# ── FIX #9: embed-dimension validation ───────────────────────────────────────────

class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return _FakeResp(self._status, self._payload)

    async def get(self, *a, **k):
        return _FakeResp(self._status, self._payload)


def test_embed_rejects_dimension_mismatch(monkeypatch):
    import pytest
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "_assert_embed_egress_ok", lambda: _aval(None))
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setenv("AI_EMBED_DIM", "1024")
    payload = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}  # 3-dim, not 1024
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(payload))
    with pytest.raises(v.HTTPException) as ei:
        asyncio.run(v._embed(["hello"]))
    assert ei.value.status_code == 502
    assert "dimension" in ei.value.detail.lower()


def test_embed_accepts_matching_dimension(monkeypatch):
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "_assert_embed_egress_ok", lambda: _aval(None))
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setenv("AI_EMBED_DIM", "3")
    payload = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(payload))
    assert asyncio.run(v._embed(["hello"])) == [[0.1, 0.2, 0.3]]


# ── FIX #6: local-only embed egress guard fails closed ───────────────────────────

class _BoomClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        raise RuntimeError("gateway unreachable")


def test_embed_egress_fails_closed_on_introspection_error(monkeypatch):
    import pytest
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "egress_policy", lambda: "local-only")
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda *a, **k: _BoomClient())
    with pytest.raises(v.HTTPException) as ei:
        asyncio.run(v._assert_embed_egress_ok())
    assert ei.value.status_code == 403


def test_embed_egress_fails_closed_when_model_not_registered(monkeypatch):
    import pytest
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "egress_policy", lambda: "local-only")
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setenv("AI_EMBED_MODEL", "embed")
    payload = {"data": [{"model_name": "other", "litellm_params": {"model": "ollama/bge-m3"}}]}
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(payload))
    with pytest.raises(v.HTTPException) as ei:
        asyncio.run(v._assert_embed_egress_ok())
    assert ei.value.status_code == 403


def test_embed_egress_blocks_external_model(monkeypatch):
    import pytest
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "egress_policy", lambda: "local-only")
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setenv("AI_EMBED_MODEL", "embed")
    payload = {"data": [{"model_name": "embed",
                         "litellm_params": {"model": "bedrock/amazon.titan-embed-text-v2:0"}}]}
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(payload))
    with pytest.raises(v.HTTPException) as ei:
        asyncio.run(v._assert_embed_egress_ok())
    assert ei.value.status_code == 403


def test_embed_egress_allows_local_model(monkeypatch):
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "egress_policy", lambda: "local-only")
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setenv("AI_EMBED_MODEL", "embed")
    payload = {"data": [{"model_name": "embed", "litellm_params": {"model": "ollama/bge-m3"}}]}
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(payload))
    asyncio.run(v._assert_embed_egress_ok())   # must not raise


def test_embed_egress_noop_when_cloud_allowed(monkeypatch):
    import app.api.ai_vectors as v
    monkeypatch.setattr(v, "egress_policy", lambda: "cloud-allowed")
    # _gateway / httpx must not even be consulted under cloud-allowed
    monkeypatch.setattr(v, "_gateway", lambda: (_ for _ in ()).throw(AssertionError("gateway consulted")))
    asyncio.run(v._assert_embed_egress_ok())   # must not raise
