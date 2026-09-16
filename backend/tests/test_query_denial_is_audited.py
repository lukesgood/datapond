"""A refused query leaves a record, and a refusal is not filed as an engine error.

`require_permission` audits the permissions it checks, but the write/DDL gate is
checked inside the handler, on the statement's kind — so a credential probing the API
for what it could DROP was refused and left nothing behind (POSITIONING_FIT_AUDIT §2.5).
The tool call log had the opposite problem: it recorded every failure as `error`, so
denials were indistinguishable from outages.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import queries


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


VIEWER = {"id": "11111111-1111-1111-1111-111111111111", "username": "vic",
          "role": "viewer", "permissions": ["query:run"]}


class _Req:
    def __init__(self, query, save_history=True, origin="ui"):
        self.query, self.save_history, self.origin = query, save_history, origin


@pytest.fixture
def audited(monkeypatch):
    rows = []

    async def _record(**kw):
        rows.append(kw)

    monkeypatch.setattr(queries.security_audit, "record", _record)
    return rows


def test_a_write_statement_from_a_reader_is_audited_then_refused(audited, monkeypatch):
    monkeypatch.setattr(queries, "statement_kind", lambda *a, **k: "write", raising=False)
    with pytest.raises(HTTPException) as exc:
        _run(queries._execute_query_impl(_Req("DROP TABLE orders"), db=None, user=VIEWER))
    assert exc.value.status_code == 403
    assert len(audited) == 1
    assert audited[0]["permission"] == "query:write"
    assert audited[0]["outcome"] == "denied"
    assert audited[0]["route"] == "/api/queries/execute"
    assert audited[0]["actor"] is VIEWER


def test_the_audit_row_is_written_before_the_refusal_reaches_the_caller(audited, monkeypatch):
    """Ordering matters: a row written after the raise would never be written at all."""
    monkeypatch.setattr(queries, "statement_kind", lambda *a, **k: "write", raising=False)
    try:
        _run(queries._execute_query_impl(_Req("CREATE TABLE t (a int)"), db=None, user=VIEWER))
    except HTTPException:
        pass
    assert audited, "the refusal produced no audit row"


# ── the tool call log tells a refusal from an outage ──────────────────────────

def _logged(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)

    monkeypatch.setattr(queries.tool_call_log, "record", _record)
    return calls


@pytest.mark.parametrize("status,expected", [(403, "refused"), (401, "refused"), (500, "error")])
def test_an_http_refusal_is_not_filed_as_an_engine_error(status, expected, monkeypatch):
    calls = _logged(monkeypatch)

    async def _boom(*a, **k):
        raise HTTPException(status_code=status, detail="no")

    monkeypatch.setattr(queries, "_execute_query_impl", _boom)
    with pytest.raises(HTTPException):
        _run(queries.execute_query(_Req("SELECT 1"), db=None, user=VIEWER))
    assert calls[0]["outcome"] == expected


def test_a_genuine_engine_failure_is_still_an_error(monkeypatch):
    calls = _logged(monkeypatch)

    async def _boom(*a, **k):
        raise RuntimeError("trino is down")

    monkeypatch.setattr(queries, "_execute_query_impl", _boom)
    with pytest.raises(RuntimeError):
        _run(queries.execute_query(_Req("SELECT 1"), db=None, user=VIEWER))
    assert calls[0]["outcome"] == "error"
