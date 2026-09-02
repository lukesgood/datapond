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


# The add-ons SUPPORT.md disclaims, as FEATURE_* names. Tied to that document by
# tests/test_capability_support_tiers.py — the list lives there for people, here for
# the derivation, and neither may drift.
UNSUPPORTED_BACKENDS = (
    "TRINO", "AIRFLOW", "SPARK", "POLARIS", "RISINGWAVE", "OPENMETADATA",
    "JUPYTER", "MLFLOW",
)

# Which FEATURE_* flags can turn each component-gated capability on. One source for the
# runtime answer and for the support tier a capability carries.
CAPABILITY_BACKENDS = {
    "connectors":  ("TRINO", "POLARIS", "GLUE"),
    "catalog":     ("TRINO", "POLARIS", "GLUE"),
    "query":       ("TRINO", "ATHENA"),
    "dashboards":  ("TRINO", "ATHENA"),
    "pipelines":   ("AIRFLOW",),
    "streaming":   ("RISINGWAVE",),
    "experiments": ("MLFLOW",),
    "notebooks":   ("JUPYTER",),
    "lineage":     ("OPENMETADATA",),
}

# A capability whose own headline feature cannot complete in this release. Stronger
# than `experimental`, and tied to the code that makes it true:
# tests/test_capability_support_tiers.py fails when the deploy stops being refused.
PREVIEW_CAPABILITIES = ("pipelines",)


def support_tiers() -> dict:
    """{capability: tier} for everything this release does not fully support.

    Absent means supported, so a capability added later cannot inherit a tier by
    accident. Derived, never hand-written: experimental is "every backend that can
    enable this is one SUPPORT.md disclaims".
    """
    tiers = {
        capability: "experimental"
        for capability, backends in CAPABILITY_BACKENDS.items()
        if all(backend in UNSUPPORTED_BACKENDS for backend in backends)
    }
    tiers.update({capability: "preview" for capability in PREVIEW_CAPABILITIES})
    return tiers


def compute_capabilities(env: Mapping) -> dict:
    """Feature→enabled map from FEATURE_<COMPONENT> env (fail-closed by default).

    Pure function: no imports beyond typing, no side effects, no I/O.
    Enables instant, infallible `/api/capabilities` endpoint.
    """
    trino = _feat(env, "TRINO")
    polaris = _feat(env, "POLARIS")
    glue = _feat(env, "GLUE", default=False)  # new opt-in AWS backend — off unless set
    athena = _feat(env, "ATHENA", default=False)  # AWS-native query engine (slice 2)

    def _gated(name: str) -> bool:
        return any(_feat(env, flag) for flag in CAPABILITY_BACKENDS[name])

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
        # Which non-supported capabilities carry a tier, and which one. Absent means
        # supported. Derived from CAPABILITY_BACKENDS/UNSUPPORTED_BACKENDS/
        # PREVIEW_CAPABILITIES above, not decided here.
        "support": support_tiers(),
        # Component-gated
        "connectors": _gated("connectors"),  # Ingestion → Iceberg via Trino/Polaris or Glue
        "catalog": _gated("catalog"),
        "query": _gated("query"),
        "dashboards": _gated("dashboards"),  # BI mini-charts run through /queries/execute
        "pipelines": _gated("pipelines"),  # Transforms
        "streaming": _gated("streaming"),
        "experiments": _gated("experiments"),
        "notebooks": _gated("notebooks"),
        "lineage": _gated("lineage"),  # governance sub-tab (nav stays core)
        "rls": _feat(env, "RLS", default=False),
        # Phase 0 ontology slice: concept store + opt-in query expansion. Fail-closed.
        "ontology": _feat(env, "ONTOLOGY", default=False),
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
