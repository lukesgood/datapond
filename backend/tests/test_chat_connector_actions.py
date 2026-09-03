"""Reads over sources: what exists, what ran, and what the quality checks found."""
import asyncio

import pytest

from app.chat.analysis import connectors as mod


def _run(c):
    return asyncio.run(c)


def test_list_sources_passes_the_caller_through(monkeypatch):
    """The handler takes `user` as a Depends default. Called without it, the Depends
    object arrives as the user and the failure surfaces far from here."""
    seen = {}

    async def _fake(user):
        seen["user"] = user
        return [{"id": "c1", "name": "crm"}]

    monkeypatch.setattr("app.api.connectors.list_connections", _fake)
    user = {"id": "u1"}
    out = _run(mod.list_sources({}, user))
    assert seen["user"] is user
    assert out["sources"] == [{"id": "c1", "name": "crm"}]


def test_sync_history_passes_id_limit_and_user(monkeypatch):
    seen = {}

    async def _fake(connection_id, limit=20, user=None):
        seen.update(connection_id=connection_id, limit=limit, user=user)
        return {"sessions": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _fake)
    user = {"id": "u1"}
    _run(mod.sync_history({"connection_id": "c1", "limit": 5}, user))
    assert seen == {"connection_id": "c1", "limit": 5, "user": user}


def test_quality_checks_passes_id_limit_and_user(monkeypatch):
    seen = {}

    async def _fake(connection_id, limit=20, user=None):
        seen.update(connection_id=connection_id, limit=limit, user=user)
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_quality_checks", _fake)
    user = {"id": "u1"}
    _run(mod.quality_checks({"connection_id": "c1", "limit": 20}, user))
    assert seen == {"connection_id": "c1", "limit": 20, "user": user}


def test_all_three_are_reads_gated_on_the_connectors_capability():
    for action in mod.ACTIONS:
        assert action.kind.value == "read"
        assert action.capability == "connectors"
        assert action.permission == "connector:read"
        assert action.pages == ("*",)


def test_limit_is_bounded():
    """An unbounded limit is a way to pull the whole history into a model prompt."""
    from app.chat.actions import InvalidParams, validate_params
    action = next(a for a in mod.ACTIONS if a.id == "connectors.sync_history")
    with pytest.raises(InvalidParams):
        validate_params(action, {"connection_id": "c1", "limit": 5000})
