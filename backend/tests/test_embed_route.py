"""/ai/embed is a tool call like the others: guarded, and on the record.

It sent its input to the embedding model with no PII guardrail and wrote nothing to
tool_call_log, so raw personal data could leave for an external provider through the
one AI route that left no trace.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app import tool_call_log
from app.api import ai_vectors

USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "svc", "role": "analyst",
        "auth_method": "service"}
PHONE = "연락처 010-1234-5678"


def _install(monkeypatch):
    sent, rows = [], []

    async def _embed(texts, **kw):
        sent.extend(texts)
        return [[0.0] * 4 for _ in texts]

    async def _record(**kw):
        rows.append(kw)
    monkeypatch.setattr(ai_vectors, "_embed", _embed)
    monkeypatch.setattr(tool_call_log, "record", _record)
    return sent, rows


def test_the_input_is_masked_before_it_is_embedded(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    sent, rows = _install(monkeypatch)
    out = asyncio.run(ai_vectors.embed(ai_vectors.EmbedRequest(input=[PHONE, "hello"]), USER))
    assert len(out["embeddings"]) == 2
    assert "010-1234-5678" not in sent[0] and sent[1] == "hello"
    assert rows[0]["tool"] == "ai.embed" and rows[0]["outcome"] == "ok"
    assert rows[0]["pii_masked"] >= 1 and rows[0]["hit_count"] == 2
    assert "010-1234-5678" not in rows[0]["request_text"]


def test_block_mode_refuses_and_records_the_refusal(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "block")
    sent, rows = _install(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_vectors.embed(ai_vectors.EmbedRequest(input=[PHONE]), USER))
    assert exc.value.status_code == 400
    assert sent == []
    assert rows[0]["outcome"] == "refused"


def test_ai_embed_is_a_tool_the_log_accepts():
    tool_call_log.build_row(actor=USER, tool="ai.embed", resource_kind="none",
                            resource=[], request_text="x")
