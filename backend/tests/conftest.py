"""Shared test doubles for exercising tool_call_log.record() end to end.

A test that wants counting()'s ContextVar to bump exactly as it does in production
must run the real record() — build_row, the INSERT, the success-only accounting —
against a fake connection pool, not a stand-in for record() itself. See
tests/test_tool_call_counting.py for the original of this pattern; tests/test_mcp_server.py
reuses it so the two do not drift.
"""
from typing import List

# Positional order of tool_call_log._INSERT's column list — this is what lets a test
# read a written row back as a dict rather than an opaque args tuple.
_INSERT_COLUMNS = (
    "occurred_at", "actor_id", "actor_username", "actor_kind", "tool",
    "resource_kind", "resource", "request_hash", "request_masked", "hit_count",
    "citation_sources", "pii_masked", "outcome", "duration_ms", "client_address", "via",
    # 0013. This tuple is the INSERT's contract: _Conn.execute only reads a write back
    # as a row when the argument count matches, so a column added to tool_call_log._INSERT
    # without a matching entry here turns every assertion about written rows into a
    # silent "nothing was written" rather than a failure that names the cause.
    "response_hash", "response_masked",
    "injection_flags",  # 0014
)


class _Conn:
    """A connection whose execute() succeeds and remembers every statement it ran.

    `calls` holds the raw (sql, args) pairs, for a test that only cares how many
    writes happened. `rows` holds the same writes as `_INSERT_COLUMNS`-keyed dicts,
    for a test that inspects what record() actually wrote.
    """

    def __init__(self):
        self.calls: List[tuple] = []
        self.rows: List[dict] = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if len(args) == len(_INSERT_COLUMNS):
            self.rows.append(dict(zip(_INSERT_COLUMNS, args)))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self, timeout=None):
        return self._conn


def _patch_pool(monkeypatch, pool):
    async def _get_db_pool():
        return pool
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _get_db_pool)
