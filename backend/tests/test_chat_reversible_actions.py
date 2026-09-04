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
        seen.update(name=name, username=body.username, user=user)
        return {"ok": True}

    monkeypatch.setattr("app.api.ai_vectors.add_member", _fake)
    user = {"id": "u1"}
    _run(mod.add_member_action({"collection": "handbook", "username": "ada",
                                "role": "viewer"}, user))
    assert seen == {"name": "handbook", "username": "ada", "user": user}


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


# ── Important 5 — a failed preview read must say so, not look like a lookup that
# found nothing. governance.py, users.py and settings.py already put the error in
# `summary`; knowledge.py and connectors.py instead returned current_role: null /
# is_member: false / current_schedule: null — indistinguishable from a genuine
# non-member or an unscheduled connection. ─────────────────────────────────────

def test_refresh_schedule_preview_reports_a_failed_read_in_summary(monkeypatch):
    from app.chat.analysis import knowledge as mod

    async def _boom(name, user=None):
        raise RuntimeError("schedule store unavailable")

    monkeypatch.setattr("app.api.ai_vectors.get_schedule", _boom)
    out = _run(mod.preview_set_refresh_schedule(
        {"collection": "handbook", "interval_minutes": 30}, {"id": "u1"}))
    assert "current_schedule" not in out
    assert "could not be read" in out.get("summary", "")


def test_add_member_preview_reports_a_failed_read_in_summary(monkeypatch):
    from app.chat.analysis import knowledge as mod

    async def _boom(name, user=None):
        raise RuntimeError("member store unavailable")

    monkeypatch.setattr("app.api.ai_vectors.list_members", _boom)
    out = _run(mod.preview_add_member(
        {"collection": "handbook", "username": "ada", "role": "reader"}, {"id": "u1"}))
    assert "current_role" not in out
    assert "could not be read" in out.get("summary", "")


def test_remove_member_preview_reports_a_failed_read_in_summary(monkeypatch):
    from app.chat.analysis import knowledge as mod

    async def _boom(name, user=None):
        raise RuntimeError("member store unavailable")

    monkeypatch.setattr("app.api.ai_vectors.list_members", _boom)
    out = _run(mod.preview_remove_member(
        {"collection": "handbook", "username": "ada"}, {"id": "u1"}))
    assert "is_member" not in out
    assert "could not be read" in out.get("summary", "")


def test_connector_schedule_preview_reports_a_failed_read_in_summary(monkeypatch):
    from app.chat.analysis import connectors as mod

    async def _boom(connection_id, user=None):
        raise RuntimeError("connector store unavailable")

    monkeypatch.setattr("app.api.connectors.get_connection", _boom)
    out = _run(mod.preview_set_schedule(
        {"connection_id": "c1", "cron": "0 2 * * *"}, {"id": "u1"}))
    assert "current_schedule" not in out
    assert "could not be read" in out.get("summary", "")


def test_connector_sync_mode_preview_reports_a_failed_read_in_summary(monkeypatch):
    from app.chat.analysis import connectors as mod

    async def _boom(connection_id, user=None):
        raise RuntimeError("connector store unavailable")

    monkeypatch.setattr("app.api.connectors.get_connection", _boom)
    out = _run(mod.preview_set_sync_mode(
        {"connection_id": "c1", "sync_mode": "full"}, {"id": "u1"}))
    assert "connection_name" not in out
    assert "could not be read" in out.get("summary", "")
