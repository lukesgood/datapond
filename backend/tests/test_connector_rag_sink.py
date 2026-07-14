import asyncio


class _Conn:
    """Fake asyncpg connection: captures executed SQL/args and returns a
    canned command tag so the caller can parse the affected-row count."""
    def __init__(self, update_count=0):
        self._update_count = update_count
        self.sink = []
    async def execute(self, sql, *a):
        self.sink.append((sql, a))
        if sql.strip().startswith("UPDATE"):
            return f"UPDATE {self._update_count}"
        return "OK"
    async def __aenter__(self): return self
    async def __aexit__(self, *e): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return self._c


# (table, target, ok, rows, status) — mirrors connectors.py sync `results`.
def _r(table, ok, ns="default"):
    return (table, f"datapond.{ns}.{table}", ok, 10, None)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_invalidate_matches_only_successful_tables(monkeypatch):
    import app.api.connectors as c
    monkeypatch.setenv("RAG_SINK_ENABLED", "true")
    conn = _Conn(update_count=2)
    results = [_r("orders", True), _r("customers", True), _r("broken", False)]
    n = _run(c._invalidate_sink_collections(_Pool(conn), results))
    assert n == 2
    # exactly one UPDATE, scoped to the two successful tables (sorted, deduped)
    updates = [(sql, a) for sql, a in conn.sink if sql.strip().startswith("UPDATE")]
    assert len(updates) == 1
    sql, args = updates[0]
    assert "last_refreshed_at = NULL" in sql
    assert "refresh_source->>'type' = 'iceberg'" in sql
    assert "unnest($1::text[], $2::text[])" in sql
    # parallel (namespaces, tables) arrays, sorted by pair, "broken" excluded
    assert args == (["default", "default"], ["customers", "orders"])


def test_namespace_derived_from_target(monkeypatch):
    import app.api.connectors as c
    monkeypatch.setenv("RAG_SINK_ENABLED", "true")
    conn = _Conn(update_count=1)
    # a single-table sync that overrode target into another namespace
    _run(c._invalidate_sink_collections(_Pool(conn), [_r("orders", True, ns="warehouse")]))
    sql, args = [(s, a) for s, a in conn.sink if s.strip().startswith("UPDATE")][0]
    assert args == (["warehouse"], ["orders"])  # ns comes from target, not hardcoded


def test_no_update_when_no_successful_tables(monkeypatch):
    import app.api.connectors as c
    monkeypatch.setenv("RAG_SINK_ENABLED", "true")
    conn = _Conn()
    n = _run(c._invalidate_sink_collections(_Pool(conn), [_r("orders", False)]))
    assert n == 0
    assert conn.sink == []


def test_disabled_flag_skips_entirely(monkeypatch):
    import app.api.connectors as c
    monkeypatch.setenv("RAG_SINK_ENABLED", "false")
    conn = _Conn(update_count=5)
    n = _run(c._invalidate_sink_collections(_Pool(conn), [_r("orders", True)]))
    assert n == 0
    assert conn.sink == []  # never touched the pool
