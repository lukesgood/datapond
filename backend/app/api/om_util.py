"""
Shared OpenMetadata access — URL + auth token.

connectors.py and pipelines.py each had their own identical OM URL constant and
token function (JWT bot-token → cache → base64 basic-auth login). Centralize so the
auth flow / endpoint can't drift between the two (code-review finding #9).
"""
import os
import base64
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OPENMETADATA_URL = os.getenv("OPENMETADATA_URL", "http://openmetadata-server.datapond.svc.cluster.local:8585")
# OM admin creds (env-overridable; password must match the OM instance to log in).
OPENMETADATA_EMAIL = os.getenv("OPENMETADATA_EMAIL", "admin@open-metadata.org")
OPENMETADATA_PASSWORD = os.getenv("OPENMETADATA_PASSWORD", "admin")

_TOKEN_CACHE: Optional[str] = None


async def om_token() -> Optional[str]:
    """OpenMetadata JWT. Preferred: long-lived bot token via OPENMETADATA_JWT_TOKEN
    (ingestion-bot). Fallback: basic-auth /users/login (OM >=1.x needs the password
    Base-64 encoded). Cached in a module var after the first login."""
    global _TOKEN_CACHE
    static = os.getenv("OPENMETADATA_JWT_TOKEN", "").strip()
    if static:
        return static
    if _TOKEN_CACHE:
        return _TOKEN_CACHE
    try:
        pw_b64 = base64.b64encode(OPENMETADATA_PASSWORD.encode()).decode()
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{OPENMETADATA_URL}/api/v1/users/login",
                json={"email": OPENMETADATA_EMAIL, "password": pw_b64},
            )
            if r.status_code == 200:
                _TOKEN_CACHE = r.json().get("accessToken")
                return _TOKEN_CACHE
            logger.warning(f"[om] login failed {r.status_code}: {r.text[:120]}")
    except Exception as e:
        logger.warning(f"[om] login error: {e}")
    return None


def om_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
