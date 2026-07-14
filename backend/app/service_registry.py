"""Profile-aware platform-service list — pure, dependency-free (like capabilities.py).

Returns the ACTUAL deployed workloads per profile rather than a fixed legacy stack:
foundation core pods + optional self-hosted engines (FEATURE_* gated) + AWS-managed
services (informational) on the AWS/Glue profile.
"""
from typing import Mapping, List

# External (browser) consoles for services that expose one.
SERVICE_URLS = {
    "mlflow": "/mlflow", "jupyterlab": "/jupyter", "airflow": "/airflow",
    "openmetadata": "/openmetadata", "seaweedfs": "/storage",
}


def _feat(env: Mapping, name: str, default: bool = True) -> bool:
    v = env.get(f"FEATURE_{name}")
    return default if v is None else str(v).strip().lower() in ("1", "true", "yes", "on")


def _aws_profile(env: Mapping) -> bool:
    """AWS-native foundation profile (Glue catalog + Athena + S3/Aurora/Bedrock)."""
    return str(env.get("ICEBERG_CATALOG_BACKEND", "polaris")).strip().lower() == "glue"


def service_registry(env: Mapping) -> List[dict]:
    aws = _aws_profile(env)
    svcs: List[dict] = [
        {"name": "backend",  "app": "backend",  "kind": "pod", "desc": "DataPond API (FastAPI)"},
        {"name": "frontend", "app": "frontend", "kind": "pod", "desc": "Management UI (Next.js)"},
        {"name": "litellm",  "app": "litellm",  "kind": "pod", "desc": "AI model gateway (→ Bedrock)"},
        {"name": "valkey",   "app": "valkey",   "kind": "pod", "desc": "Cache / sessions"},
    ]
    # Optional self-hosted engines — shown only when their component is enabled.
    for name, app, feat in [
        ("trino", "trino", "TRINO"), ("polaris", "polaris", "POLARIS"),
        ("risingwave", "risingwave", "RISINGWAVE"), ("openmetadata", "openmetadata", "OPENMETADATA"),
        ("mlflow", "mlflow", "MLFLOW"), ("jupyterlab", "jupyterlab", "JUPYTER"),
        ("airflow", "airflow", "AIRFLOW"),
    ]:
        if _feat(env, feat, default=not aws):
            svcs.append({"name": name, "app": app, "kind": "pod", "url": SERVICE_URLS.get(name)})
    if aws:
        for name, desc in [
            ("Amazon S3", "Object storage (Iceberg data)"),
            ("Amazon Aurora", "PostgreSQL + pgvector (managed)"),
            ("Amazon Bedrock", "LLM / embeddings (managed)"),
            ("AWS Glue", "Iceberg Data Catalog (serverless)"),
            ("Amazon Athena", "Serverless SQL query engine"),
        ]:
            svcs.append({"name": name, "kind": "managed", "desc": desc})
    else:
        svcs.append({"name": "postgres", "app": "postgres", "kind": "pod", "desc": "PostgreSQL"})
        svcs.append({"name": "seaweedfs", "app": "seaweedfs", "kind": "pod",
                     "url": SERVICE_URLS.get("seaweedfs"), "desc": "S3-compatible object storage"})
    return svcs
