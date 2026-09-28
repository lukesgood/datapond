"""OAuth resource-server mode: accept access tokens issued by the customer's IdP.

DataPond's own credentials are an HS256 session token and `dp_sk_` keys. An MCP
client that speaks OAuth — the authorization model of MCP 2026-07-28 — could not
connect, and behind an agent gateway every agent was the one service account whose
key the gateway held. A gateway cannot pass a user's token through, but it can
exchange it for one scoped to DataPond that still names the user; this module is
what lets DataPond read that name.

Design: docs/superpowers/specs/2026-09-28-oauth-resource-server-design.md. In short:

  - **Validate, never forward.** RS256/ES256 against the issuer's JWKS, the issuer,
    expiry, and an audience that is this deployment. The token is not passed on to
    anything; model calls keep using DataPond's own gateway key.
  - **Existing principals only.** `(issuer, subject)` must match an active `users`
    row an administrator already has — a person who signed in through SSO, or a
    service account linked to the token's client. The IdP issuing a token does not
    create a DataPond account.
  - **Scopes narrow, and are required.** Permissions are the role ∩ the token's
    `datapond:` scopes. A token with none is refused with insufficient_scope rather
    than given the whole role.
"""
import os
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Set, Tuple

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import JOSEError

ALLOWED_ALGS = ("RS256", "ES256")
_LEEWAY_SECONDS = 60
_CACHE_TTL = 3600.0
# A forced refetch (an unknown kid) waits this long after the last fetch. A kid is
# free to forge, and without a floor every forged token cost a round trip to the IdP.
_REFETCH_COOLDOWN = 60.0

# Scopes named in a 401 challenge: what an agent needs to use the data tools at all.
_CHALLENGE_PERMISSIONS = ("knowledge:read", "ai:generate")


class InvalidToken(Exception):
    """Not a token this deployment accepts. Always answered with 401."""


class InsufficientScope(Exception):
    """A valid token for a known principal that carries no DataPond scope."""


@dataclass(frozen=True)
class Config:
    issuer: str
    audiences: Tuple[str, ...]
    client_ids: Tuple[str, ...]
    subject_claim: str
    scope_prefix: str
    base_url: str


def _csv(name: str) -> Tuple[str, ...]:
    return tuple(v.strip() for v in (os.getenv(name) or "").split(",") if v.strip())


def base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")


def enabled() -> bool:
    on = (os.getenv("OAUTH_RS_ENABLED") or "").lower() in ("1", "true", "yes")
    return on and bool((os.getenv("OAUTH_RS_ISSUER") or "").strip())


def config() -> Config:
    base = base_url()
    audiences = _csv("OAUTH_RS_AUDIENCES") or tuple(a for a in (base, f"{base}/api/mcp") if base)
    return Config(
        issuer=(os.getenv("OAUTH_RS_ISSUER") or "").strip().rstrip("/"),
        audiences=audiences,
        client_ids=_csv("OAUTH_RS_CLIENT_IDS"),
        subject_claim=(os.getenv("OAUTH_RS_SUBJECT_CLAIM") or "sub").strip(),
        scope_prefix=(os.getenv("OAUTH_RS_SCOPE_PREFIX") or "datapond:").strip(),
        base_url=base,
    )


def looks_external(token: str) -> bool:
    """A JWT signed with an IdP's key. DataPond's own session token is HS256, so the
    header alone routes a token — neither kind is ever tried against the other's key."""
    if not token or token.count(".") != 2:
        return False
    try:
        return jose_jwt.get_unverified_header(token).get("alg") in ALLOWED_ALGS
    except JOSEError:
        return False


# ── keys ──────────────────────────────────────────────────────────────────────

_discovery_cache: dict = {}
_jwks_cache: dict = {}


async def _discover(cfg: Config) -> dict:
    hit = _discovery_cache.get(cfg.issuer)
    if hit and time.monotonic() - hit[1] < _CACHE_TTL:
        return hit[0]
    doc = None
    # OIDC discovery first, then RFC 8414: Okta, Entra and Cognito all serve the former.
    for path in ("/.well-known/openid-configuration", "/.well-known/oauth-authorization-server"):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(cfg.issuer + path)
            if r.status_code == 200:
                doc = r.json()
                break
        except httpx.HTTPError:
            continue
    if not doc or not doc.get("jwks_uri"):
        raise InvalidToken("the issuer's metadata could not be read")
    _discovery_cache[cfg.issuer] = (doc, time.monotonic())
    return doc


