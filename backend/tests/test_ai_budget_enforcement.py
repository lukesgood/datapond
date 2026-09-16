"""A caller that has spent its budget is told so, and the refusal is audited.

The gateway enforces the cap (it holds the spend), but answers with an auth error —
"type": "auth_error", code 401 — which our call sites wrapped again as 502 "Embedding
failed". An agent could not tell a spend cap from a bad key, and nothing recorded that
a caller had been turned away.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.ai_budget import budget_error, is_budget_refusal, refuse_over_budget

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


OVER = ('{"error":{"message":"ExceededBudget: End User=svc-bot over budget. '
        'Spend=0.9, Budget=0.5","type":"auth_error","code":401}}')
BAD_KEY = '{"error":{"message":"Authentication Error, Invalid proxy server token","type":"auth_error","code":401}}'


@pytest.mark.parametrize("status,body,expected", [
    (401, OVER, True),
    (400, "user over budget", True),
    (401, BAD_KEY, False),      # same status and type — only the message separates them
    (500, "upstream exploded", False),
    (200, OVER, False),         # a success is not a refusal whatever it says
    (502, None, False),
])
def test_only_a_spend_cap_reads_as_one(status, body, expected):
    assert is_budget_refusal(status, body) is expected


def test_the_error_is_402_and_carries_the_numbers():
    e = budget_error(OVER)
    assert e.status_code == 402
    assert "Spend=0.9" in e.detail and "Budget=0.5" in e.detail


def test_the_detail_is_trimmed_not_unbounded():
    assert len(budget_error("x" * 5000).detail) < 400


def test_a_refusal_is_recorded_before_the_error_is_raised(monkeypatch):
    """Run through an explicit loop, like the rest of this suite: there is no asyncio
    plugin configured here, and a bare `async def test_` is collected and skipped —
    which reads as a passing suite while the assertion never runs."""
    rows = []

    async def _record(**kw):
        rows.append(kw)

    import app.ai_budget as mod
    monkeypatch.setattr(mod.tool_call_log, "record", _record)
    err = _run(refuse_over_budget(actor={"id": "u1", "username": "svc-bot"},
                                  tool="ai.search", request_text="010-1234-5678",
                                  body=OVER))
    assert isinstance(err, HTTPException) and err.status_code == 402
    assert len(rows) == 1
    assert rows[0]["outcome"] == "refused" and rows[0]["tool"] == "ai.search"
    # masked_for_log runs before the row is written — tool_call_log is append-only.
    assert "010-1234-5678" not in rows[0]["request_text"]
