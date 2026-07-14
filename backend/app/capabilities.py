"""Feature capability flags for UI gating — pure, dependency-free."""
from typing import Mapping


def _feat(env: Mapping, name: str, default: bool = True) -> bool:
    """Parse FEATURE_<name> from env; default True if not set."""
    v = env.get(f"FEATURE_{name}")
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def compute_capabilities(env: Mapping) -> dict:
    """Feature→enabled map from FEATURE_<COMPONENT> env (default enabled).

    Pure function: no imports beyond typing, no side effects, no I/O.
    Enables instant, infallible `/api/capabilities` endpoint.
    """
    trino = _feat(env, "TRINO")
    polaris = _feat(env, "POLARIS")
    glue = _feat(env, "GLUE", default=False)  # new opt-in AWS backend — off unless set
    lake = trino or polaris or glue
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
        "query": trino,
        "dashboards": trino,  # BI mini-charts run Trino queries
        "pipelines": _feat(env, "AIRFLOW"),  # Transforms
        "streaming": _feat(env, "RISINGWAVE"),
        "experiments": _feat(env, "MLFLOW"),
        "notebooks": _feat(env, "JUPYTER"),
        "lineage": _feat(env, "OPENMETADATA"),  # governance sub-tab (nav stays core)
    }
