"""Counting rows so the MCP dispatcher can tell whether the inner path already logged.

Suppressing the inner write would have been simpler and worse: the /ai/* routes build a
row carrying the collection, the hit count, the cited sources and the masked count, and
a flat row written at the MCP boundary would have thrown all of that away for the sake
of uniformity. Counting keeps the rich row where one exists and fills the gap where one
does not.
"""
import asyncio

from app import tool_call_log


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


ACTOR = {"id": "11111111-1111-1111-1111-111111111111", "username": "svc-bot",
         "auth_method": "service"}


class _Conn:
    def __init__(self):
        self.rows = 0

    async def execute(self, sql, *args):
        self.rows += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self, timeout=None):
        return self._conn


class _BrokenPool:
    def acquire(self, timeout=None):
        raise RuntimeError("pool is gone")


class _RejectingConn:
    """A connection that acquires fine but whose INSERT is rejected — the way an
    out-of-vocabulary `tool` value fails against the CHECK constraint added in 0009."""

    async def execute(self, sql, *args):
        raise RuntimeError("new row for relation \"tool_call_log\" violates check "
                            "constraint \"tool_call_log_tool_check\"")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_pool(monkeypatch, pool):
    async def _get_db_pool():
        return pool
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _get_db_pool)


def _record(**over):
    kwargs = dict(actor=ACTOR, tool="ai.search", resource_kind="collection",
                  resource=["faq"], request_text="q")
    kwargs.update(over)
    return tool_call_log.record(**kwargs)


def test_counting_reports_rows_written_inside_the_block(monkeypatch):
    _patch_pool(monkeypatch, _Pool(_Conn()))

    async def _go():
        with tool_call_log.counting() as count:
            assert count() == 0
            await _record()
            await _record()
            return count()
    assert _run(_go()) == 2


def test_a_failed_write_does_not_count(monkeypatch):
    """Otherwise a lost row would suppress the dispatcher's fallback and the call would
    vanish from the log entirely."""
    _patch_pool(monkeypatch, _BrokenPool())

    async def _go():
        with tool_call_log.counting() as count:
            await _record()
            return count()
    assert _run(_go()) == 0


def test_a_rejected_insert_does_not_count(monkeypatch):
    """The pool acquires fine here; the INSERT itself fails, e.g. against the CHECK
    constraint. This is the layer where a real row actually gets lost after 0009, and
    it must not count — or the dispatcher's fallback row would be suppressed and the
    call would vanish from the log entirely."""
    _patch_pool(monkeypatch, _Pool(_RejectingConn()))

    async def _go():
        with tool_call_log.counting() as count:
            await _record()
            return count()
    assert _run(_go()) == 0


def test_the_counter_does_not_leak_out_of_the_block(monkeypatch):
    _patch_pool(monkeypatch, _Pool(_Conn()))

    async def _go():
        with tool_call_log.counting():
            pass
        await _record()          # outside: no counter, must not raise
    _run(_go())


def test_counting_nests_without_disturbing_the_outer_count(monkeypatch):
    _patch_pool(monkeypatch, _Pool(_Conn()))

    async def _go():
        with tool_call_log.counting() as outer:
            await _record()
            with tool_call_log.counting() as inner:
                await _record()
                assert inner() == 1
            return outer()
    assert _run(_go()) == 1
