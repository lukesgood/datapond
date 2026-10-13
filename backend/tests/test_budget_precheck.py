"""A cap is enforced before the model call, from the gateway's own figures.

The gateway holds the cap and the spend, but it judges "spend > cap" on spend it has
already written, and it writes spend asynchronously and caches the customer row.
Seen live on 2026-10-13: a caller capped at 0 right after its first call got one more
answer (HTTP 200) because its spend had not landed yet; a probe showed the same
cap refusing only from the second call on, and `blocked: true` not refusing at all.

So before a model call DataPond asks the gateway for the caller's spend and cap
(cached for a few seconds, forgotten when an operator changes the cap) and refuses
with the same 402 and `refused` row when spend >= cap. A cap of 0 therefore means
"no calls", immediately. The gateway's own check stays as the backstop.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from app import ai_budget, tool_call_log

ACTOR = {"id": "u-sales", "username": "svc-sales"}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self.text = status, body

    def json(self):
        return json.loads(self.text)


def _info(max_budget, spend):
    return json.dumps({"user_id": "u-sales", "spend": spend, "blocked": False,
                       "litellm_budget_table": {"max_budget": max_budget}})


@pytest.fixture
def gateway(monkeypatch):
    """The gateway's /customer/info, scripted per test; counts the lookups."""
    state = {"answer": _Resp(200, _info(None, 0.0)), "gets": 0, "raise": None}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kw):
            state["gets"] += 1
            assert url.endswith("/customer/info")
            assert kw["params"] == {"end_user_id": "u-sales"}
            if state["raise"]:
                raise state["raise"]
            return state["answer"]

        async def post(self, url, **kw):
            raise AssertionError(f"no model call expected: {url}")
    monkeypatch.setattr(ai_budget.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ai_budget, "_gateway", lambda: ("http://gw", "k"))
    ai_budget.forget_cached()
    return state


@pytest.fixture
def rows(monkeypatch):
    rows = []

    async def _record(**kw):
        rows.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)
    return rows


def test_a_caller_at_its_cap_is_refused_before_the_call(gateway, rows):
    gateway["answer"] = _Resp(200, _info(0.0, 0.0))
    with pytest.raises(HTTPException) as e:
        _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    assert e.value.status_code == 402
    assert [(r["tool"], r["outcome"]) for r in rows] == [("ai.search", "refused")]


def test_a_caller_under_its_cap_or_without_one_goes_through(gateway, rows):
    gateway["answer"] = _Resp(200, _info(1.0, 0.25))
    _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    ai_budget.forget_cached()
    gateway["answer"] = _Resp(200, _info(None, 99.0))
    _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    assert rows == []


def test_the_answer_is_cached_until_an_operator_changes_the_cap(gateway, rows):
    gateway["answer"] = _Resp(200, _info(1.0, 0.0))
    for _ in range(3):
        _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    assert gateway["gets"] == 1
    ai_budget.forget_cached("u-sales")
    gateway["answer"] = _Resp(200, _info(0.0, 0.0))
    with pytest.raises(HTTPException):
        _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    assert gateway["gets"] == 2


def test_an_unknown_customer_or_an_unreachable_gateway_does_not_block(gateway, rows):
    gateway["answer"] = _Resp(404, '{"detail":"not found"}')
    _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    ai_budget.forget_cached()
    gateway["raise"] = RuntimeError("connection refused")
    _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    ai_budget.forget_cached()
    gateway["raise"] = None
    gateway["answer"] = _Resp(500, "boom")
    _run(ai_budget.assert_within_cap(actor=ACTOR, tool="ai.search", request_text="q"))
    assert rows == []


def test_no_actor_means_nothing_to_check(gateway, rows):
    _run(ai_budget.assert_within_cap(actor={}, tool="ai.search", request_text="q"))
    assert gateway["gets"] == 0


def test_setting_a_cap_forgets_the_cached_answer(monkeypatch):
    from app.api import ai_budgets
    forgotten = []
    monkeypatch.setattr(ai_budget, "forget_cached", lambda uid=None: forgotten.append(uid))

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kw):
            return _Resp(200, "{}")
    monkeypatch.setattr(ai_budgets.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ai_budgets, "_gateway", lambda: ("http://gw", "k"))
    _run(ai_budgets.set_budget("u-sales", ai_budgets.BudgetPut(max_budget=0)))
    assert forgotten == ["u-sales"]


def test_embedding_asks_before_it_posts(monkeypatch, rows):
    """The one place every search, rag and embed call passes through."""
    from app.api import ai_vectors
    from app import ai_context
    calls = []

    async def _check(*, actor, tool, request_text):
        calls.append((actor.get("id"), tool))
        raise HTTPException(402, "capped")
    monkeypatch.setattr(ai_vectors, "assert_within_cap", _check)
    monkeypatch.setattr(ai_vectors, "egress_policy", lambda: "open")
    monkeypatch.setattr(ai_vectors, "_gateway", lambda: ("http://gw", "k"))

    class _NoPost:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kw):
            raise AssertionError("the embedding must not be requested")
    monkeypatch.setattr(ai_vectors.httpx, "AsyncClient", _NoPost)
    ai_context.set_actor({"id": "u-sales", "username": "svc-sales"})
    with pytest.raises(HTTPException) as e:
        _run(ai_vectors._embed(["hello"], tool="ai.rag"))
    assert e.value.status_code == 402
    assert calls == [("u-sales", "ai.rag")]


def test_sql_generation_asks_before_it_calls(monkeypatch):
    from app.api import ai_sql
    calls = []

    async def _check(*, actor, tool, request_text):
        calls.append(tool)
        raise HTTPException(402, "capped")
    monkeypatch.setattr(ai_sql, "assert_within_cap", _check)
    monkeypatch.setattr(ai_sql, "_call_litellm", lambda *a: (_ for _ in ()).throw(AssertionError("no call")))
    with pytest.raises(HTTPException) as e:
        _run(ai_sql.generate_text_with_cap(actor={"id": "u1"}, request_text="q",
                                           system="s", messages=[]))
    assert e.value.status_code == 402 and calls == ["ai.sql"]
