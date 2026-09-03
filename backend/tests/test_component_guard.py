"""The capability predicate, shared by the route guards and the action gate.

It lived in main.py, where the only way to reach it was to import the application.
"""
import pytest
from fastapi import HTTPException

from app.component_guard import capability_on, require_capability


def test_capability_on_reads_the_computed_map(monkeypatch):
    monkeypatch.delenv("FEATURE_TRINO", raising=False)
    monkeypatch.delenv("FEATURE_POLARIS", raising=False)
    monkeypatch.delenv("FEATURE_GLUE", raising=False)
    assert capability_on("catalog") is False

    monkeypatch.setenv("FEATURE_TRINO", "true")
    assert capability_on("catalog") is True


def test_capability_on_is_false_for_a_name_that_does_not_exist():
    """Fail-closed. A typo must not read as 'on'."""
    assert capability_on("no_such_capability") is False


def test_capability_on_is_false_for_a_non_boolean_value(monkeypatch):
    """compute_capabilities also returns strings (query_engine, profile_id). Only an
    exact True counts, so a truthy string can never open a gate."""
    assert capability_on("query_engine") is False


def test_require_capability_raises_503_when_off(monkeypatch):
    monkeypatch.delenv("FEATURE_TRINO", raising=False)
    monkeypatch.delenv("FEATURE_ATHENA", raising=False)
    guard = require_capability("query", "SQL Lab")
    with pytest.raises(HTTPException) as e:
        guard()
    assert e.value.status_code == 503
    assert "SQL Lab" in e.value.detail


def test_require_capability_passes_when_on(monkeypatch):
    monkeypatch.setenv("FEATURE_TRINO", "true")
    assert require_capability("query", "SQL Lab")() is None
