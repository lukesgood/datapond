"""Links to MLflow's own UI follow `mlflow_ui`, which is off unless the chart publishes it."""
from app.capabilities import compute_capabilities


def test_experiments_without_a_published_ui():
    caps = compute_capabilities({"FEATURE_MLFLOW": "true", "FEATURE_MLFLOW_UI": "false"})
    assert caps["experiments"] is True and caps["mlflow_ui"] is False


def test_published_ui():
    assert compute_capabilities({"FEATURE_MLFLOW": "true", "FEATURE_MLFLOW_UI": "true"})["mlflow_ui"] is True


def test_unset_is_off():
    assert compute_capabilities({})["mlflow_ui"] is False
