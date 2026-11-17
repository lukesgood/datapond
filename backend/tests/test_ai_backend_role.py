"""Only a generation model may become the active default."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import ai_backends as ab


@pytest.mark.parametrize("name, model, info, role", [
    ("default", "bedrock/us.anthropic.claude-haiku-4-5", {}, "generation"),
    ("embed", "bedrock/amazon.titan-embed-text-v2:0", {}, "embedding"),
    ("rerank", "bedrock/arn:aws:bedrock:us-east-1::foundation-model/cohere.rerank-v3-5:0", {}, "rerank"),
    ("x", "openai/gpt-4o", {"mode": "embedding"}, "embedding"),
    ("chat", "bedrock/us.anthropic.claude-sonnet-4-5", {}, "generation"),
])
def test_role(name, model, info, role, monkeypatch):
    monkeypatch.delenv("AI_RERANK_MODEL", raising=False)
    assert ab.backend_role(name, model, info) == role


def test_set_active_refuses_an_embedding_model(monkeypatch):
    async def _role(*a):
        return "embedding"
    async def _never(*a):
        raise AssertionError("must not set")
    monkeypatch.setattr(ab, "_gateway", lambda: ("http://gw", "k"))
    monkeypatch.setattr(ab, "_role_of_registered_model", _role)
    monkeypatch.setattr(ab, "_set_active_model", _never)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ab.set_active(ab.ActivePatch(model_name="embed")))
    assert exc.value.status_code == 400 and "embedding" in exc.value.detail


def test_set_active_allows_when_the_gateway_cannot_say(monkeypatch):
    async def _role(*a):
        return None
    done = []
    async def _set(name):
        done.append(name)
    monkeypatch.setattr(ab, "_gateway", lambda: ("http://gw", "k"))
    monkeypatch.setattr(ab, "_role_of_registered_model", _role)
    monkeypatch.setattr(ab, "_set_active_model", _set)
    asyncio.run(ab.set_active(ab.ActivePatch(model_name="chat")))
    assert done == ["chat"]
