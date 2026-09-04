"""Changing model configuration, with credentials out of reach.

The settings body is a dictionary by nature, so `extra="forbid"` on a params model
does not reach it. The allowlist is checked again at execution, and it is derived
rather than written so that a credential added later is excluded without anyone
remembering to exclude it.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind
from app.chat.analysis import settings as mod


def _run(c):
    return asyncio.run(c)


def test_it_is_destructive_and_targets_the_key():
    action = REGISTRY["settings.set_model_config"]
    assert action.kind is ActionKind.DESTRUCTIVE
    assert action.target_field == "key"
    assert action.permission == "settings:write"


def test_the_allowlist_is_the_difference_of_two_existing_sets():
    """Derived, not written: a credential added to SENSITIVE_KEYS later is excluded
    without anyone having to remember this file exists."""
    from app.api.system_settings import AI_ENV_MAP, SENSITIVE_KEYS
    assert mod.ALLOWED_KEYS == set(AI_ENV_MAP) - set(SENSITIVE_KEYS)
    assert mod.ALLOWED_KEYS == {"ai.provider", "ai.litellm_url", "ai.litellm_model"}


@pytest.mark.parametrize("key", ["ai.aws_access_key_id", "ai.aws_secret_access_key"])
def test_a_credential_key_is_refused_at_execution(key, monkeypatch):
    """Not merely absent from the schema — refused by the code that would write it."""
    called = []
    monkeypatch.setattr("app.api.system_settings.update_system_settings",
                        lambda body: called.append(body))
    with pytest.raises(ValueError):
        _run(mod.set_model_config({"key": key, "value": "AKIA..."}, {"id": "u1"}))
    assert called == []


def test_a_key_nobody_has_heard_of_is_refused(monkeypatch):
    called = []
    monkeypatch.setattr("app.api.system_settings.update_system_settings",
                        lambda body: called.append(body))
    with pytest.raises(ValueError):
        _run(mod.set_model_config({"key": "ai.something_new", "value": "x"}, {"id": "u1"}))
    assert called == []


def test_an_allowed_key_is_written(monkeypatch):
    seen = {}

    async def _fake(body):
        seen["body"] = body
        return {"ok": True}

    monkeypatch.setattr("app.api.system_settings.update_system_settings", _fake)
    _run(mod.set_model_config({"key": "ai.litellm_model", "value": "claude-sonnet-5"},
                              {"id": "u1"}))
    assert seen["body"].settings == {"ai.litellm_model": "claude-sonnet-5"}


def test_litellm_model_does_not_claim_to_strand_collections(monkeypatch):
    """ai.litellm_model maps to LITELLM_MODEL, the *generation* model
    (app/api/system_settings.py). What a collection is embedded with, and what a
    query is embedded with, is AI_EMBED_MODEL (app/api/ai_vectors.py:_embed_model),
    a different env var this action cannot reach at all — see
    app/chat/analysis/knowledge.py's diagnose_collection, which compares against
    exactly that. This action must never claim it can strand a collection."""
    monkeypatch.setenv("LITELLM_MODEL", "claude-sonnet-5")
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_model", "value": "claude-opus-5"}, {"id": "u1"}))
    assert not any(item.get("kind") == "collection" for item in out["items"])
    assert not out["not_checked"]
    assert out["items"], "a truthful consequence must still be reported"


def test_litellm_model_reports_the_generation_consequence(monkeypatch):
    monkeypatch.setenv("LITELLM_MODEL", "claude-sonnet-5")
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_model", "value": "claude-opus-5"}, {"id": "u1"}))
    text = repr(out)
    assert "claude-sonnet-5" in text and "claude-opus-5" in text


@pytest.mark.parametrize("key,env_name", [("ai.provider", "AI_PROVIDER"),
                                          ("ai.litellm_url", "LITELLM_URL")])
def test_provider_and_url_are_never_reported_as_nothing_depending(key, env_name,
                                                                   monkeypatch):
    """Critical 1&2: an early return of empty items and empty not_checked reads, per
    Dependents' own docstring, as the affirmative claim that nothing depends on this
    change — false for a key that repoints the single gateway path every chat, cited
    answer, and embedding call goes through."""
    monkeypatch.setenv(env_name, "old-value")
    out = _run(mod.dependents_set_model_config(
        {"key": key, "value": "new-value"}, {"id": "u1"}))
    assert out["items"] or out["not_checked"]
    assert out["items"], "the consequence is knowable, not merely unchecked"
    text = repr(out)
    assert "old-value" in text and "new-value" in text


def test_provider_card_does_not_claim_traffic_moves(monkeypatch):
    """AI_PROVIDER is read by nothing in this codebase — the only two hits repo-wide
    are its own entry in AI_ENV_MAP (app/api/system_settings.py) and this test.
    `_gateway()` (app/api/ai_vectors.py) decides routing from LITELLM_URL alone. The
    card for `ai.provider` must say that plainly and must never use language that
    would let a reader believe changing it repoints, moves, or affects any call —
    that was the false claim this action shared with `ai.litellm_url` before the fix
    (see the module docstring)."""
    monkeypatch.setenv("AI_PROVIDER", "litellm")
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.provider", "value": "none"}, {"id": "u1"}))
    assert out["items"], "a truthful consequence must still be reported"
    text = " ".join(item["effect"] for item in out["items"])
    assert "AI_PROVIDER is not read anywhere" in text
    assert "no traffic moves and no call is repointed" in text
    for forbidden in ("repoints", "repointing", "moves traffic", "changes where"):
        assert forbidden not in text, f"the card must not claim {forbidden!r}"


def test_litellm_url_card_still_claims_the_real_routing_consequence(monkeypatch):
    """The opposite pin: ai.litellm_url really does repoint the shared gateway path,
    and splitting it from ai.provider must not accidentally weaken that true claim
    too."""
    monkeypatch.setenv("LITELLM_URL", "https://old-gateway")
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_url", "value": "https://new-gateway"}, {"id": "u1"}))
    text = " ".join(item["effect"] for item in out["items"])
    assert "repoints every one of them" in text
    assert "https://old-gateway" in text and "https://new-gateway" in text


def test_current_value_display_for_an_unset_variable(monkeypatch):
    """settings.py:110 minor fix: os.getenv(..., "") used to render as the current
    value being the empty string, so the card read 'changing it from '' to ...' for
    a variable that was never set. It must say plainly that nothing is set."""
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.provider", "value": "litellm"}, {"id": "u1"}))
    text = " ".join(item["effect"] for item in out["items"])
    assert "not currently set" in text
    assert "''" not in text and "from '' " not in text


def test_an_unrecognised_key_is_reported_not_checked(monkeypatch):
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.nonsense", "value": "x"}, {"id": "u1"}))
    assert out["items"] == [] and out["not_checked"]


def test_the_description_names_the_settable_keys_so_the_model_asks_first():
    """Fix round 1: the old description said 'provider, gateway URL, or the active
    model name' — exactly the natural phrasing that does NOT satisfy named_by_user
    for ai.litellm_model (see the naming-question finding in task-9-report.md). The
    model must be told, in the description it reads before proposing, which literal
    keys exist and that the person has to name one themselves — otherwise it invites
    the model to propose against prose the gate will refuse."""
    action = REGISTRY["settings.set_model_config"]
    for key in ("ai.provider", "ai.litellm_url", "ai.litellm_model"):
        assert key in action.description

    key_field_description = action.params.model_fields["key"].description or ""
    for key in ("ai.provider", "ai.litellm_url", "ai.litellm_model"):
        assert key in key_field_description
