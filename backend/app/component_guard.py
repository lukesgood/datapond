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

from app.capabilities import _feat


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
