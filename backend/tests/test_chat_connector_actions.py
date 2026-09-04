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


def test_all_reads_are_gated_on_the_connectors_capability():
    """The read actions (list/history/quality/diagnose) — the two reversible writes,
    set_schedule and set_sync_mode, are covered by their own tests: they share the
    capability but not the permission or kind."""
    from app.chat.actions import ActionKind
    reads = [a for a in mod.ACTIONS if a.kind is ActionKind.READ]
    assert len(reads) == 4
    for action in reads:
        assert action.capability == "connectors"
        assert action.permission == "connector:read"
        assert action.pages == ("*",)


def test_the_two_writes_are_mutations_gated_on_connector_write():
    from app.chat.actions import ActionKind
    writes = [a for a in mod.ACTIONS if a.kind is not ActionKind.READ]
    assert {a.id for a in writes} == {"connectors.set_schedule", "connectors.set_sync_mode"}
    for action in writes:
        assert action.kind is ActionKind.MUTATE
        assert action.capability == "connectors"
        assert action.permission == "connector:write"
        assert action.pages == ("*",)


def test_limit_is_bounded():
    """An unbounded limit is a way to pull the whole history into a model prompt."""
    from app.chat.actions import InvalidParams, validate_params
    action = next(a for a in mod.ACTIONS if a.id == "connectors.sync_history")
    with pytest.raises(InvalidParams):
        validate_params(action, {"connection_id": "c1", "limit": 5000})
