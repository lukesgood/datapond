"""The throttle has to be wired in front of the password check, not behind it.

A limiter placed after the bcrypt verify still rejects the attempt, so it looks
correct in a test that only counts 401s — while leaving the CPU cost, which is half
the reason the limiter exists, entirely unmitigated.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import auth as auth_module


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    import time
    from app.rate_limit import LoginThrottle
    monkeypatch.setattr(auth_module, "_login_throttle",
                        LoginThrottle(clock=time.monotonic, max_failures=2,
                                      base_lockout=60, max_lockout=600,
                                      ip_max_failures=100, ip_window=300))
    yield
    monkeypatch.setattr(auth_module, "_login_throttle", None)


class Req:
    client = type("C", (), {"host": "203.0.113.5"})()
    headers = {}


def _login(username="alice", password="wrong"):
    return asyncio.run(auth_module.login(
        auth_module.LoginRequest(username=username, password=password), Req()))


def test_a_locked_out_attempt_never_reaches_the_password_check(monkeypatch):
    """The proof of ordering: make the verify explode, then confirm the 429 comes
    back anyway. If the limiter ran after it, this test would raise instead."""
    auth_module.login_throttle().record_failure("alice", "203.0.113.5")
    auth_module.login_throttle().record_failure("alice", "203.0.113.5")

    def _must_not_run(*a, **kw):
        raise AssertionError("password verification ran while rate limited")

    monkeypatch.setattr(auth_module, "_verify_password", _must_not_run)

    with pytest.raises(HTTPException) as ei:
        _login()
    assert ei.value.status_code == 429


def test_the_refusal_says_when_to_come_back():
    auth_module.login_throttle().record_failure("alice", "203.0.113.5")
    auth_module.login_throttle().record_failure("alice", "203.0.113.5")
    with pytest.raises(HTTPException) as ei:
        _login()
    assert ei.value.headers.get("Retry-After")


def test_the_refusal_does_not_say_whether_the_account_exists():
    for name in ("alice", "no-such-user-at-all"):
        auth_module.login_throttle().record_failure(name, "203.0.113.5")
        auth_module.login_throttle().record_failure(name, "203.0.113.5")
        with pytest.raises(HTTPException) as ei:
            _login(username=name)
        assert "exist" not in ei.value.detail.lower()
        assert ei.value.status_code == 429
