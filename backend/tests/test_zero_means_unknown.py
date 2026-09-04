"""Two numbers that used to mean two different things at once.

`spend_summary` returned total_spend 0.0 whether the month was idle or the gateway
was unreachable, and `/governance/stats` returned pii_detections 0 whether the scan
found nothing or could not run at all. Both are read by the assistant, which turns a
number into a sentence — and "you spent nothing" for "I could not ask" is the kind of
confident wrong answer that is worse than no answer.
"""
import asyncio

import pytest


def _run(c):
    return asyncio.run(c)


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp=None, raises=None):
        self._resp, self._raises = resp, raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        if self._raises:
            raise self._raises
        return self._resp


def _install(monkeypatch, client):
    from app.api import ai_backends
    monkeypatch.setattr(ai_backends, "_gateway", lambda: ("http://gw", "sk-test"))
    monkeypatch.setattr(ai_backends.httpx, "AsyncClient", lambda *a, **k: client)


def test_spend_summary_reports_a_real_total_when_the_gateway_answers(monkeypatch):
    from app.api.ai_backends import spend_summary
    _install(monkeypatch, _Client(_Resp(200, {"keys": [{"spend": 1.5}, {"spend": 2.0}]})))
    out = _run(spend_summary())
    assert out == {"total_spend": 3.5, "keys_with_spend": 2}
    assert "unavailable" not in out


def test_an_idle_month_is_still_reported_as_zero(monkeypatch):
    """Zero is a fine answer when it is a measurement."""
    from app.api.ai_backends import spend_summary
    _install(monkeypatch, _Client(_Resp(200, {"keys": []})))
    out = _run(spend_summary())
    assert out == {"total_spend": 0.0, "keys_with_spend": 0}


def test_a_rejected_request_is_unavailable_not_zero(monkeypatch):
    from app.api.ai_backends import spend_summary
    _install(monkeypatch, _Client(_Resp(401, {})))
    out = _run(spend_summary())
    assert "total_spend" not in out, "a failure must not carry a spend number at all"
    assert "401" in out["unavailable"]


def test_the_failure_does_not_echo_the_gateway_body(monkeypatch):
    """A 401 body from LiteLLM quotes part of the key it rejected."""
    from app.api.ai_backends import spend_summary
    _install(monkeypatch, _Client(_Resp(401, {"error": "bad key sk-live-abcdef"})))
    assert "sk-live-abcdef" not in repr(_run(spend_summary()))


def test_an_unreachable_gateway_is_unavailable_not_zero(monkeypatch):
    from app.api.ai_backends import spend_summary
    _install(monkeypatch, _Client(raises=RuntimeError("connect timeout")))
    out = _run(spend_summary())
    assert "total_spend" not in out
    assert out["unavailable"]


# ── /governance/stats ─────────────────────────────────────────────────────────

def _stats(monkeypatch, scan_result):
    from app.api import governance
    monkeypatch.setattr(governance, "_scan_pii_tables", lambda: scan_result)

    class _Q:
        def filter(self, *a, **k):
            return self

        def scalar(self):
            return 0

    class _DB:
        def query(self, *a, **k):
            return _Q()

    return governance.get_governance_stats(db=_DB())


def test_a_scan_that_could_not_run_reports_no_number(monkeypatch):
    assert _stats(monkeypatch, None).pii_detections is None


def test_a_scan_that_found_nothing_reports_zero(monkeypatch):
    """The distinction this file exists for: [] is a measurement, None is not."""
    assert _stats(monkeypatch, []).pii_detections == 0


def test_a_scan_that_found_something_counts_the_columns(monkeypatch):
    entry = type("E", (), {"pii_columns": [object(), object()]})()
    assert _stats(monkeypatch, [entry]).pii_detections == 2
