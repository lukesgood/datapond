"""Why did spend change? Volume or unit price — a single window cannot tell you."""
import asyncio

from app.chat.analysis import spend as mod


def _run(c):
    return asyncio.run(c)


def _report(rows, detail=None, status_code=None):
    """`spend_report` returns {"start_date", "end_date", "report": [...]} — the list
    lives under "report", not "rows". On a gateway error it returns an empty "report"
    with a "detail" key (the raw upstream body, truncated) and a "status_code" key
    instead of raising."""
    out = {"report": rows}
    if detail is not None:
        out["detail"] = detail
    if status_code is not None:
        out["status_code"] = status_code
    return out


def _install(monkeypatch, current, previous):
    calls = []

    async def _fake(start_date=None, end_date=None):
        calls.append((start_date, end_date))
        return current if len(calls) == 1 else previous

    monkeypatch.setattr("app.api.ai_backends.spend_report", _fake)
    return calls


def test_a_rise_driven_by_call_count_is_named_as_volume(monkeypatch):
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 20.0, "requests": 200}]),
             previous=_report([{"model": "claude", "spend": 10.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert any("volume" in s["statement"].lower() for s in out["signals"])
    assert out["facts"]["current_total"] == 20.0


def test_a_rise_at_flat_volume_is_named_as_unit_price(monkeypatch):
    """Same number of calls, twice the bill — someone changed model."""
    _install(monkeypatch,
             current=_report([{"model": "opus", "spend": 20.0, "requests": 100}]),
             previous=_report([{"model": "haiku", "spend": 10.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert any("per call" in s["statement"].lower()
               or "unit" in s["statement"].lower() for s in out["signals"])


def test_no_change_is_an_ok_signal(monkeypatch):
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 10.0, "requests": 100}]),
             previous=_report([{"model": "claude", "spend": 10.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert all(s["severity"] == "ok" for s in out["signals"])


def test_an_empty_previous_window_is_not_reported_as_infinite_growth(monkeypatch):
    """A first week of use is not a hundred-percent increase; it is no comparison."""
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 10.0, "requests": 100}]),
             previous=_report([]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert any("no spend" in r.lower() or "nothing to compare" in r.lower()
               for r in out["not_checked"])


# ── unrecognised payload: rows exist, none carry a "spend" field ──────────────
# LiteLLM's row shape is not defined anywhere in this repo. If none of the rows carry a
# field named "spend", summing "spend" silently gives zero — and a zero reported as a
# fact would be indistinguishable from an account that truly spent nothing.

def test_rows_without_a_recognised_spend_field_are_not_checked(monkeypatch):
    _install(monkeypatch,
             current=_report([{"model": "claude", "cost": 20.0, "requests": 200}]),
             previous=_report([{"model": "claude", "spend": 10.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert out["facts"] == {}
    assert "current_total" not in out["facts"]
    assert any("recognise" in r.lower() for r in out["not_checked"])


# ── gateway errors vs true emptiness ────────────────────────────────────────────
# On a gateway error `spend_report` returns {"report": [], "detail": "..."} instead of
# raising. An empty report is therefore ambiguous — "nothing was spent" and "the
# gateway could not be asked" need different answers — so a "detail" key on an empty
# report is treated as a fetch failure, never as zero spend.

def test_a_gateway_error_on_the_current_window_is_not_checked(monkeypatch):
    _install(monkeypatch,
             current=_report([], detail="LiteLLM 500: internal error"),
             previous=_report([{"model": "claude", "spend": 5.0, "requests": 10}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert out["facts"] == {}
    assert any("error" in r.lower() or "gateway" in r.lower()
               for r in out["not_checked"])


def test_a_gateway_error_on_the_previous_window_is_distinguished_from_real_emptiness(monkeypatch):
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 10.0, "requests": 100}]),
             previous=_report([], detail="LiteLLM 500: internal error"))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert out["facts"]["current_total"] == 10.0
    assert any("error" in r.lower() or "gateway" in r.lower()
               for r in out["not_checked"])
    assert not any("no spend" in r.lower() for r in out["not_checked"])


# ── Minor 6: the raw upstream body never reaches the model ─────────────────────
# `spend_report`'s "detail" is `_short(r.text, 200)` — the raw LiteLLM response body.
# On an auth failure that body can echo part of an API key, and this action is
# reachable by anyone with `spend:read`. Report the failure and its HTTP status, not
# the body.

def test_the_raw_gateway_body_is_not_echoed_to_the_model(monkeypatch):
    secret_body = "Unauthorized: invalid key sk-litellm-abc123secretvalue"
    _install(monkeypatch,
             current=_report([], detail=secret_body, status_code=401),
             previous=_report([{"model": "claude", "spend": 5.0, "requests": 10}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    joined = " ".join(out["not_checked"])
    assert secret_body not in joined
    assert "sk-litellm" not in joined
    assert "401" in joined


def test_a_gateway_error_with_no_status_code_still_reports_generically(monkeypatch):
    """`spend_report`'s error shape predates `status_code`; a report missing it must
    still be treated as a failure, not silently pass the raw detail through."""
    secret_body = "Forbidden: rotate key sk-litellm-shouldnotleak"
    _install(monkeypatch,
             current=_report([], detail=secret_body),
             previous=_report([{"model": "claude", "spend": 5.0, "requests": 10}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    joined = " ".join(out["not_checked"])
    assert secret_body not in joined
    assert "sk-litellm" not in joined
    assert any("error" in r.lower() or "gateway" in r.lower() for r in out["not_checked"])


# ── threshold pins ───────────────────────────────────────────────────────────────
# `_MATERIAL_USD`, `_MATERIAL_FRACTION`, and the 0.6 attribution split are pinned on
# both sides — a changed constant fails a test here instead of silently reclassifying
# a real account's spend history.

def test_material_usd_threshold_just_inside_reports_flat(monkeypatch):
    assert mod._MATERIAL_USD == 1.0
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 5.99, "requests": 100}]),
             previous=_report([{"model": "claude", "spend": 5.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert any("flat" in s["statement"].lower() for s in out["signals"])


def test_material_usd_threshold_just_outside_reports_a_change(monkeypatch):
    assert mod._MATERIAL_USD == 1.0
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 6.01, "requests": 100}]),
             previous=_report([{"model": "claude", "spend": 5.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert not any("flat" in s["statement"].lower() for s in out["signals"])


def test_material_fraction_threshold_just_inside_reports_flat(monkeypatch):
    assert mod._MATERIAL_FRACTION == 0.15
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 9.05, "requests": 100}]),
             previous=_report([{"model": "claude", "spend": 8.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert any("flat" in s["statement"].lower() for s in out["signals"])


def test_material_fraction_threshold_just_outside_reports_a_change(monkeypatch):
    assert mod._MATERIAL_FRACTION == 0.15
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 7.95, "requests": 100}]),
             previous=_report([{"model": "claude", "spend": 6.9, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert not any("flat" in s["statement"].lower() for s in out["signals"])


def test_attribution_split_just_below_point_six_does_not_name_volume(monkeypatch):
    """call_growth (0.29) just below 0.6 * fraction (0.30) must not be attributed
    solely to volume — it falls through to "both moving", not "mostly on volume"."""
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 150.0, "requests": 129}]),
             previous=_report([{"model": "claude", "spend": 100.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert not any("mostly on volume" in s["statement"].lower() for s in out["signals"])


def test_attribution_split_just_above_point_six_names_volume(monkeypatch):
    """call_growth (0.31) just above 0.6 * fraction (0.30) is attributed to volume."""
    _install(monkeypatch,
             current=_report([{"model": "claude", "spend": 150.0, "requests": 131}]),
             previous=_report([{"model": "claude", "spend": 100.0, "requests": 100}]))
    out = _run(mod.diagnose_change({"days": 7}, {"id": "u1"}))
    assert any("mostly on volume" in s["statement"].lower() for s in out["signals"])
