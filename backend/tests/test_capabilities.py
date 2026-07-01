"""Tests for feature capability flags."""
from app.capabilities import compute_capabilities


def _env(**kw):
    """Build env dict from FEATURE_* kwargs."""
    return {f"FEATURE_{k}": v for k, v in kw.items()}


def test_all_enabled_by_default():
    """All features enabled when no env vars set (backward compat)."""
    caps = compute_capabilities({})
    assert caps["catalog"] is True
    assert caps["query"] is True
    assert caps["streaming"] is True
    assert caps["knowledge"] is True


def test_lean_profile_hides_lakehouse():
    """Lean profile (no Trino/Polaris/Airflow/etc) hides lakehouse features."""
    env = _env(
        TRINO="false",
        POLARIS="false",
        AIRFLOW="false",
        MLFLOW="false",
        RISINGWAVE="false",
        OPENMETADATA="false",
        JUPYTER="false",
    )
    caps = compute_capabilities(env)
    # Hidden by lean profile
    for k in (
        "catalog",
        "connectors",
        "query",
        "dashboards",
        "pipelines",
        "streaming",
        "experiments",
        "notebooks",
        "lineage",
    ):
        assert caps[k] is False, f"{k} should be False"
    # Core always on
    for k in ("knowledge", "ai", "settings", "governance", "storage"):
        assert caps[k] is True, f"{k} should be True"


def test_catalog_on_if_only_polaris():
    """Catalog available if Polaris enabled, even without Trino."""
    caps = compute_capabilities(_env(TRINO="false", POLARIS="true"))
    assert caps["catalog"] is True
