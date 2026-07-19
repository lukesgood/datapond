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


def test_glue_enables_connectors_and_catalog_but_not_query():
    """FEATURE_GLUE (AWS-native) re-enables ingestion+catalog, but not SQL query (Athena = later slice)."""
    caps = compute_capabilities(_env(TRINO="false", POLARIS="false", GLUE="true"))
    assert caps["connectors"] is True
    assert caps["catalog"] is True
    assert caps["query"] is False
    assert caps["dashboards"] is False


def test_glue_off_by_default():
    """Glue is opt-in: absent FEATURE_GLUE leaves the lake backends off."""
    caps = compute_capabilities(_env(TRINO="false", POLARIS="false"))
    assert caps["connectors"] is False and caps["catalog"] is False


def test_athena_enables_query_and_dashboards():
    """FEATURE_ATHENA (AWS-native query) re-enables SQL + dashboards."""
    caps = compute_capabilities(_env(TRINO="false", POLARIS="false", GLUE="true", ATHENA="true"))
    assert caps["query"] is True and caps["dashboards"] is True
    assert caps["catalog"] is True


def test_athena_off_keeps_query_off():
    """Slice-1-only (glue catalog, no athena): catalog on, query off."""
    caps = compute_capabilities(_env(TRINO="false", POLARIS="false", GLUE="true"))
    assert caps["query"] is False and caps["catalog"] is True


def test_profile_and_adapter_metadata_is_additive():
    """Deployment identity is exposed without changing legacy capability keys."""
    caps = compute_capabilities({
        "DATAPOND_PROFILE_ID": "aws-single-node",
        "DATAPOND_PROFILE_LABEL": "AWS Single-Node Reference",
        "DATAPOND_PROFILE_DESCRIPTION": "Portable Core with managed AWS adapters.",
        "DATAPOND_PROFILE_MATURITY": "reference",
        "DATAPOND_PROFILE_TOPOLOGY": "ec2-k3s",
        "DATAPOND_NAMESPACE": "datapond-prod",
        "STORAGE_PROVIDER": "s3",
        "ICEBERG_CATALOG_BACKEND": "glue",
        "QUERY_ENGINE": "athena",
        "VECTOR_STORE": "aurora-pgvector",
        "MODEL_GATEWAY": "litellm",
        "FEATURE_GLUE": "true",
        "FEATURE_ATHENA": "true",
        "FEATURE_TRINO": "false",
        "FEATURE_POLARIS": "false",
        "FEATURE_RLS": "true",
    })
    assert caps["knowledge"] is True
    assert caps["profile_id"] == "aws-single-node"
    assert caps["profile_label"] == "AWS Single-Node Reference"
    assert caps["profile_maturity"] == "reference"
    assert caps["profile_topology"] == "ec2-k3s"
    assert caps["deployment_namespace"] == "datapond-prod"
    assert caps["rls"] is True
    assert caps["storage_provider"] == "s3"
    assert caps["catalog_backend"] == "glue"
    assert caps["query_engine"] == "athena"
    assert caps["vector_store"] == "aurora-pgvector"
    assert caps["model_gateway"] == "litellm"
