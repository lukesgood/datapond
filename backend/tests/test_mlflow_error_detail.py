"""MLflow's error text can carry its tracking database's SQL; the console must not."""
from app.api.mlflow_integration import _mlflow_detail


class _E(Exception):
    error_code = "INVALID_REQUEST"


def test_the_detail_keeps_the_code_and_drops_the_sql():
    d = _mlflow_detail(_E("(psycopg2.errors.InvalidTextRepresentation) ... [SQL: SELECT experiments.experiment_id ...]"))
    assert "INVALID_REQUEST" in d
    assert "SELECT" not in d and "psycopg2" not in d


def test_an_exception_without_a_code_still_reads():
    assert "INTERNAL_ERROR" in _mlflow_detail(RuntimeError("boom"))
