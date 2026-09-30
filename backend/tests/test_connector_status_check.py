"""A source's status follows its last real contact with the source.

Status used to be written once, from the connection test at creation. A source whose
password changed, or whose stored credentials stopped decrypting, stayed "active"
through every failed sync — the list said everything was fine while nothing synced.
These pin what now moves it, and what deliberately does not: a sync that failed on the
write side is not the source's fault.
"""
import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import connectors
from app.connectors.base import ConnectionTestResult

CID = "00000000-0000-0000-0000-000000000001"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    async def record(connection_id, ok, message):
        calls.append((connection_id, ok, message))

    monkeypatch.setattr(connectors, "_record_check", record)
    return calls


class _Connector:
    def __init__(self, test_ok=True, tables=None, list_error=None):
        self.test_ok, self.tables, self.list_error = test_ok, tables or ["t"], list_error
        self.tested = 0

    async def test_connection(self):
        self.tested += 1
        return ConnectionTestResult(success=self.test_ok,
                                    message="ok" if self.test_ok else "password authentication failed")

    async def get_tables(self):
        if self.list_error:
            raise self.list_error
        return self.tables


# ── sync outcomes ─────────────────────────────────────────────────────────────

def test_a_sync_that_read_any_table_marks_the_source_reachable(recorded):
    connector = _Connector(test_ok=False)
    _run(connectors._record_sync_outcome(connector, CID, [(False, "boom"), (True, None)]))
    assert recorded == [(CID, True, "Read during sync")]
    assert connector.tested == 0, "a successful read is the check; no second probe"


def test_a_sync_that_failed_everywhere_asks_the_source_before_blaming_it(recorded):
    """The write side (Glue, S3) fails too. A reachable source keeps its active status,
    and the message says which half failed."""
    _run(connectors._record_sync_outcome(_Connector(test_ok=True), CID,
                                         [(False, "AccessDenied on s3://warehouse")]))
    (_, ok, message), = recorded
    assert ok and "last sync failed: AccessDenied" in message


def test_a_sync_that_failed_and_a_source_that_does_not_answer_is_an_error(recorded):
    _run(connectors._record_sync_outcome(_Connector(test_ok=False), CID, [(False, "timeout")]))
    assert recorded == [(CID, False, "password authentication failed")]


def test_a_sync_with_nothing_to_sync_records_nothing(recorded):
    _run(connectors._record_sync_outcome(_Connector(), CID, []))
    assert recorded == []


def test_a_source_that_cannot_list_its_tables_is_an_error(recorded):
    connector = _Connector(list_error=RuntimeError("connection refused"))
    with pytest.raises(RuntimeError):
        _run(connectors._discover_tables(connector, CID))
    (_, ok, message), = recorded
    assert not ok and "connection refused" in message


# ── credentials that no longer decrypt ────────────────────────────────────────

class _Pool:
    def __init__(self, row):
        self.row = row

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool

            async def __aexit__(self, *a):
                return False
        return _Ctx()

    async def fetchrow(self, *_a):
        return self.row


def test_credentials_that_do_not_decrypt_are_a_failed_check(monkeypatch, recorded):
    """The live incident: ENCRYPTION_KEY was regenerated, every sync failed with
    "Decryption failed", and the connector still read "active"."""
    async def pool():
        return _Pool({"name": "s", "connector_type": "postgresql", "config_encrypted": "x"})

    def boom(_):
        raise ValueError("Decryption failed")

    monkeypatch.setattr(connectors, "get_db_pool", pool)
    monkeypatch.setattr(connectors.vault, "decrypt_credentials", boom)
    with pytest.raises(ValueError):
        _run(connectors._get_connector_instance(CID))
    (_, ok, message), = recorded
    assert not ok and "cannot be decrypted" in message


# ── explicit check ────────────────────────────────────────────────────────────

def test_check_tests_the_stored_config_and_records_it(monkeypatch, recorded):
    async def instance(_):
        return _Connector(test_ok=False)

    monkeypatch.setattr(connectors, "_get_connector_instance", instance)
    assert _run(connectors._check_connection(CID)) == {
        "success": False, "message": "password authentication failed", "status": "error"}
    assert recorded == [(CID, False, "password authentication failed")]


def test_check_of_a_missing_connection_is_a_404_not_a_recorded_failure(monkeypatch, recorded):
    async def instance(_):
        raise HTTPException(status_code=404, detail="Connection not found")

    monkeypatch.setattr(connectors, "_get_connector_instance", instance)
    with pytest.raises(HTTPException):
        _run(connectors._check_connection(CID))
    assert recorded == []


# ── the write itself ──────────────────────────────────────────────────────────

