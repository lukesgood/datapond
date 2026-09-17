"""The generated answer is guarded, not just the question and the retrieved chunks.

The context handed to the model is masked on the way in, but the answer is the model's
own text. It can restate what it saw, and under `block` the retrieval path returns raw
content by design — so guarding only the input leaves the last hop, the bytes the
caller actually receives, unchecked.

Only the RAG answer is guarded this way. The generated SQL in ai_sql is deliberately
left alone: masking a literal inside a WHERE clause produces a statement that no longer
parses, and that path already guards its question and context on the way in.
"""
import asyncio


def _aval(value):
    async def _coro():
        return value
    return _coro()


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code, self._payload, self.text = status, payload, ""

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return _Resp(self._payload)


def _rag(monkeypatch, answer, mode="mask"):
    import app.api.ai_vectors as v
    monkeypatch.setenv("PII_GUARDRAIL_MODE", mode)
    hits = [{"source": "doc1", "content": "context text", "id": "1", "score": 0.9}]
    monkeypatch.setattr(v, "_retrieve", lambda *a, **k: _aval((hits, 0)))
    monkeypatch.setattr(v, "_gateway", lambda: ("http://gw", ""))
    monkeypatch.setattr(v, "egress_policy", lambda: "cloud-allowed")
    monkeypatch.setattr(v.httpx, "AsyncClient",
                        lambda *a, **k: _Client({"choices": [{"message": {"content": answer}}]}))
    req = v.RagRequest(collection="c", question="who signed it?")
    user = {"id": "00000000-0000-0000-0000-000000000001", "username": "u", "role": "admin"}
    return asyncio.run(v._rag_impl(req, user))


def test_pii_in_the_answer_is_masked(monkeypatch):
    out = _rag(monkeypatch, "담당자는 010-1234-5678 로 연락하세요.")
    assert "010-1234-5678" not in out["answer"]
    assert "[휴대전화]" in out["answer"]
    assert out["pii_masked"] >= 1
    assert out["has_ai"] is True


def test_a_credential_in_the_answer_is_masked(monkeypatch):
    """The same guard covers secrets, because they travel the same detector."""
    out = _rag(monkeypatch, "Use AKIAIOSFODNN7EXAMPLE to authenticate.")
    assert "AKIAIOSFODNN7EXAMPLE" not in out["answer"]
    assert out["pii_masked"] >= 1


def test_block_mode_does_not_return_the_answer(monkeypatch):
    # checksum-valid on purpose: _valid_rrn rejects a made-up 13-digit run, so an
    # invalid number proves nothing about the guard.
    out = _rag(monkeypatch, "주민등록번호는 900101-1234568 입니다.", mode="block")
    assert "900101-1234568" not in out["answer"]
    assert "block" in out["answer"].lower()
    assert out["citations"], "citations still returned — only the generated text is withheld"


def test_a_clean_answer_is_returned_unchanged(monkeypatch):
    text = "The contract was signed in March by the finance team."
    out = _rag(monkeypatch, text)
    assert out["answer"] == text
    assert out["pii_masked"] == 0
