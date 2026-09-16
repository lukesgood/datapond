"""The PII guardrail mode can be tightened per request, never loosened.

It was one global env var (POSITIONING_FIT_AUDIT §2.4: "모드는 전역 env 하나… 호출자·
컬렉션별 정책 없음"), so a collection holding resident registration numbers and one
holding public FAQ text were treated identically. A scope narrows it for the request;
the deployment default is the floor.
"""
import pytest

from app.guardrails import pii_ko


@pytest.fixture(autouse=True)
def default_mask(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")


def test_without_a_scope_the_deployment_default_applies():
    assert pii_ko.get_mode() == "mask"


def test_a_scope_can_tighten():
    with pii_ko.scope("block"):
        assert pii_ko.get_mode() == "block"
    assert pii_ko.get_mode() == "mask"


def test_a_scope_cannot_loosen():
    """The point of the rule: a collection or caller set to `off` under a deployment
    that masks does not get raw data."""
    with pii_ko.scope("off"):
        assert pii_ko.get_mode() == "mask"


def test_off_is_reachable_only_when_the_deployment_allows_it(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "off")
    assert pii_ko.get_mode() == "off"
    with pii_ko.scope("block"):
        assert pii_ko.get_mode() == "block"


def test_unknown_and_missing_values_are_ignored_not_treated_as_off():
    assert pii_ko.strictest(None, "", "sometimes") is None
    with pii_ko.scope(None, "typo"):
        assert pii_ko.get_mode() == "mask"


def test_strictest_orders_the_vocabulary():
    assert pii_ko.strictest("off", "mask") == "mask"
    assert pii_ko.strictest("mask", "block") == "block"
    assert pii_ko.strictest("off", "block", "mask") == "block"


def test_nesting_only_tightens():
    with pii_ko.scope("block"):
        with pii_ko.scope("off"):
            assert pii_ko.get_mode() == "block"
        assert pii_ko.get_mode() == "block"


def test_the_scope_is_restored_even_when_the_body_raises():
    with pytest.raises(RuntimeError):
        with pii_ko.scope("block"):
            raise RuntimeError("boom")
    assert pii_ko.get_mode() == "mask"


def test_apply_follows_the_scope():
    rrn = "901231-1234567"
    with pii_ko.scope("block"):
        text, findings, blocked = pii_ko.apply(f"id {rrn}")
    assert blocked is True and text == f"id {rrn}" and findings
