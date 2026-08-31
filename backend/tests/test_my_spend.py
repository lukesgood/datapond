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


# ── whose account's spend may be read ───────────────────────────────────────

def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


ENGINEER = {"id": "00000000-0000-0000-0000-00000000ae01", "role": "ai_engineer"}
ACCOUNT_ID = "00000000-0000-0000-0000-0000000005ac"


def test_one_persons_ai_generate_does_not_read_another_accounts_spend(monkeypatch):
    """`/service-accounts/{id}/usage` takes the id from the path, and ai:generate is
    held by most roles. Without an ownership check, anyone holding it could read any
    service account's — or any colleague's — full spend history by guessing a UUID.
    Every other service-account route is admin-only; this one has to be at least as
    careful as the thing it reports on."""
    from fastapi import HTTPException

    from app.api import ai_backends

    def no_gateway_call(*a, **k):
        raise AssertionError("the refusal must come before the gateway is queried")

    monkeypatch.setattr(ai_backends, "_gateway", no_gateway_call)

    with pytest.raises(HTTPException) as exc:
        _run(ai_backends.service_account_usage(ACCOUNT_ID, ENGINEER))
    assert exc.value.status_code == 403


def test_an_account_reads_its_own_spend_and_an_admin_reads_any(monkeypatch):
    from app.api import ai_backends

    monkeypatch.setattr(ai_backends, "_gateway", lambda: ("http://gw", "k"))

    class _NoLogs:
        status_code = 500

        def json(self):
            return {}

    class _Client:
        async def get(self, *a, **k):
            return _NoLogs()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ai_backends.httpx, "AsyncClient", lambda **k: _Client())

    itself = {"id": ACCOUNT_ID, "role": "ai_engineer"}
    admin = {"id": "00000000-0000-0000-0000-0000000000ad", "role": "admin"}
    assert _run(ai_backends.service_account_usage(ACCOUNT_ID, itself))["requests"] == 0
    assert _run(ai_backends.service_account_usage(ACCOUNT_ID, admin))["requests"] == 0
