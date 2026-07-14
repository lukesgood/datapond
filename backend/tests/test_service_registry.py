from app.service_registry import service_registry


def _names(env):
    return [s["name"] for s in service_registry(env)]


def test_aws_foundation_profile():
    """Glue/Athena profile: core pods + AWS-managed, no self-hosted engines."""
    env = {"ICEBERG_CATALOG_BACKEND": "glue",
           "FEATURE_TRINO": "false", "FEATURE_POLARIS": "false"}
    names = _names(env)
    assert {"backend", "frontend", "litellm", "valkey"} <= set(names)
    assert {"Amazon S3", "Amazon Aurora", "Amazon Bedrock", "AWS Glue", "Amazon Athena"} <= set(names)
    assert "trino" not in names and "polaris" not in names and "seaweedfs" not in names
    # managed services carry kind=managed
    managed = [s for s in service_registry(env) if s["kind"] == "managed"]
    assert len(managed) == 5


def test_onprem_full_profile():
    """Default (polaris) profile: self-hosted engines + postgres/seaweedfs, no AWS-managed."""
    env = {}  # nothing set → default polaris, FEATURE_* default true
    names = _names(env)
    assert {"backend", "frontend", "trino", "polaris", "postgres", "seaweedfs"} <= set(names)
    assert not any(s["kind"] == "managed" for s in service_registry(env))


def test_feature_gating_hides_disabled_engine():
    env = {"ICEBERG_CATALOG_BACKEND": "glue", "FEATURE_TRINO": "false"}
    assert "trino" not in _names(env)
