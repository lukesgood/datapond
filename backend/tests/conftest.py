"""Shared test doubles for exercising tool_call_log.record() end to end.

A test that wants counting()'s ContextVar to bump exactly as it does in production
must run the real record() — build_row, the INSERT, the success-only accounting —
against a fake connection pool, not a stand-in for record() itself. See
tests/test_tool_call_counting.py for the original of this pattern; tests/test_mcp_server.py
reuses it so the two do not drift.
"""
import os

# Unit tests never reach a real query engine or cache. The in-cluster default host
# (trino.datapond.svc.cluster.local) can take a 30 s connect timeout to fail on a
# workstation — one test spent 30 s in governance._scan_pii_tables, and a background
# quality check logged after the run. Point every Trino setting at a closed local port
# so an unmocked call fails at once, the way an unreachable engine does. setdefault:
# an environment that names a real engine (acceptance runs) keeps it.
for _var in ("TRINO_HOST", "TRINO_SERVICE_HOST"):
    os.environ.setdefault(_var, "127.0.0.1")
for _var in ("TRINO_PORT", "TRINO_SERVICE_PORT"):
    os.environ.setdefault(_var, "9")
# Same for Valkey (webauthn's challenge store waited out a 2 s connect per call on the
# in-cluster default before falling back to its in-process store).
os.environ.setdefault("VALKEY_HOST", "127.0.0.1")
os.environ.setdefault("VALKEY_PORT", "9")

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
    "chunks_withheld",  # 0017
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


# ── catalog grants (app/catalog_access.py) ───────────────────────────────────
# Grants are read from the database for every non-admin caller. A unit test has no
# database, and "cannot read grants" fails closed — so every test starts with grants
# read and empty (every catalog open), which is what a deployment that never granted
# anything sees. Tests about grants install their own.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _no_catalog_grants():
    # tests/acceptance runs against a deployed target with only pytest and httpx
    # installed — there is no `app` to import, and nothing local to reset.
    try:
        from app import catalog_access
    except ImportError:
        yield
        return
    catalog_access.set_grants({})
    yield
    catalog_access.reset()
