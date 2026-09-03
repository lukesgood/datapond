"""Why did last night's sync fail? — history and quality checks, read together.

Mocks here mirror the real return shapes of `app.api.connectors.get_sync_history`
(a plain list of session dicts) and `get_quality_checks` (`{"checks": [...]}`, each
check carrying `overall_status` — `ok` / `warning` / `alert` — not `severity`).
"""
import asyncio

from app.chat.analysis import connectors as mod


def _run(c):
    return asyncio.run(c)


def _session(**over):
    base = {"id": "s1", "started_at": "2026-09-02T22:00:00Z", "completed_at": None,
            "status": "success", "rows_processed": 100, "rows_failed": 0,
            "error_message": None, "tables": ["orders"], "duration_ms": 4000,
            "sync_mode": "full"}
    base.update(over)
    return base


def _check(**over):
    base = {"source_table": "orders", "checked_at": "2026-09-02T22:00:05Z",
            "rows_current": 100, "rows_previous": 100, "row_change_pct": 0.0,
            "row_change_status": "ok", "null_checks": {}, "overall_status": "ok",
            "warnings": []}
    base.update(over)
    return base


def test_a_failed_last_run_is_a_bad_signal_carrying_its_error(monkeypatch):
    async def _hist(connection_id, limit=20, user=None):
        return [_session(status="failed", error_message="connection refused",
                         started_at="2026-09-02T22:00:00Z", duration_ms=3000)]

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
        return [_session(status="success", duration_ms=40000)]

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": [_check(overall_status="alert", row_change_status="alert",
                                   row_change_pct=-64.0,
                                   warnings=["-64% against previous run"])]}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any(s["severity"] == "bad" for s in out["signals"])


def test_no_history_is_recorded_as_not_checked_not_as_health(monkeypatch):
    async def _hist(connection_id, limit=20, user=None):
        return []

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any("never" in r.lower() or "no sync" in r.lower()
               for r in out["not_checked"])
    assert not any(s["severity"] == "ok" for s in out["signals"])


def test_a_source_with_history_returns_rather_than_raising(monkeypatch):
    """Regression for the AttributeError from treating the plain list history
    handlers return as if it were wrapped in {"sessions": [...]}."""
    async def _hist(connection_id, limit=20, user=None):
        return [_session(status="success", duration_ms=4000)]

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert out["facts"]["runs_examined"] == 1


def test_an_alert_status_quality_check_is_a_bad_signal(monkeypatch):
    """Regression for filtering on a `severity` key that never exists — the real
    field is `overall_status`, with `alert` as its worst value."""
    async def _hist(connection_id, limit=20, user=None):
        return [_session(status="success", duration_ms=4000)]

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": [_check(overall_status="alert")]}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any(s["severity"] == "bad" for s in out["signals"])


# ── thresholds pinned: each judgment boundary this task introduces gets a test on
# each side, so a change to the number breaks a test rather than passing silently ──

def _sessions_with_durations_ms(*durations_ms):
    return [_session(status="success", duration_ms=d) for d in durations_ms]


def test_duration_trend_needs_at_least_three_timed_runs(monkeypatch):
    """Just outside: two timed runs — trend is skipped, not judged."""
    async def _hist(connection_id, limit=20, user=None):
        return _sessions_with_durations_ms(100_000, 10_000)

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
        return _sessions_with_durations_ms(10_000, 10_000, 10_000)

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
        # earlier average = 50s (from 50s, 50s); recent = 100s == 2 * 50s
        return _sessions_with_durations_ms(100_000, 50_000, 50_000)

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert not any("longer than" in s["statement"] for s in out["signals"])


def test_just_over_double_the_average_warns(monkeypatch):
    """Just outside the multiplier: recent > 2x the earlier average warns."""
    async def _hist(connection_id, limit=20, user=None):
        # earlier average = 49s (from 49s, 49s); recent = 100s > 2 * 49s == 98s
        return _sessions_with_durations_ms(100_000, 49_000, 49_000)

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
        # earlier average = 1s (from 1s, 1s); recent = 30s, ratio = 30x but at the floor
        return _sessions_with_durations_ms(30_000, 1_000, 1_000)

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert not any("longer than" in s["statement"] for s in out["signals"])


def test_just_over_thirty_seconds_warns_at_a_large_ratio(monkeypatch):
    """Just outside the floor: recent == 31s, with the same large ratio, does warn."""
    async def _hist(connection_id, limit=20, user=None):
        return _sessions_with_durations_ms(31_000, 1_000, 1_000)

    async def _quality(connection_id, limit=20, user=None):
        return {"checks": []}

    monkeypatch.setattr("app.api.connectors.get_sync_history", _hist)
    monkeypatch.setattr("app.api.connectors.get_quality_checks", _quality)

    out = _run(mod.diagnose_sync({"connection_id": "c1"}, {"id": "u1"}))
    assert any("longer than" in s["statement"] and s["severity"] == "warn"
               for s in out["signals"])
