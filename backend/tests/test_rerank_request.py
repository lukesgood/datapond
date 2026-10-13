"""The rerank request must be one the provider accepts.

Bedrock's Rerank API refuses a request whose numberOfResults exceeds the number of
documents ("Cannot provide numberOfResults value that exceeds the number of
sources"), and LiteLLM passes top_n through as numberOfResults. The backend asked for
top_n=k even when fewer hits came back, so every such search fell back to vector
order with only a warning in the log (seen on the live node, 2026-10-13).
"""
import asyncio

from app.api import ai_vectors


class _Resp:
    status_code = 200

    def __init__(self, n):
        self._n = n
        self.text = ""

    def json(self):
        # Provider order: reverse of the vector order, so a rerank is observable.
        return {"results": [{"index": i, "relevance_score": 1.0 - i / 10}
                            for i in reversed(range(self._n))]}


def _fake_client(sent):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append(json)
            return _Resp(len(json["documents"]))

    return _Client


def _hits(n):
    return [{"source": f"s{i}", "content": f"c{i}"} for i in range(n)]


def _run(monkeypatch, hits, k):
    sent = []
    monkeypatch.setattr(ai_vectors, "_rerank_model", lambda: "rerank")
    monkeypatch.setattr(ai_vectors, "_gateway", lambda: ("http://gw", "k"))
    monkeypatch.setattr(ai_vectors.httpx, "AsyncClient", _fake_client(sent))
    out = asyncio.run(ai_vectors._rerank("q", hits, k))
    return sent, out


def test_top_n_never_exceeds_the_documents_sent(monkeypatch):
    sent, out = _run(monkeypatch, _hits(3), k=5)
    assert sent[0]["top_n"] == 3
    assert [h["source"] for h in out] == ["s2", "s1", "s0"]


def test_top_n_is_k_when_there_are_more_documents_than_k(monkeypatch):
    sent, out = _run(monkeypatch, _hits(8), k=5)
    assert sent[0]["top_n"] == 5
    assert len(out) == 5
