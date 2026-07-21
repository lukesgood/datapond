"""Profile-aware platform service list.

Capability/configuration identity is separate from health. This pure registry lists
only workloads explicitly enabled by Helm and external adapters explicitly configured
through non-secret environment hints.
"""
from typing import List, Mapping


SERVICE_URLS = {
    "mlflow": "/mlflow",
    "jupyterlab": "/jupyter",
    "airflow": "/airflow",
    "openmetadata": "/openmetadata",
    "minio": "/storage",
}


def _feat(env: Mapping, name: str, default: bool = True) -> bool:
    value = env.get(f"FEATURE_{name}")
    return default if value is None else str(value).strip().lower() in ("1", "true", "yes", "on")


def _text(env: Mapping, name: str, default: str = "") -> str:
    return str(env.get(name, default)).strip().lower()


def service_registry(env: Mapping) -> List[dict]:
    profile_id = _text(env, "DATAPOND_PROFILE_ID", "legacy")
    catalog_backend = _text(env, "ICEBERG_CATALOG_BACKEND", "polaris")
    legacy_aws = catalog_backend == "glue" or "aws" in profile_id
    services: List[dict] = [
        {"name": "backend", "app": "backend", "kind": "pod", "desc": "DataPond API (FastAPI)"},
        {"name": "frontend", "app": "frontend", "kind": "pod", "desc": "Management UI (Next.js)"},
    ]

    if _feat(env, "LITELLM"):
        services.append({"name": "litellm", "app": "litellm", "kind": "pod", "desc": "Portable AI model gateway"})
    if _feat(env, "VALKEY"):
        services.append({"name": "valkey", "app": "valkey", "kind": "pod", "desc": "Cache / sessions"})

    # Optional self-hosted engines appear only when their component flag is true.
    for name, app, feature, description in [
        ("trino", "trino", "TRINO", "Distributed SQL query engine"),
        ("polaris", "polaris", "POLARIS", "Apache Iceberg REST catalog"),
        ("risingwave", "risingwave", "RISINGWAVE", "Streaming SQL / CDC add-on"),
        ("openmetadata", "openmetadata", "OPENMETADATA", "External catalog and lineage add-on"),
        ("mlflow", "mlflow", "MLFLOW", "Experiment and model tracking add-on"),
        ("jupyterlab", "jupyterlab", "JUPYTER", "Notebook and DuckDB exploration add-on"),
        ("airflow", "airflow", "AIRFLOW", "Workflow orchestration add-on"),
    ]:
        if _feat(env, feature, default=not legacy_aws):
            services.append({
                "name": name,
                "app": app,
                "kind": "pod",
                "url": SERVICE_URLS.get(name),
                "desc": description,
            })

    if _feat(env, "SPARK", default=not legacy_aws):
        services.append({
            "name": "spark",
            "app": "spark",
            "kind": "pod",
            "desc": "Distributed batch compute add-on",
        })
    if _feat(env, "OLLAMA", default=False):
        services.append({
            "name": "ollama",
            "app": "ollama",
            "kind": "pod",
            "desc": "Local model and embedding runtime",
        })

    vector_store = _text(env, "VECTOR_STORE", "aurora-pgvector" if legacy_aws else "postgres-pgvector")
    if vector_store == "aurora-pgvector":
        services.append({"name": "Amazon Aurora", "kind": "managed", "desc": "PostgreSQL + pgvector adapter"})
    elif vector_store == "external-postgres-pgvector":
        services.append({"name": "External PostgreSQL", "kind": "managed", "desc": "PostgreSQL + pgvector adapter"})
    elif _feat(env, "POSTGRES", default=not legacy_aws):
        services.append({"name": "postgres", "app": "postgres", "kind": "pod", "desc": "PostgreSQL + pgvector"})

    storage_provider = _text(env, "STORAGE_PROVIDER", "s3" if legacy_aws else "")
    endpoint = str(env.get("S3_ENDPOINT", "")).strip()
    if storage_provider == "s3" and not endpoint:
        services.append({"name": "Amazon S3", "kind": "managed", "desc": "Native object-store adapter"})
    elif _feat(env, "MINIO", default=not legacy_aws):
        services.append({
            "name": "minio",
            "app": "minio",
            "kind": "pod",
            "url": SERVICE_URLS["minio"],
            "desc": "S3-compatible object storage",
        })

    if _text(env, "MODEL_PROVIDER", "bedrock" if legacy_aws else "") == "bedrock":
        services.append({"name": "Amazon Bedrock", "kind": "managed", "desc": "Embedding and generation provider"})
    if _feat(env, "GLUE", default=legacy_aws):
        services.append({"name": "AWS Glue", "kind": "managed", "desc": "Iceberg catalog adapter"})
    if _feat(env, "ATHENA", default=legacy_aws):
        services.append({"name": "Amazon Athena", "kind": "managed", "desc": "Serverless SQL query adapter"})

    return services
