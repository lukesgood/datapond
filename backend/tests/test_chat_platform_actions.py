"""Reads over the deployment itself: service health, metrics, events, storage."""
import asyncio

import pytest

from app.chat.analysis import platform as mod


def _run(c):
    return asyncio.run(c)


def test_service_health_passes_the_service_name(monkeypatch):
    seen = {}

    async def _fake(service):
        seen["service"] = service
        return {"status": "healthy"}

    monkeypatch.setattr("app.api.services.get_service_health", _fake)
    out = _run(mod.service_health({"service": "backend"}, {"id": "u1"}))
    assert seen["service"] == "backend"
    assert out["health"] == {"status": "healthy"}


def test_recent_events_bounds_the_window_and_the_page(monkeypatch):
    seen = {}

    async def _fake(severity=None, kind=None, source=None, hours=168, limit=200):
        seen.update(hours=hours, limit=limit, severity=severity)
        return {"events": []}

    monkeypatch.setattr("app.api.system_events_routes.list_system_events", _fake)
    _run(mod.recent_events({"hours": 24, "limit": 50, "severity": None}, {"id": "u1"}))
    assert seen == {"hours": 24, "limit": 50, "severity": None}


def test_storage_overview_takes_no_parameters(monkeypatch):
    async def _fake():
        return {"buckets": []}

    monkeypatch.setattr("app.api.storage.get_storage_overview", _fake)
    out = _run(mod.storage_overview({}, {"id": "u1"}))
    assert out["storage"] == {"buckets": []}


def test_all_four_are_reads_on_service_manage_with_no_capability():
    for action in mod.ACTIONS:
        assert action.kind.value == "read"
        assert action.permission == "service:manage"
        assert action.capability is None
        assert action.pages == ("*",)


def test_the_event_window_is_bounded():
    from app.chat.actions import InvalidParams, validate_params
    action = next(a for a in mod.ACTIONS if a.id == "platform.recent_events")
    with pytest.raises(InvalidParams):
        validate_params(action, {"hours": 100000})