async def fetch_jwks(cfg: Config, force: bool = False) -> dict:
    hit = _jwks_cache.get(cfg.issuer)
    if hit:
        age = time.monotonic() - hit[1]
        if age < (_REFETCH_COOLDOWN if force else _CACHE_TTL):
            return hit[0]
    doc = await _discover(cfg)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(doc["jwks_uri"])
        r.raise_for_status()
        jwks = r.json()
    except (httpx.HTTPError, ValueError):
        raise InvalidToken("the issuer's signing keys could not be read")
    _jwks_cache[cfg.issuer] = (jwks, time.monotonic())
    return jwks


# ── validation ────────────────────────────────────────────────────────────────

def _client_of(claims: dict) -> Optional[str]:
    # Cognito client_id, Entra v2 azp / v1 appid, Okta cid.
    for name in ("client_id", "azp", "appid", "cid"):
        if isinstance(claims.get(name), str) and claims[name]:
            return claims[name]
    return None


def is_client_token(claims: dict, subject) -> bool:
    """Whether a token was issued to a client acting for itself (client credentials)
    rather than to a person through that client.

    Only such a token may reach the service account linked to its client. A person's
    token from the same client names the person; if the person is not a DataPond user
    they are nobody here, not the agent — otherwise anyone in the tenant who can get a
    token from the agent's client would act, and be audited, as the agent.
    """
    client = _client_of(claims)
    if not client:
        return False
    if not isinstance(subject, str) or not subject:
        return True
    if subject in (client, f"{client}@clients"):       # Okta, Cognito; Auth0
        return True
    if claims.get("idtyp") == "app":                   # Entra, optional claim
        return True
    # Entra app-only token: its subject is the service principal's object id, and it
    # carries application roles instead of delegated `scp`.
    return claims.get("oid") == subject and "scp" not in claims


def verify(token: str, jwks: dict, cfg: Config) -> dict:
    """The token's claims, or InvalidToken. Pure: keys and config are arguments."""
    try:
        header = jose_jwt.get_unverified_header(token)
    except JOSEError:
        raise InvalidToken("malformed token")
    if header.get("alg") not in ALLOWED_ALGS:
        raise InvalidToken("unsupported algorithm")
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise InvalidToken("unknown kid")
    try:
        claims = jose_jwt.decode(
            token, key, algorithms=list(ALLOWED_ALGS),
            options={"verify_aud": False, "verify_iss": False, "require_exp": True,
                     "leeway": _LEEWAY_SECONDS})
    except JOSEError as e:
        raise InvalidToken(str(e))
    # Compared without a trailing slash on either side: the configured issuer is held
    # without one (it is joined to discovery paths and stored on linked accounts), and
    # some IdPs — Auth0 — put one in `iss`. An exact match refused every such token.
    iss = claims.get("iss")
    if not isinstance(iss, str) or iss.rstrip("/") != cfg.issuer:
        raise InvalidToken("token issuer is not the configured issuer")

    if claims.get("token_use") == "id":
        raise InvalidToken("an ID token is not an access token")
    aud = claims.get("aud")
    auds = [aud] if isinstance(aud, str) else list(aud or [])
    if auds:
        # RFC 8707 / MCP: the token must have been issued for this resource.
        if not set(auds) & set(cfg.audiences):
            raise InvalidToken("token audience is not this deployment")
    elif _client_of(claims) not in cfg.client_ids:
        # Cognito access tokens usually carry no aud; the client is what can be checked.
        raise InvalidToken("token has no audience and its client is not accepted")
    return claims


# ── scopes and principals ─────────────────────────────────────────────────────

def token_scopes(claims: dict) -> Set[str]:
    raw = claims.get("scp", claims.get("scope"))
    if isinstance(raw, str):
        return set(raw.split())
    if isinstance(raw, list):
        return {s for s in raw if isinstance(s, str)}
    return set()


def granted_permissions(scopes: Iterable[str], *, role: str, service: bool,
                        prefix: str) -> Set[str]:
    from app.permissions import permissions_for
    from app.service_accounts import NEVER_FOR_SERVICE_ACCOUNTS
    asked = {s[len(prefix):] for s in scopes if s.startswith(prefix)}
    granted = asked & set(permissions_for(role))
    if service:
        granted -= set(NEVER_FOR_SERVICE_ACCOUNTS)
    return granted


