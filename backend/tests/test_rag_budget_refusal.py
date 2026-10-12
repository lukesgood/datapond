"""A caller over its spend budget gets the same answer from /ai/rag as from /ai/search:
402, once in the audit log.

The RAG path used to turn a refused generation into HTTP 200 with the answer
"(Model spend budget reached for this caller) Returning search results only." — an
agent reading the status saw success, the demo script promised 402, and the live
rehearsal on 2026-10-01 produced one such 200 nobody could explain. A spend cap is a
refusal; it is reported as one.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app import tool_call_log
from app.ai_budget import refuse_over_budget
from app.api import ai_vectors

OVER = ('{"error":{"message":"Budget has been exceeded! EndUser=u1 Current cost: 0.9, '
        'Max budget: 0.5","type":"budget_exceeded","code":"400"}}')
USER = {"id": "u1", "username": "svc-sales", "role": "ai_engineer"}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class _Client:
    """The gateway as the RAG path sees it: one chat completion, refused."""
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kw):
        assert url.endswith("/v1/chat/completions")
        return _Resp(400, OVER)


@pytest.fixture
def rows(monkeypatch):
    rows = []

    async def _record(**kw):
        rows.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)
    return rows


@pytest.fixture
def refused_generation(monkeypatch):
    async def _admit(name, user):
        return 7

    async def _retrieve(collection, text, k, user, rerank, coll_id=None, tool="ai.search"):
        return [{"content": "Salaries are reviewed in March.", "source": "handbook",
                 "score": 0.9}], 0
    monkeypatch.setattr(ai_vectors, "_admit", _admit)
    monkeypatch.setattr(ai_vectors, "_retrieve", _retrieve)
    monkeypatch.setattr(ai_vectors, "_gateway", lambda: ("http://gw", "k"))
    monkeypatch.setattr(ai_vectors, "egress_policy", lambda: "open")
    monkeypatch.setattr(ai_vectors.httpx, "AsyncClient", _Client)


def test_a_refused_generation_is_402_not_a_200_with_an_apology(refused_generation, rows):
    req = ai_vectors.RagRequest(collection="handbook", question="When are salaries reviewed?")
    with pytest.raises(HTTPException) as e:
        _run(ai_vectors._rag_impl(req, USER))
    assert e.value.status_code == 402
    assert "Max budget: 0.5" in e.value.detail
    assert [r["outcome"] for r in rows] == ["refused"]


def test_a_budget_refusal_is_audited_once_not_as_refused_and_error(rows):
    """`_logged` writes an `error` row for any exception. A refusal is not an error, and
    `refuse_over_budget` has already written its own row."""
    async def impl():
        raise await refuse_over_budget(actor=USER, tool="ai.rag",
                                       request_text="q", body=OVER)
    with pytest.raises(HTTPException) as e:
        _run(ai_vectors._logged("ai.rag", "handbook", "q", USER, impl))
    assert e.value.status_code == 402
    assert [r["outcome"] for r in rows] == ["refused"]


class _EmbedRefusingClient(_Client):
    """The gateway refusing at the first step a RAG call takes: the question's embedding."""
    async def post(self, url, **kw):
        assert url.endswith("/v1/embeddings"), url
        return _Resp(400, OVER)


@pytest.fixture
def refused_embedding(monkeypatch):
    async def _admit(name, user):
        return 7

    class _Pool:
        def acquire(self):
            raise AssertionError("the refusal comes before any database work")

    async def _pool():
        return _Pool()
    monkeypatch.setattr(ai_vectors, "_admit", _admit)
    monkeypatch.setattr(ai_vectors, "get_db_pool", _pool)
    monkeypatch.setattr(ai_vectors, "_gateway", lambda: ("http://gw", "k"))
    monkeypatch.setattr(ai_vectors, "egress_policy", lambda: "open")
    monkeypatch.setattr(ai_vectors.httpx, "AsyncClient", _EmbedRefusingClient)


def test_a_rag_call_refused_at_the_embedding_step_is_audited_as_ai_rag(refused_embedding, rows):
    """The row names the tool the caller used, not the step the gateway refused at:
    `_retrieve` embeds the question for both /ai/search and /ai/rag."""
    req = ai_vectors.RagRequest(collection="handbook", question="What is the Q4 quota?")
    with pytest.raises(HTTPException) as e:
        _run(ai_vectors._rag_impl(req, USER))
    assert e.value.status_code == 402
    assert [(r["tool"], r["outcome"]) for r in rows] == [("ai.rag", "refused")]
