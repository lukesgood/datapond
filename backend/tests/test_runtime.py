import importlib


def _fresh():
    import app.runtime as r
    return importlib.reload(r)


def test_production_true(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert _fresh().is_production() is True


def test_dev_false(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert _fresh().is_production() is False


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "Production")
    assert _fresh().is_production() is True