def scope_for(permission: str, cfg: Optional[Config] = None) -> str:
    return (cfg or config()).scope_prefix + permission


def scopes_supported(cfg: Optional[Config] = None) -> list:
    from app.permissions import ASSIGNABLE_ROLES, permissions_for
    every = set().union(*(permissions_for(r) for r in ASSIGNABLE_ROLES))
    return sorted(scope_for(p, cfg) for p in every)


async def _get_pool():
    from app.api.auth import _get_pool as pool
    return await pool()


_COLUMNS = "id, username, role, is_active, pii_mode, auth_method"
_BY_SUBJECT = f"""SELECT {_COLUMNS} FROM users
    WHERE external_id = $1 AND (external_provider = $2 OR external_provider IS NULL)
      AND auth_method IN ('oidc', 'service') AND is_active"""
_BY_CLIENT = f"""SELECT {_COLUMNS} FROM users
    WHERE external_id = $1 AND (external_provider = $2 OR external_provider IS NULL)
      AND auth_method = 'service' AND is_active"""


async def resolve(token: str) -> Optional[dict]:
    """The DataPond principal behind an external access token, or None.

    Raises InsufficientScope for a valid token of a known principal that grants
    nothing: the client should be told which scope to ask for, not that it is unknown.
    """
    cfg = config()
    try:
        try:
            claims = verify(token, await fetch_jwks(cfg), cfg)
        except InvalidToken as e:
            if "unknown kid" not in str(e):
                raise
            claims = verify(token, await fetch_jwks(cfg, force=True), cfg)
    except InvalidToken:
        return None

    subject = claims.get(cfg.subject_claim)
    client = _client_of(claims)
    row = None
    try:
        pool = await _get_pool()
        async with pool.acquire(timeout=2) as conn:
            if isinstance(subject, str) and subject:
                row = await conn.fetchrow(_BY_SUBJECT, subject, cfg.issuer)
            if row is None and client and is_client_token(claims, subject):
                # A client-credentials token names the agent, not a person. It may
                # reach only a service account an administrator linked to that client.
                row = await conn.fetchrow(_BY_CLIENT, client, cfg.issuer)
    except Exception:
        return None
    if row is None:
        return None

    service = str(row["auth_method"]) == "service"
    permissions = granted_permissions(token_scopes(claims), role=row["role"],
                                      service=service, prefix=cfg.scope_prefix)
    if not permissions:
        raise InsufficientScope()
    user = {
        "id": str(row["id"]),
        "username": row["username"],
        "role": row["role"],
        "auth_method": "service" if service else "oidc",
        "permissions": sorted(permissions),
        "oauth": True,
    }
    if row["pii_mode"]:
        user["pii_mode"] = row["pii_mode"]
    return user


# ── what a client is told ─────────────────────────────────────────────────────

def metadata_url(path: str) -> str:
    suffix = "/api/mcp" if path.startswith("/api/mcp") else ""
    return f"{base_url()}/.well-known/oauth-protected-resource{suffix}"


def challenge(path: str, *, error: Optional[str] = None,
              scopes: Optional[Iterable[str]] = None) -> str:
    """The WWW-Authenticate value (RFC 6750 / RFC 9728) for a refusal on `path`."""
    cfg = config()
    wanted = " ".join(scopes or (scope_for(p, cfg) for p in _CHALLENGE_PERMISSIONS))
    parts = []
    if error:
        parts.append(f'error="{error}"')
    parts.append(f'scope="{wanted}"')
    parts.append(f'resource_metadata="{metadata_url(path)}"')
    return "Bearer " + ", ".join(parts)


def protected_resource_metadata(resource_path: str = "") -> dict:
    """RFC 9728 document. `resource` must equal the identifier the well-known URL was
    formed from, so the root document names the deployment and the MCP one the endpoint."""
    cfg = config()
    return {
        "resource": cfg.base_url + resource_path,
        "authorization_servers": [cfg.issuer],
        "scopes_supported": scopes_supported(cfg),
        "bearer_methods_supported": ["header"],
        "resource_name": "DataPond",
    }
