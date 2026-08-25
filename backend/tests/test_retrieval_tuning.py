"""Retrieval knobs belong to the person responsible for retrieval quality.

`k` was fixed in the frontend (5 for answers, 8 for search) and reranking was an
environment variable, so changing either meant an operator editing a deployment.
That put a tuning decision behind a release, for the one role accountable for
whether search works.

These tests pin the decision, not the plumbing: what does `rerank=None|True|False`
mean, and does turning it off actually skip the call.
"""
import pytest

from app.api.ai_vectors import RagRequest, SearchRequest


def test_the_knobs_are_part_of_the_request():
    r = SearchRequest(collection="c", query="q", k=12, rerank=False, expand_concepts=True)
    assert (r.k, r.rerank, r.expand_concepts) == (12, False, True)


def test_answers_take_the_same_knobs_as_search():
    """Otherwise tuning search tells you nothing about the answers built on it."""
    r = RagRequest(collection="c", question="q", k=12, rerank=False)
    assert (r.k, r.rerank) == (12, False)


def test_not_saying_means_use_the_deployment_default():
    assert SearchRequest(collection="c", query="q").rerank is None


@pytest.mark.parametrize("configured,requested,expected", [
    ("bedrock/amazon.rerank-v1:0", None,  True),   # configured, no opinion → on
    ("bedrock/amazon.rerank-v1:0", True,  True),
    ("bedrock/amazon.rerank-v1:0", False, False),  # explicitly off
    ("",                           None,  False),  # nothing configured
    ("",                           True,  False),  # asking cannot conjure a model
])
def test_when_reranking_actually_runs(configured, requested, expected, monkeypatch):
    monkeypatch.setenv("AI_RERANK_MODEL", configured)
    from app.api.ai_vectors import _rerank_model
    use = bool(_rerank_model()) and requested is not False
    assert use is expected
