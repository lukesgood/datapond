import pytest
from fastapi import HTTPException


def test_guard_raises_503_when_feature_off(monkeypatch):
    from app.component_guard import require_component
    monkeypatch.setenv("FEATURE_JUPYTER", "false")
    guard = require_component("JUPYTER", "Notebooks")
    with pytest.raises(HTTPException) as ei:
        guard()
    assert ei.value.status_code == 503
    assert "Notebooks is not enabled" in ei.value.detail


def test_guard_passes_when_feature_on(monkeypatch):
    from app.component_guard import require_component
    monkeypatch.setenv("FEATURE_RISINGWAVE", "true")
    require_component("RISINGWAVE", "Streaming")()  # no raise


def test_guard_passes_when_unset_default_true(monkeypatch):
    from app.component_guard import require_component
    monkeypatch.delenv("FEATURE_MLFLOW", raising=False)
    require_component("MLFLOW", "Experiments")()  # default True → no raise


def test_guard_respects_default_false(monkeypatch):
    from app.component_guard import require_component
    monkeypatch.delenv("FEATURE_SOMETHING", raising=False)
    with pytest.raises(HTTPException) as ei:
        require_component("SOMETHING", "Thing", default=False)()
    assert ei.value.status_code == 503
