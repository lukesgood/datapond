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


def test_changing_the_embedding_model_lists_the_collections_it_will_strand(monkeypatch):
    """The reason this action computes dependents at all: a collection embedded with
    one model and queried through another loses retrieval quality with nothing logged.
    knowledge.diagnose_collection finds that afterwards; this shows it before."""
    monkeypatch.setattr(mod, "_collections_by_embed_model",
                        lambda: [{"name": "handbook", "embed_model": "titan-v1"},
                                 {"name": "tickets", "embed_model": "titan-v2"}])
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_model", "value": "titan-v2"}, {"id": "u1"}))
    names = repr(out)
    assert "handbook" in names and "titan-v1" in names


def test_collections_that_cannot_be_listed_are_not_checked(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "_collections_by_embed_model", _boom)
    out = _run(mod.dependents_set_model_config(
        {"key": "ai.litellm_model", "value": "titan-v2"}, {"id": "u1"}))
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
