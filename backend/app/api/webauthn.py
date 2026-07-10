"""Passwordless passkey/WebAuthn (community). Library-backed via py_webauthn.
Challenges are single-use in Valkey (mirrors ee/sso state_pop, reimplemented here since
community code cannot import from /ee)."""
import base64
import json
import logging
import os
import secrets
from typing import Optional

logger = logging.getLogger(__name__)
COSE_ALG_ALLOWLIST = [-7, -257]  # ES256, RS256


def _webauthn_cfg() -> dict:
    rp_id = os.getenv("WEBAUTHN_RP_ID", "").strip()
    origin = os.getenv("WEBAUTHN_ORIGIN", "").strip()
    if not origin and rp_id:
        origin = f"https://{rp_id}"
    return {
        "rp_id": rp_id,
        "rp_name": os.getenv("WEBAUTHN_RP_NAME", "DataPond").strip(),
        "origin": origin,
    }


def webauthn_enabled() -> bool:
    cfg = _webauthn_cfg()
    if not cfg["rp_id"] or not cfg["origin"]:
        return False
    # WebAuthn needs a secure context: HTTPS, or localhost for dev.
    return cfg["origin"].startswith("https://") or cfg["rp_id"] == "localhost"


def _redis_client():
    try:
        import redis
        r = redis.Redis(
            host=os.getenv("VALKEY_HOST", "valkey.datapond.svc.cluster.local"),
            port=int(os.getenv("VALKEY_PORT", "6379")),
            socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
        )
        r.ping()
        return r
    except Exception:
        return None


# In-process fallback store for dev/tests when Valkey is absent (single-use still enforced).
_mem_challenges: dict = {}


def _challenge_store(nonce: str, challenge_b64: str, ttl: int = 300) -> None:
    r = _redis_client()
    if r:
        r.setex(f"webauthn:chal:{nonce}", ttl, challenge_b64)
    else:
        _mem_challenges[nonce] = challenge_b64


def _challenge_pop(nonce: str) -> Optional[str]:
    r = _redis_client()
    if r:
        key = f"webauthn:chal:{nonce}"
        val = r.get(key)
        if val is not None:
            r.delete(key)  # single-use
        return val
    return _mem_challenges.pop(nonce, None)


def _new_nonce() -> str:
    return secrets.token_urlsafe(24)