class _WritePool(_Pool):
    def __init__(self):
        super().__init__(None)
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


def test_recording_leaves_a_paused_source_paused(monkeypatch):
    pool = _WritePool()

    async def get_pool():
        return pool

    monkeypatch.setattr(connectors, "get_db_pool", get_pool)
    _run(connectors._record_check(CID, False, "x" * 900))
    (sql, args), = pool.executed
    assert "WHEN status = 'paused' THEN status" in sql
    assert "last_checked_at = now()" in sql
    assert args[1] == "error" and len(args[2]) == 500


def test_recording_never_fails_the_caller(monkeypatch):
    async def broken():
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(connectors, "get_db_pool", broken)
    _run(connectors._record_check(CID, True, "ok"))  # does not raise


# ── the columns exist, additively ─────────────────────────────────────────────

def test_the_migration_only_adds_columns():
    from app.migration_rules import review_migration
    versions = Path(connectors.__file__).resolve().parents[2] / "migrations" / "versions"
    sql = (versions / "0019_connector_last_check.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS last_checked_at" in sql
    assert "ADD COLUMN IF NOT EXISTS last_check_message" in sql
    assert not review_migration("0019_connector_last_check", sql)


# ── the periodic check ────────────────────────────────────────────────────────

class _TickConn:
    def __init__(self, lock=True, due=("a", "b")):
        self.lock, self.due, self.sql = lock, list(due), []

    async def fetchval(self, sql, *args):
        self.sql.append(sql)
        return self.lock

    async def fetch(self, sql, *args):
        self.sql.append((sql, args))
        return [{"id": d} for d in self.due]

    async def execute(self, sql, *args):
        self.sql.append(sql)


class _TickPool:
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


def test_a_tick_checks_every_due_source_and_releases_the_lock():
    from app import connector_checks
    conn, seen = _TickConn(), []

    async def check(cid):
        seen.append(cid)

    assert _run(connector_checks.tick(_TickPool(conn), check=check)) == 2
    assert seen == ["a", "b"]
    assert any("pg_advisory_unlock" in str(s) for s in conn.sql)


def test_the_replica_without_the_lock_checks_nothing():
    """Two backend replicas run the loop; only the lock holder may contact sources, or
    every source is probed twice per interval."""
    from app import connector_checks
    seen = []

    async def check(cid):
        seen.append(cid)

    assert _run(connector_checks.tick(_TickPool(_TickConn(lock=False)), check=check)) == 0
    assert seen == []


def test_one_failing_check_does_not_stop_the_tick():
    from app import connector_checks

    async def check(cid):
        if cid == "a":
            raise HTTPException(status_code=404, detail="gone")

    assert _run(connector_checks.tick(_TickPool(_TickConn()), check=check)) == 1


def test_due_sources_skip_paused_and_take_the_oldest_first():
    from app import connector_checks
    conn = _TickConn()
    _run(connector_checks.due_ids(conn, 60))
    (sql, args), = conn.sql
    assert "IS DISTINCT FROM 'paused'" in sql
    assert "last_checked_at IS NULL" in sql and "NULLS FIRST" in sql
    assert args == (60, connector_checks.BATCH)


def test_the_interval_has_a_floor(monkeypatch):
    """A one-minute interval would probe customer systems constantly."""
    from app import connector_checks
    monkeypatch.setenv("CONNECTOR_CHECK_INTERVAL_MINUTES", "1")
    assert connector_checks.interval_minutes() == 5
    monkeypatch.setenv("CONNECTOR_CHECK_INTERVAL_MINUTES", "junk")
    assert connector_checks.interval_minutes() == 60


# ── the check itself runs off the request loop, under a deadline ─────────────

def test_a_source_that_does_not_answer_is_a_failed_check(monkeypatch):
    import time
    monkeypatch.setenv("CONNECTOR_CHECK_TIMEOUT_SECONDS", "1")

    class _Hang:
        async def test_connection(self):
            time.sleep(3)       # a blocking driver, not an awaitable sleep

    ok, message = _run(connectors._test_isolated(_Hang()))
    assert not ok and "No answer within 1s" in message


def test_a_blocking_driver_does_not_block_the_loop(monkeypatch):
    """While a check blocks in its driver, the request loop keeps serving."""
    import time
    monkeypatch.setenv("CONNECTOR_CHECK_TIMEOUT_SECONDS", "5")

    class _Slow:
        async def test_connection(self):
            time.sleep(0.5)
            return ConnectionTestResult(success=True, message="ok")

    async def both():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.05)
                ticks += 1

        result, _ = await asyncio.gather(connectors._test_isolated(_Slow()), heartbeat())
        return result, ticks

    (ok, _), ticks = _run(both())
    assert ok and ticks == 5
