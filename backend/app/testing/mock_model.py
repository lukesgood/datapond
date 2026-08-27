"""A stand-in for the model gateway.

Acceptance runs against the live deployment, which proves the path works on a system
that has been running for weeks and repaired by hand along the way. It says nothing
about a fresh install — and the two checks that matter most for a release, upgrade and
rollback, need a cluster nobody has touched.

Such a cluster has no Bedrock credentials, so it has no model. This is the model.

Deterministic rather than realistic, on purpose. An embedding derived from the text
means the same text retrieves itself and unrelated text does not, which is the only
property a retrieval test actually leans on. A random vector would make the suite
flaky. A real model would make it slow, cost money on every run, and depend on the
credential the whole point is to do without.

Nothing here should ever be mistaken for a model's output, so everything it says
announces itself.
"""
import hashlib
import math
import re
from typing import Dict, List

MARKER = "[mock model]"


def embedding_vector(text: str, dim: int) -> List[float]:
    """A unit vector derived from the text.

    Token-level rather than whole-string: hashing the whole string would make two
    texts that share every word but one land nowhere near each other, and then a
    retrieval test would pass or fail on whether the query was worded identically.
    """
    vector = [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower()) or ["\x00"]
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        for i in range(0, len(digest), 2):
            slot = int.from_bytes(digest[i:i + 2], "big") % dim
            vector[slot] += 1.0

    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _grounded_answer(messages: List[dict]) -> str:
    """Echo the context back, when there is any.

    RAG asserts that an answer is grounded in what was retrieved. An answer that
    ignored its context would fail that assertion for a reason that has nothing to do
    with the code under test.
    """
    text = "\n".join(str(m.get("content") or "") for m in messages)
    after_context = re.split(r"context\s*:", text, flags=re.I)
    if len(after_context) > 1:
        body = after_context[1].strip()
        # Up to the question, if one follows.
        body = re.split(r"\n\s*(?:Q|Question)\s*:", body, flags=re.I)[0].strip()
        if body:
            return f"{MARKER} Based on the context provided: {body[:600]}"
    return f"{MARKER} This deployment is running a mock model provider, so this is not a real answer."


def chat_completion(messages: List[dict], model: str = "mock") -> Dict:
    answer = _grounded_answer(messages)
    prompt_tokens = sum(len(str(m.get("content") or "").split()) for m in messages)
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": len(answer.split()),
            "total_tokens": prompt_tokens + len(answer.split()),
        },
    }


def rerank(query: str, documents: List[str], top_n: int = 5) -> Dict:
    """Order by how many of the query's words a document contains.

    Crude, and enough: a rerank test asks whether reordering happened and whether the
    obviously-relevant document came first.
    """
    wanted = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    scored = []
    for i, doc in enumerate(documents):
        words = set(re.findall(r"[a-z0-9]+", (doc or "").lower()))
        overlap = len(wanted & words) / (len(wanted) or 1)
        scored.append({"index": i, "relevance_score": round(overlap, 4)})
    scored.sort(key=lambda r: (-r["relevance_score"], r["index"]))
    return {"id": "rerank-mock", "results": scored[:top_n]}
