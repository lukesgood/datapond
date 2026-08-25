"""What *I* spent.

A role holding ai:generate can spend model tokens. Until now the only way to see the
result was /settings/ai/usage, which takes no caller argument: it reports the whole
deployment's total and every user's share. So the choice was between showing a
data_scientist everyone's spend or showing them nothing, and it had been nothing.

Neither is right. Spend attribution exists precisely so a person can be accountable
for their own use, which needs a view scoped to them.
"""
import pytest

from app.api.ai_backends import spend_for_user


def _log(user, spend=0.01, tokens=100, tags=None, model="m"):
    return {"end_user": user, "spend": spend, "total_tokens": tokens,
            "request_tags": tags or [], "model": model}


def test_only_the_callers_rows_are_counted():
    out = spend_for_user([_log("me", 0.01), _log("someone-else", 9.99)], "me")
    assert out["spend"] == pytest.approx(0.01)
    assert out["requests"] == 1


def test_a_user_with_no_usage_gets_zero_not_an_error():
    out = spend_for_user([_log("someone-else")], "me")
    assert out["spend"] == 0 and out["requests"] == 0


def test_the_breakdown_by_feature_is_also_scoped():
    out = spend_for_user([_log("me", 0.02, tags=["app:ai_chat"]),
                          _log("me", 0.03, tags=["app:ai_sql"]),
                          _log("other", 5.00, tags=["app:ai_chat"])], "me")
    by = {a["app"]: a["spend"] for a in out["apps"]}
    assert by["ai_chat"] == pytest.approx(0.02)
    assert by["ai_sql"] == pytest.approx(0.03)


def test_unattributed_rows_are_never_claimed_by_anyone():
    """Spend logged against no user belongs to nobody. Folding it into whoever asks
    would invent a number, and the person reading it would act on it."""
    out = spend_for_user([_log(None, 4.00), _log("", 4.00)], "me")
    assert out["spend"] == 0


def test_tokens_are_summed():
    out = spend_for_user([_log("me", 0.01, 120), _log("me", 0.01, 80)], "me")
    assert out["total_tokens"] == 200


def test_the_models_the_caller_actually_used_are_listed():
    out = spend_for_user([_log("me", 0.01, model="haiku"), _log("me", 0.02, model="sonnet"),
                          _log("other", 9.0, model="opus")], "me")
    assert sorted(out["models"]) == ["haiku", "sonnet"]
