import logging
import pytest
from app import runtime
from app.runtime import component_secret


@pytest.fixture(autouse=True)
def _reset_warned():
    runtime._warned_secrets.clear()
    yield
    runtime._warned_secrets.clear()


def test_set_value_wins_everywhere(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MY_SECRET", " s3cret ")
    assert component_secret("MY_SECRET", "dev") == "s3cret"


def test_prod_missing_raises(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MY_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="MY_SECRET is required in production"):
        component_secret("MY_SECRET", "dev")


def test_prod_empty_string_raises(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MY_SECRET", "   ")
    with pytest.raises(RuntimeError):
        component_secret("MY_SECRET", "dev", component="airflow")


def test_dev_returns_default_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("MY_SECRET", raising=False)
    with caplog.at_level(logging.WARNING):
        assert component_secret("MY_SECRET", "dev-default") == "dev-default"
    assert "MY_SECRET" in caplog.text


def test_dev_warns_only_once(monkeypatch, caplog):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("MY_SECRET", raising=False)
    with caplog.at_level(logging.WARNING):
        component_secret("MY_SECRET", "d")
        component_secret("MY_SECRET", "d")
    assert caplog.text.count("MY_SECRET") == 1
