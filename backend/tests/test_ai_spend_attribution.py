"""Who spent it, and on which feature.

Two defects behind these tests, both found by reading the live gateway's own spend
logs rather than the code:

The assistant called `actor_payload("ai_chat")` but never `set_actor(user)`, so the
`user` field was absent and fourteen of thirty-two logged calls were attributed to
nobody. Ask AI and RAG both set it; the chat route was the one that did not.

And every one of those thirty-two rows carried no feature tag at all. The `app` name
was being sent inside `metadata`, but LiteLLM overwrites `metadata` in spend_logs
with its own object (status, max_retries, cost_breakdown, …), so the client's value
never survives. `request_tags` does survive — the live rows carry User-Agent entries
there — which is where the tag has to go instead.

The consequence of the second one is easy to understand and easy to miss: the
fallback `metadata.get("user_id")` in the usage endpoint is unreachable code. It can
never fire, which is exactly why the missing `set_actor` produced no attribution at
all rather than a degraded one.
"""
import pytest

from app.ai_context import actor_payload, set_actor
from app.api.ai_backends import usage_by_feature


@pytest.fixture(autouse=True)
def clear_actor():
    import app.ai_context as ctx
    token = ctx._actor.set(None)
    yield
    ctx._actor.reset(token)


# ── what we send ──────────────────────────────────────────────────────────────

def test_the_feature_is_sent_as_a_request_tag():
    """metadata does not survive into spend_logs; request_tags does."""
    assert actor_payload("ai_chat")["metadata"]["tags"] == ["app:ai_chat"]


def test_an_identified_caller_is_sent_as_the_user_field():
    set_actor({"id": "u-1", "username": "alice"})
    payload = actor_payload("ai_chat")
    assert payload["user"] == "u-1"


def test_the_feature_tag_survives_alongside_the_user():
    set_actor({"id": "u-1", "username": "alice"})
    assert actor_payload("ai_rag")["metadata"]["tags"] == ["app:ai_rag"]


def test_an_unidentified_call_still_carries_its_feature():
    """Background work has no user, and its cost still has to land somewhere
    nameable."""
    payload = actor_payload("ai_embed")
    assert "user" not in payload
    assert payload["metadata"]["tags"] == ["app:ai_embed"]


# ── what we read back ─────────────────────────────────────────────────────────

def _log(tags=None, spend=0.001, tokens=100):
    return {"request_tags": tags or [], "spend": spend, "total_tokens": tokens}


def test_spend_is_grouped_by_feature():
    rows = usage_by_feature([_log(["app:ai_chat"], 0.01), _log(["app:ai_chat"], 0.02),
                             _log(["app:ai_sql"], 0.05)])
    by = {r["app"]: r for r in rows}
    assert by["ai_chat"]["requests"] == 2
    assert by["ai_chat"]["spend"] == pytest.approx(0.03)
    assert by["ai_sql"]["requests"] == 1


def test_untagged_calls_are_named_rather_than_dropped():
    """Silently discarding them would make the feature totals disagree with the
    overall total, and the reader would trust the smaller number."""
    rows = usage_by_feature([_log([], 0.07)])
    assert rows[0]["app"] == "untagged"
    assert rows[0]["spend"] == pytest.approx(0.07)


def test_tags_that_are_not_ours_are_ignored():
    """LiteLLM adds its own — the live rows carry User-Agent entries."""
    rows = usage_by_feature([_log(["User-Agent: python-httpx", "app:ai_chat"], 0.01)])
    assert [r["app"] for r in rows] == ["ai_chat"]


def test_the_biggest_spender_comes_first():
    rows = usage_by_feature([_log(["app:ai_sql"], 0.01), _log(["app:ai_chat"], 0.09)])
    assert [r["app"] for r in rows] == ["ai_chat", "ai_sql"]


def test_tokens_are_summed_per_feature():
    rows = usage_by_feature([_log(["app:ai_chat"], 0.01, 100),
                             _log(["app:ai_chat"], 0.01, 250)])
    assert rows[0]["total_tokens"] == 350


def test_no_logs_is_an_empty_report_not_an_error():
    assert usage_by_feature([]) == []


# ── who may read it ───────────────────────────────────────────────────────────
#
# `spend:read` existed in the permission matrix and no endpoint used it. Everything
# about AI cost required admin — including /settings/ai/usage, which the Governance
# page already fetches. An auditor holds governance:read AND spend:read, so they
# could open that page and watch one panel 403.

def test_reading_ai_usage_requires_spend_read_not_admin():
    from app.api import ai_backends

    marker = [d for d in ai_backends.usage_summary.__dict__.get("__dependencies__", [])]
    # The gate is declared on the route, so read it from the router instead.
    route = next(r for r in ai_backends.router.routes
                 if getattr(r, "path", "") == "/settings/ai/usage")
    gates = {getattr(d.call, "__datapond_authorization__", None)
             for d in route.dependant.dependencies}
    assert "spend:read" in gates, f"gates were {gates}"


def test_reading_the_spend_report_requires_spend_read():
    from app.api import ai_backends

    route = next(r for r in ai_backends.router.routes
                 if getattr(r, "path", "") == "/settings/ai/spend")
    gates = {getattr(d.call, "__datapond_authorization__", None)
             for d in route.dependant.dependencies}
    assert "spend:read" in gates


def test_configuring_backends_still_requires_admin():
    """Reading what was spent is not the same as changing which models exist or
    issuing keys against them."""
    from app.api import ai_backends

    for path in ("/settings/ai/backends", "/settings/ai/keys"):
        route = next(r for r in ai_backends.router.routes
                     if getattr(r, "path", "") == path and "GET" in r.methods)
        gates = {getattr(d.call, "__datapond_authorization__", None)
                 for d in route.dependant.dependencies}
        assert "role:admin" in gates, f"{path} gates were {gates}"
