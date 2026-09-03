"""Fail-fast guard for disabled components.

Foundation profile turns the OSS engines off (Jupyter / RisingWave / MLflow /
Airflow). Their routers are still mounted, so a direct call would try to reach a
service that isn't there and surface a raw 500 (connection error, or a
fail-closed secret guard). This dependency returns a clean, honest 503 instead —
and uses the SAME _feat/default logic as /api/capabilities, so the API guard and
the UI's capability gate always agree.
"""
import os

from fastapi import HTTPException

from app.capabilities import _feat, compute_capabilities


def require_component(feature: str, label: str, default: bool = True):
    """FastAPI dependency factory. Raises 503 when FEATURE_<feature> is off.

    Apply at include_router time (dependencies=[Depends(require_component(...))])
    to guard every endpoint of a component's router at once.
    """
    def _guard() -> None:
        if not _feat(os.environ, feature, default):
            raise HTTPException(
                status_code=503,
                detail=f"{label} is not enabled on this deployment profile.",
            )
    return _guard


def capability_on(cap_key: str) -> bool:
    """Whether `cap_key` is enabled, as /api/capabilities computes it.

    Exactly `True` counts. compute_capabilities also returns strings — query_engine,
    profile_id — and a truthy string must never open a gate. An unknown key is False,
    so a typo hides a feature rather than exposing one (design rule 3).
    """
    return compute_capabilities(os.environ).get(cap_key) is True


def require_capability(cap_key: str, label: str):
    """FastAPI dependency: 503 unless `cap_key` is on.

    Unlike require_component (a single FEATURE_* flag), catalog / query / connectors
    are OR-composed capabilities (e.g. ``trino or polaris or glue``). Gating on the
    computed boolean keeps this server-side guard in exact agreement with the
    /api/capabilities the UI gates on.
    """
    def _guard() -> None:
        if not capability_on(cap_key):
            raise HTTPException(
                status_code=503,
                detail=f"{label} is not enabled on this deployment profile.",
            )
    return _guard
