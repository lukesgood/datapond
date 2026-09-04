"""Configuration the assistant may change behind the ordinary approval card.

Every one of these is undoable from what is on screen: set the number back, flip the
switch back, re-add the member. That is the whole reason they do not need the
destructive gate — see the grading rule in the spec.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind

IDS = ["knowledge.set_refresh_schedule", "knowledge.add_member",
       "knowledge.remove_member", "connectors.set_schedule",
       "connectors.set_sync_mode"]


def _run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("action_id", IDS)
def test_each_is_a_mutate_not_a_read_and_not_destructive(action_id):
    action = REGISTRY[action_id]
    assert action.kind is ActionKind.MUTATE, (
        f"{action_id} changes state, so it must not execute without approval")
    assert action.target_field is None, (
        f"{action_id} is reversible; a typed target would be friction with no payer")


@pytest.mark.parametrize("action_id", IDS)
def test_each_has_a_previewer(action_id):
    """A card that says nothing about what will change is a card nobody reads."""
    from app.chat.analysis import PREVIEWERS
    assert action_id in PREVIEWERS


def test_the_knowledge_actions_pass_the_caller_through(monkeypatch):
    """These handlers take `user` as a Depends default. Called without it, the Depends
    object arrives as the user and the collection ACL is asked about the wrong thing."""
    from app.chat.analysis import knowledge as mod
    seen = {}

    async def _fake(name, body, user=None):
        seen.update(name=name, user=user)
        return {"ok": True}

    monkeypatch.setattr("app.api.ai_vectors.add_member", _fake)
    user = {"id": "u1"}
    _run(mod.add_member_action({"collection": "handbook", "email": "a@b.c",
                                "role": "viewer"}, user))
    assert seen == {"name": "handbook", "user": user}


def test_the_connector_actions_pass_the_caller_through(monkeypatch):
    from app.chat.analysis import connectors as mod
    seen = {}

    async def _fake(connection_id, request=None, user=None):
        seen.update(connection_id=connection_id, user=user)
        return {"ok": True}

    monkeypatch.setattr("app.api.connectors.set_schedule", _fake)
    user = {"id": "u1"}
    _run(mod.set_schedule_action({"connection_id": "c1", "cron": "0 2 * * *"}, user))
    assert seen == {"connection_id": "c1", "user": user}
