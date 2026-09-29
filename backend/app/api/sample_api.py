"""The REST feed behind the "Sample FX Rates API" source.

The REST connector needs an HTTP endpoint to call, and an install with no egress has
no public one. So this backend serves one, and the sample connector calls it on the
pod's own address.

The route is exempt from the bearer check in main.py, because the connector sends an
API key header rather than a DataPond token — which is the point: it shows the REST
connector's `api_key` auth against a real endpoint. It is not open, though. The key is
derived from this deployment's JWT secret, so it is different on every install and
changes when the secret rotates; re-adding the sample writes the new one into the
connector. What it guards is generated exchange rates — nothing a caller could not
compute from app/sample_sources.py — but an unauthenticated route in a governed
product is a habit worth not starting.
"""
import hashlib
import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from app.sample_sources import fx_payload

router = APIRouter()

FX_RATES_PATH = "/sample-api/fx-rates"


def sample_api_key() -> str:
    from app.api.auth import SECRET_KEY
    digest = hmac.new(SECRET_KEY.encode(), b"datapond-sample-rest-api",
                      hashlib.sha256).hexdigest()
    return f"dp_sample_{digest[:32]}"


def sample_api_base_url() -> str:
    """Where the connector reaches this route: the pod's own listener by default.

    127.0.0.1 rather than the Service name, so a sync never lands on another replica
    running an older image, and never depends on cluster DNS.
    """
    base = os.getenv("SAMPLE_API_BASE_URL", "http://127.0.0.1:8000/api").rstrip("/")
    return base + FX_RATES_PATH


@router.get(FX_RATES_PATH, include_in_schema=False)
async def fx_rates(x_sample_key: str = Header(default="")):
    if not hmac.compare_digest(x_sample_key, sample_api_key()):
        raise HTTPException(status_code=401, detail="Missing or wrong X-Sample-Key.")
    return fx_payload()
