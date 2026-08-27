"""A stand-in for the model gateway, so a fresh install can be tested without one.

Acceptance runs against the live deployment, which proves the path works on a system
that has been running for weeks and repaired by hand. It says nothing about whether a
fresh install works — and the release checks that matter most, upgrade and rollback,
need a cluster nobody has touched.

Such a cluster has no Bedrock credentials, so it has no model. This is the model:
OpenAI-compatible, deterministic, and obviously fake.

Deterministic matters more than realistic. An embedding derived from the text means
the same text retrieves itself and different text does not, which is the only property
retrieval tests actually rely on. A random vector would make the suite flaky; a real
model would make it slow, costly, and dependent on a credential the point is to avoid.
"""
import pytest

from app.testing.mock_model import chat_completion, embedding_vector, rerank


def test_the_same_text_always_embeds_the_same_way():
    assert embedding_vector("refund policy", 8) == embedding_vector("refund policy", 8)


def test_different_text_embeds_differently():
    assert embedding_vector("refund policy", 8) != embedding_vector("server capacity", 8)


def test_the_dimension_is_what_was_asked_for():
    """ai_chunks.embedding is vector(1024). A vector of the wrong length is rejected
    by the column, which would look like a broken deployment rather than a broken
    mock."""
    assert len(embedding_vector("anything", 1024)) == 1024


def test_the_vector_is_normalised():
    """Cosine distance on an unnormalised vector still works, but scores stop being
    comparable between runs, and a retrieval assertion on a score would drift."""
    v = embedding_vector("refund policy", 64)
    assert abs(sum(x * x for x in v) ** 0.5 - 1.0) < 1e-6


def test_similar_text_scores_closer_than_unrelated_text():
    """The one property a retrieval test needs: a query finds its own document."""
    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    doc = embedding_vector("the refund policy is seven business days", 256)
    near = embedding_vector("refund policy seven business days", 256)
    far = embedding_vector("kubernetes node autoscaling configuration", 256)
    assert cos(doc, near) > cos(doc, far)


def test_a_chat_completion_has_the_shape_the_client_expects():
    out = chat_completion([{"role": "user", "content": "hello"}], model="default")
    assert out["choices"][0]["message"]["role"] == "assistant"
    assert out["choices"][0]["message"]["content"]
    assert out["usage"]["total_tokens"] > 0


def test_the_answer_says_it_is_a_mock():
    """Nothing produced here should ever be mistaken for a model's output — not in a
    log, not in a screenshot, not in a test failure someone is reading at speed."""
    out = chat_completion([{"role": "user", "content": "hello"}], model="default")
    assert "mock" in out["choices"][0]["message"]["content"].lower()


def test_a_cited_answer_repeats_the_context_it_was_given():
    """RAG asserts that an answer is grounded. An answer that ignores its context
    would fail that for the wrong reason."""
    msgs = [{"role": "user", "content": "Context: refunds take seven business days.\n\nQ: how long?"}]
    out = chat_completion(msgs, model="default")
    assert "seven business days" in out["choices"][0]["message"]["content"]


def test_rerank_returns_every_document_with_a_score():
    out = rerank("refund", ["a refund takes seven days", "unrelated text"], top_n=2)
    assert len(out["results"]) == 2
    assert all("relevance_score" in r for r in out["results"])


def test_rerank_puts_the_matching_document_first():
    out = rerank("refund", ["unrelated text", "a refund takes seven days"], top_n=2)
    assert out["results"][0]["index"] == 1


# ── the HTTP surface ──────────────────────────────────────────────────────────

def test_the_gateway_refuses_to_start_without_being_asked():
    """A stand-in that answers real traffic because an environment variable was left
    pointing at it is worse than no stand-in: every answer is wrong and nothing looks
    wrong."""
    import os

    from app.testing.mock_gateway import main
    old = os.environ.pop("MOCK_MODEL_PROVIDER", None)
    try:
        assert main() == 2
    finally:
        if old is not None:
            os.environ["MOCK_MODEL_PROVIDER"] = old


def test_it_answers_the_three_paths_the_backend_uses():
    from app.testing.mock_gateway import app
    paths = {r.path for r in app.routes}
    assert {"/v1/chat/completions", "/v1/embeddings", "/v1/rerank"} <= paths


def test_it_never_returns_a_tool_call():
    """The assistant branches on tool_calls. A mock that invented one would send it
    down a path nobody wrote, and the suite would be testing the mock."""
    from app.testing.mock_model import chat_completion
    out = chat_completion([{"role": "user", "content": "search the catalog"}])
    assert "tool_calls" not in out["choices"][0]["message"]
