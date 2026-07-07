# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.
"""OIDC Relying Party — authorization-code + PKCE on httpx + python-jose.

Env-configured (LDAP parity), one IdP per deployment. No new dependencies.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Optional

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import JWTError

logger = logging.getLogger(__name__)

ALLOWED_ALGS = ("RS256", "ES256")
STATE_TTL_SEC = 600
DISCOVERY_TTL_SEC = 3600
JWKS_TTL_SEC = 3600
HTTP_TIMEOUT = 10.0


class OIDCError(Exception):
    """Any OIDC protocol/validation failure (caller maps to a reason slug)."""


def oidc_enabled() -> bool:
    return os.getenv("OIDC_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _cfg() -> dict:
    """Read config fresh per call (LDAP-parity env; secret is prod-fail-closed)."""
    from app.runtime import component_secret
    return {
        "issuer":       os.getenv("OIDC_ISSUER", "").strip().rstrip("/"),
        "client_id":    os.getenv("OIDC_CLIENT_ID", "").strip(),
        "client_secret": component_secret("OIDC_CLIENT_SECRET", "", component="oidc"),
        "scopes":       os.getenv("OIDC_SCOPES", "openid profile email").strip(),
        "redirect_url": os.getenv("OIDC_REDIRECT_URL", "").strip(),
        "group_claim":  os.getenv("OIDC_GROUP_CLAIM", "groups").strip(),
        "admin_group":  os.getenv("OIDC_ADMIN_GROUP", "").strip(),
        "default_role": os.getenv("OIDC_DEFAULT_ROLE", "viewer").strip(),
    }


# ── PKCE ───────────────────────────────────────────────────────────────────────

def make_pkce() -> tuple:
    """(code_verifier, S256 code_challenge)."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


# ── State store: Valkey (TTL, single-use) with in-memory fallback ─────────────

_mem_state = {}


def _redis_client():
    """Valkey client or None (tests/dev fallback). Import-local: redis is optional at call time."""
    try:
        import redis
        r = redis.Redis(
            host=os.getenv("VALKEY_HOST", "valkey.datapond.svc.cluster.local"),
            port=int(os.getenv("VALKEY_PORT", "6379")),
            socket_timeout=2, socket_connect_timeout=2, decode_responses=True,
        )
        r.ping()
        return r
    except Exception:
        return None


async def state_put(state: str, payload: dict) -> None:
    r = _redis_client()
    if r is not None:
        await asyncio.to_thread(r.setex, f"oidc:state:{state}", STATE_TTL_SEC, json.dumps(payload))
        return
    _mem_state[state] = (time.time() + STATE_TTL_SEC, payload)


async def state_pop(state: str) -> Optional[dict]:
    r = _redis_client()
    if r is not None:
        def _getdel():
            pipe = r.pipeline()
            pipe.get(f"oidc:state:{state}")
            pipe.delete(f"oidc:state:{state}")
            return pipe.execute()[0]
        raw = await asyncio.to_thread(_getdel)
        return json.loads(raw) if raw else None
    exp_payload = _mem_state.pop(state, None)
    if not exp_payload:
        return None
    exp, payload = exp_payload
    return payload if exp > time.time() else None


# ── Discovery + JWKS (cached) ─────────────────────────────────────────────────

_discovery_cache = {"issuer": None, "doc": None, "ts": 0.0}
_jwks_cache = {"jwks": None, "ts": 0.0}


async def discovery() -> dict:
    cfg = _cfg()
    if not cfg["issuer"]:
        raise OIDCError("OIDC_ISSUER is not configured")
    now = time.time()
    if (_discovery_cache["doc"] is not None
            and _discovery_cache["issuer"] == cfg["issuer"]
            and now - _discovery_cache["ts"] < DISCOVERY_TTL_SEC):
        return _discovery_cache["doc"]
    url = f"{cfg['issuer']}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        doc = resp.json()
    _discovery_cache.update(issuer=cfg["issuer"], doc=doc, ts=now)
    return doc


async def _jwks(force: bool = False) -> dict:
    now = time.time()
    if not force and _jwks_cache["jwks"] is not None and now - _jwks_cache["ts"] < JWKS_TTL_SEC:
        return _jwks_cache["jwks"]
    doc = await discovery()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(doc["jwks_uri"])
        resp.raise_for_status()
        jwks = resp.json()
    _jwks_cache.update(jwks=jwks, ts=now)
    return jwks


# ── Authorize URL / token exchange ─────────────────────────────────────────────

async def build_authorize_url() -> str:
    cfg = _cfg()
    doc = await discovery()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = make_pkce()
    await state_put(state, {"nonce": nonce, "verifier": verifier})
    params = httpx.QueryParams({
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_url"],
        "scope": cfg["scopes"],
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{doc['authorization_endpoint']}?{params}"


async def exchange_code(code: str, verifier: str) -> dict:
    cfg = _cfg()
    doc = await discovery()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_url"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code_verifier": verifier,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(doc["token_endpoint"], data=data)
    if resp.status_code != 200:
        raise OIDCError(f"token exchange failed: HTTP {resp.status_code}")
    return resp.json()


# ── id_token verification ─────────────────────────────────────────────────────

def verify_claims(id_token: str, jwks: dict, *, issuer: str, client_id: str,
                  nonce: str, leeway: int = 60) -> dict:
    """Pure verification against a JWKS dict — the unit-testable core."""
    try:
        header = jose_jwt.get_unverified_header(id_token)
    except JWTError as e:
        raise OIDCError(f"malformed token: {e}")
    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        raise OIDCError(f"disallowed alg: {alg}")
    kid = header.get("kid")
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        raise OIDCError(f"unknown kid: {kid}")
    try:
        claims = jose_jwt.decode(
            id_token, key, algorithms=list(ALLOWED_ALGS),
            audience=client_id, issuer=issuer,
            options={"leeway": leeway},
        )
    except JWTError as e:
        raise OIDCError(f"token validation failed: {e}")
    if claims.get("nonce") != nonce:
        raise OIDCError("nonce mismatch")
    return claims


async def verify_id_token(id_token: str, nonce: str) -> dict:
    """Fetch/caches JWKS (one forced refetch on unknown kid) and verify."""
    cfg = _cfg()
    jwks = await _jwks()
    try:
        return verify_claims(id_token, jwks, issuer=cfg["issuer"],
                             client_id=cfg["client_id"], nonce=nonce)
    except OIDCError as e:
        if "unknown kid" in str(e):
            jwks = await _jwks(force=True)
            return verify_claims(id_token, jwks, issuer=cfg["issuer"],
                                 client_id=cfg["client_id"], nonce=nonce)
        raise
