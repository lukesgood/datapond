import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from app import tool_call_log as tcl


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


HUMAN = {"id": "11111111-1111-1111-1111-111111111111", "username": "mina", "role": "ai_engineer"}
SERVICE = {**HUMAN, "id": "22222222-2222-2222-2222-222222222222", "username": "svc-bot",
           "auth_method": "service"}


def test_build_row_masks_hash_and_truncates():
    text = "x" * 600
    row = tcl.build_row(actor=HUMAN, tool="ai.search", resource_kind="collection",
                        resource=["faq"], request_text=text, hit_count=3,
                        citation_sources=["b.md", "a.md", "a.md"], pii_masked=2,
                        now=datetime(2026, 9, 7, tzinfo=timezone.utc))
    assert row["request_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert row["request_masked"] == "x" * 512
    assert row["citation_sources"] == ["a.md", "b.md"]
    assert row["actor_kind"] == "human"
    assert row["via"] == "api"
    assert row["occurred_at"] == datetime(2026, 9, 7, tzinfo=timezone.utc)


def test_build_row_service_account_kind():
    row = tcl.build_row(actor=SERVICE, tool="ai.rag", resource_kind="collection",
                        resource=["faq"], request_text="q")
    assert row["actor_kind"] == "service"
    assert row["actor_id"] == SERVICE["id"]
    assert row["actor_username"] == "svc-bot"


@pytest.mark.parametrize("field,value", [
    ("tool", "nope"), ("resource_kind", "shelf"), ("outcome", "meh"),
])
def test_build_row_rejects_unknown_vocabulary(field, value):
    kwargs = dict(actor=HUMAN, tool="ai.sql", resource_kind="none", resource=[],
                  request_text="q", outcome="ok")
    kwargs[field] = value
    with pytest.raises(ValueError):
        tcl.build_row(**kwargs)


def test_build_row_accepts_every_registered_action_id():
    """Widened per Task 5: the MCP dispatcher writes a fallback row (app/mcp/server.py)
    for any action whose executor never reaches an /ai/* route — build_row must accept
    its id or that row silently disappears into logger.error instead of the
    append-only table."""
    from app.chat.actions import REGISTRY
    assert REGISTRY, "the action registry is unexpectedly empty"
    for action_id in REGISTRY:
        row = tcl.build_row(actor=HUMAN, tool=action_id, resource_kind="none",
                            resource=[], request_text="q")
        assert row["tool"] == action_id


def test_build_row_client_address_from_contextvar_when_arg_omitted():
    assert tcl.current_client_address() is None
    token = tcl.set_client_address("203.0.113.7")
    try:
        row = tcl.build_row(actor=HUMAN, tool="ai.search", resource_kind="collection",
                            resource=["faq"], request_text="q")
        assert row["client_address"] == "203.0.113.7"
    finally:
        tcl._client_address.reset(token)
    assert tcl.current_client_address() is None


def test_build_row_prefers_explicit_client_address_over_contextvar():
    token = tcl.set_client_address("203.0.113.7")
    try:
        row = tcl.build_row(actor=HUMAN, tool="ai.search", resource_kind="collection",
                            resource=["faq"], request_text="q",
                            client_address="198.51.100.9")
        assert row["client_address"] == "198.51.100.9"
    finally:
        tcl._client_address.reset(token)


def test_via_context_defaults_to_api_and_restores():
    assert tcl.current_via() == "api"
    with tcl.via("chat"):
        assert tcl.current_via() == "chat"
    assert tcl.current_via() == "api"


def test_table_names_from_sql():
    assert tcl.table_names("SELECT a.x FROM sales.orders a JOIN dim.customer c ON a.c = c.id") \
        == ["dim.customer", "sales.orders"]
    assert tcl.table_names("this is not sql (") == []


@pytest.mark.parametrize("mode", ["block", "off"])
def test_masked_for_log_ignores_guardrail_mode(monkeypatch, mode):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", mode)
    out = tcl.masked_for_log("call me at 010-1234-5678")
    assert "010-1234-5678" not in out


class _FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn
        self.acquire_kwargs = None

    def acquire(self, timeout=None):
        self.acquire_kwargs = {"timeout": timeout}
        return self._conn


class _BrokenPool:
    def acquire(self, timeout=None):
        raise RuntimeError("pool is gone")


def _patch_pool(monkeypatch, pool):
    async def _get_db_pool():
        return pool
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _get_db_pool)


def test_record_inserts_one_row(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, _FakePool(conn))
    _run(tcl.record(actor=HUMAN, tool="query.execute", resource_kind="tables",
                    resource=["sales.orders"], request_text="SELECT 1", hit_count=1,
                    outcome="ok", duration_ms=12))
    assert len(conn.calls) == 1
    sql, args = conn.calls[0]
    assert "INSERT INTO public.tool_call_log" in sql
    assert "query.execute" in args and ["sales.orders"] in args


def test_record_never_raises(monkeypatch):
    _patch_pool(monkeypatch, _BrokenPool())
    _run(tcl.record(actor=HUMAN, tool="ai.sql", resource_kind="none", resource=[],
                    request_text="q"))  # must not raise


def test_record_acquires_with_a_timeout(monkeypatch):
    """A saturated pool must not stall the caller's response — record() bounds its
    own wait for a connection rather than blocking forever."""
    conn = _FakeConn()
    pool = _FakePool(conn)
    _patch_pool(monkeypatch, pool)
    _run(tcl.record(actor=HUMAN, tool="ai.sql", resource_kind="none", resource=[],
                    request_text="q"))
    assert pool.acquire_kwargs == {"timeout": 2}


def test_refused_is_part_of_the_vocabulary():
    """A call turned away before it ran (migration 0010). The sentinel tool exists for
    the refusal whose requested name is not a tool at all."""
    row = tcl.build_row(actor=SERVICE, tool=tcl.UNKNOWN_TOOL, resource_kind="none",
                        resource=[], request_text='{"name": "no.such.tool"}',
                        outcome="refused")
    assert row["outcome"] == "refused" and row["tool"] == tcl.UNKNOWN_TOOL
    assert "refused" in tcl.OUTCOMES and tcl.UNKNOWN_TOOL in tcl.TOOLS
