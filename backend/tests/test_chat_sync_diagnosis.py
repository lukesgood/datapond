"""Why did last night's sync fail? — history and quality checks, read together."""
import asyncio

from app.chat.analysis import connectors as mod


def _run(c):
    return asyncio.run(c)


def _history(*sessions):
    return {"sessions": list(sessions)}


def test_a_failed_last_run_is_a_bad_signal_carrying_its_error(monkeypatch):
    async def _hist(connection_id, limit=20, user=None):
        return _history({"status": "failed", "error": "connection refused",
                         "started_at": "2026-09-02T22:00:00Z", "duration_seconds": 3})

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    bad = [s for s in out["signals"] if s["severity"] == "bad"]
    assert bad and "connection refused" in str(bad[0]["evidence"])


def test_a_tripped_quality_check_is_reported_even_when_the_sync_succeeded(monkeypatch):
    """A green sync that loaded a tenth of the usual rows is the failure that does not
    announce itself."""
    async def _hist(connection_id, limit=20, user=None):
        return _history({"status": "success", "duration_seconds": 40})

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": [{"check": "row_count", "severity": "alert",
                            "detail": "-64% against previous run"}]}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any(s["severity"] == "bad" for s in out["signals"])


def test_no_history_is_recorded_as_not_checked_not_as_health(monkeypatch):
    async def _hist(connection_id, limit=20, user=None):
        return _history()

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any("never" in r.lower() or "no sync" in r.lower()
               for r in out["not_checked"])
    assert not any(s["severity"] == "ok" for s in out["signals"])


# ── thresholds pinned: each judgment boundary this task introduces gets a test on
# each side, so a change to the number breaks a test rather than passing silently ──

def _sessions_with_durations(*durations):
    return [{"status": "success", "duration_seconds": d} for d in durations]


def test_duration_trend_needs_at_least_three_timed_runs(monkeypatch):
    """Just outside: two timed runs — trend is skipped, not judged."""
    async def _hist(connection_id, limit=20, user=None):
        return _history(*_sessions_with_durations(100, 10))

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any("fewer than three timed runs" in r for r in out["not_checked"])
    assert not any("longer than" in s["statement"] for s in out["signals"])


def test_three_timed_runs_is_enough_to_judge_the_trend(monkeypatch):
    """Just inside: three timed runs — trend is judged (evaluated, not skipped),
    even though these particular durations do not trip the warn."""
    async def _hist(connection_id, limit=20, user=None):
        return _history(*_sessions_with_durations(10, 10, 10))

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert not any("fewer than three timed runs" in r for r in out["not_checked"])
    assert not any("longer than" in s["statement"] for s in out["signals"])


def test_exactly_double_the_average_does_not_warn(monkeypatch):
    """Just inside the multiplier: recent == 2x the earlier average is not
    'markedly longer' — the check requires strictly more than double."""
    async def _hist(connection_id, limit=20, user=None):
        # earlier average = 50 (from 50, 50); recent = 100 == 2 * 50
        return _history(*_sessions_with_durations(100, 50, 50))

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert not any("longer than" in s["statement"] for s in out["signals"])


def test_just_over_double_the_average_warns(monkeypatch):
    """Just outside the multiplier: recent > 2x the earlier average warns."""
    async def _hist(connection_id, limit=20, user=None):
        # earlier average = 49 (from 49, 49); recent = 100 > 2 * 49 == 98
        return _history(*_sessions_with_durations(100, 49, 49))

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any("longer than" in s["statement"] and s["severity"] == "warn"
               for s in out["signals"])


def test_thirty_seconds_or_less_never_warns_even_at_a_huge_ratio(monkeypatch):
    """Just inside the floor: recent == 30s does not warn no matter how large the
    ratio against the earlier average — a rounding artefact on a fast sync."""
    async def _hist(connection_id, limit=20, user=None):
        # earlier average = 1 (from 1, 1); recent = 30, ratio = 30x but at the floor
        return _history(*_sessions_with_durations(30, 1, 1))

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert not any("longer than" in s["statement"] for s in out["signals"])


def test_just_over_thirty_seconds_warns_at_a_large_ratio(monkeypatch):
    """Just outside the floor: recent == 31s, with the same large ratio, does warn."""
    async def _hist(connection_id, limit=20, user=None):
        return _history(*_sessions_with_durations(31, 1, 1))

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any("longer than" in s["statement"] and s["severity"] == "warn"
               for s in out["signals"])
