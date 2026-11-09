from app.service_registry import service_registry


def _names(env):
    return [s["name"] for s in service_registry(env)]


def test_aws_reference_profile():
    """Glue catalog + in-cluster Trino (2.4): core pods, Trino, AWS-managed adapters;
    no Polaris, no object-store pod, and no "Amazon Athena" entry any more."""
    env = {"ICEBERG_CATALOG_BACKEND": "glue",
           "FEATURE_TRINO": "true", "FEATURE_POLARIS": "false"}
    names = _names(env)
    assert {"backend", "frontend", "litellm", "valkey", "trino"} <= set(names)
    assert {"Amazon S3", "Amazon Aurora", "Amazon Bedrock", "AWS Glue"} <= set(names)
    assert "Amazon Athena" not in names
    assert "polaris" not in names and "seaweedfs" not in names
    # managed services carry kind=managed
    managed = [s for s in service_registry(env) if s["kind"] == "managed"]
    assert len(managed) == 4


def test_onprem_full_profile():
    """Default (polaris) profile: self-hosted engines + postgres/MinIO, no AWS-managed."""
    env = {}  # nothing set → legacy full OSS defaults
    names = _names(env)
    assert {"backend", "frontend", "trino", "polaris", "postgres", "minio", "spark"} <= set(names)
    assert "ollama" not in names  # base profile keeps the local model runtime off
    assert not any(s["kind"] == "managed" for s in service_registry(env))


def test_sovereign_profile_lists_enabled_spark_and_ollama():
    env = {
        "DATAPOND_PROFILE_ID": "sovereign-oss-extended",
        "FEATURE_SPARK": "true",
        "FEATURE_OLLAMA": "true",
        "MODEL_PROVIDER": "ollama",
    }
    names = set(_names(env))
    assert {"spark", "ollama"} <= names


def test_portable_core_aws_lists_only_configured_adapters():
    env = {
        "DATAPOND_PROFILE_ID": "portable-core-aws",
        "STORAGE_PROVIDER": "s3",
        "VECTOR_STORE": "postgres-pgvector",
        "MODEL_PROVIDER": "bedrock",
        "FEATURE_POSTGRES": "true",
        "FEATURE_MINIO": "false",
        "FEATURE_GLUE": "false",
        "FEATURE_TRINO": "false",
        "FEATURE_POLARIS": "false",
    }
    names = set(_names(env))
    assert {"postgres", "Amazon S3", "Amazon Bedrock"} <= names
    assert "AWS Glue" not in names
    assert "Amazon Athena" not in names
    assert "Amazon Aurora" not in names
    assert "minio" not in names


def test_feature_gating_hides_disabled_engine():
    env = {"ICEBERG_CATALOG_BACKEND": "glue", "FEATURE_TRINO": "false"}
    assert "trino" not in _names(env)


def test_generic_external_postgres_is_not_reported_as_aurora():
    names = set(_names({
        "DATAPOND_PROFILE_ID": "aws-hybrid-extended",
        "VECTOR_STORE": "external-postgres-pgvector",
        "FEATURE_POSTGRES": "false",
    }))
    assert "External PostgreSQL" in names
    assert "Amazon Aurora" not in names
