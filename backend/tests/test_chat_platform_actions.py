"""Reads over the deployment itself: service health, metrics, events, storage."""
import asyncio

import pytest
from fastapi import Query

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
    """The mock's signature is the real handler's, not a convenient stand-in: the
    real `list_system_events` defaults `kind`/`source` to `Query(None)` objects, not
    plain `None`. A mock declaring plain `None` defaults (as this one used to) would
    pass even if the executor left `kind`/`source` unbound — the bug this pins
    (platform.recent_events failing on every call, Critical 2) would have sailed
    through it. With the real `Query(...)` sentinels as defaults here, an executor
    that omits `kind`/`source` leaves `seen["kind"]`/`seen["source"]` as that
    sentinel object, and the `is None` assertions below catch it.
    """
    seen = {}

    async def _fake(severity: str = Query(None, description="info | warning | critical"),
                    kind: str = Query(None),
                    source: str = Query(None),
                    hours: int = Query(168, ge=1, le=24 * 90),
                    limit: int = Query(200, ge=1, le=1000)):
        seen.update(hours=hours, limit=limit, severity=severity, kind=kind, source=source)
        return {"events": []}

    monkeypatch.setattr("app.api.system_events_routes.list_system_events", _fake)
    _run(mod.recent_events({"hours": 24, "limit": 50, "severity": None}, {"id": "u1"}))
    assert seen["hours"] == 24
    assert seen["limit"] == 50
    assert seen["severity"] is None
    assert seen["kind"] is None
    assert seen["source"] is None


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
