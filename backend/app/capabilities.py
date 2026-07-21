"""Feature capability flags for UI gating — pure, dependency-free."""
from typing import Mapping


def _feat(env: Mapping, name: str, default: bool = False) -> bool:
    """Parse FEATURE_<name> from env; default False (fail-closed) if not set.

    Fail-closed is design rule 3 (docs/ARCHITECTURE.md): an optional capability
    stays off until its FEATURE_* flag is explicitly true. All deployed profiles
    render these flags via templates/backend-deployment.yaml, so this default only
    governs environments where a flag was never set at all.
    """
    v = env.get(f"FEATURE_{name}")
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def compute_capabilities(env: Mapping) -> dict:
    """Feature→enabled map from FEATURE_<COMPONENT> env (fail-closed by default).

    Pure function: no imports beyond typing, no side effects, no I/O.
    Enables instant, infallible `/api/capabilities` endpoint.
    """
    trino = _feat(env, "TRINO")
    polaris = _feat(env, "POLARIS")
    glue = _feat(env, "GLUE", default=False)  # new opt-in AWS backend — off unless set
    athena = _feat(env, "ATHENA", default=False)  # AWS-native query engine (slice 2)
    lake = trino or polaris or glue
    # Report only active adapters. Helm may retain a backend default while its
    # component flag is disabled; exposing that default would mislabel the profile.
    configured_query_engine = str(env.get("QUERY_ENGINE", "trino")).strip().lower()
    query_engine = configured_query_engine if (trino or athena) else "none"
    query_catalog = "AwsDataCatalog" if query_engine == "athena" else ("iceberg" if query_engine == "trino" else "")
    catalog_backend = "glue" if glue else ("polaris" if polaris else "none")
    return {
        # Core — always available
        "knowledge": True,
        "ai": True,
        "settings": True,
        "governance": True,
        "storage": True,
        "services": True,
        "system": True,
        "dashboard": True,
        "docs": True,
        "help": True,
        # Component-gated
        "connectors": lake,  # Ingestion → Iceberg via Trino/Polaris or Glue
        "catalog": lake,
        "query": trino or athena,
        "dashboards": trino or athena,  # BI mini-charts run through /queries/execute
        "pipelines": _feat(env, "AIRFLOW"),  # Transforms
        "streaming": _feat(env, "RISINGWAVE"),
        "experiments": _feat(env, "MLFLOW"),
        "notebooks": _feat(env, "JUPYTER"),
        "lineage": _feat(env, "OPENMETADATA"),  # governance sub-tab (nav stays core)
        "rls": _feat(env, "RLS", default=False),
        # Non-boolean UI hints (safe extras — nav gating ignores these):
        "query_engine": query_engine,      # "athena" | "trino"
        "query_catalog": query_catalog,    # catalog prefix for fully-qualified names
        "catalog_backend": catalog_backend,
        "storage_provider": str(env.get("STORAGE_PROVIDER", "s3")).strip().lower(),
        "vector_store": str(env.get("VECTOR_STORE", "postgres-pgvector")).strip().lower(),
        "model_gateway": str(env.get("MODEL_GATEWAY", "litellm")).strip().lower(),
        # Deployment identity is additive metadata. Feature flags above remain
        # authoritative, so custom values cannot enable a page by changing a label.
        "profile_id": str(env.get("DATAPOND_PROFILE_ID", "custom")).strip(),
        "profile_label": str(env.get("DATAPOND_PROFILE_LABEL", "Custom deployment")).strip(),
        "profile_description": str(env.get("DATAPOND_PROFILE_DESCRIPTION", "")).strip(),
        "profile_maturity": str(env.get("DATAPOND_PROFILE_MATURITY", "custom")).strip(),
        "profile_topology": str(env.get("DATAPOND_PROFILE_TOPOLOGY", "kubernetes")).strip(),
        "deployment_namespace": str(env.get("DATAPOND_NAMESPACE", "datapond")).strip(),
    }
