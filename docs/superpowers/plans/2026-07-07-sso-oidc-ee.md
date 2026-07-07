# SSO (OIDC) — First `/ee` Feature (P0-3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OIDC SSO (authorization-code + PKCE) as the first commercially-licensed `/ee` feature: `ee/backend/ee/sso/` module, edition-aware image build, LDAP-parity Helm config, SSO button on the login page.

**Spec:** `docs/superpowers/specs/2026-07-07-sso-oidc-ee-design.md`

**Architecture:** Hand-rolled OIDC RP on existing deps (httpx + python-jose). Community/enterprise split via multi-stage Dockerfile with repo-root build context (`--target community|enterprise`); Apache-side integration is a try-import in main.py. Env config mirrors the LDAP block; JIT provisioning mirrors `_upsert_ldap_user` (anti-shadow guard, no reactivation).

**Tech Stack:** FastAPI, httpx, python-jose, redis-py (Valkey state store), Helm, pytest.

## Global Constraints

- ZERO new Python dependencies — either edition. Only httpx / python-jose / redis (all in requirements.txt).
- All `/ee` source files start with the header comment: `# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.`
- Community image must work with `/app/ee` absent: main.py try-import; SSO endpoints simply don't exist; capabilities `"sso": false`.
- id_token verification: alg allowlist EXACTLY `("RS256", "ES256")`; verify `iss`, `aud`, `exp` (leeway 60s), `nonce`; JWKS cached 1h with ONE forced refetch on unknown `kid`.
- State store: Valkey key `oidc:state:{state}`, TTL 600s, single-use (delete-on-read); in-memory dict fallback when Valkey unreachable.
- JIT provisioning: `ON CONFLICT (username) DO UPDATE ... WHERE users.auth_method = 'oidc'`; NEVER touches `is_active` on update; a `local`/`ldap` username collision → login fails with `reason=account_conflict`. Role from `OIDC_ADMIN_GROUP` ∈ claims[`OIDC_GROUP_CLAIM`] → `admin` else `OIDC_DEFAULT_ROLE` (default `viewer`), written to `users.role` only (LDAP parity — the RLS loader falls back to `users.role`; do NOT write `user_roles`).
- Every flow failure → `logger.warning` + 302 `/login?error=sso_failed&reason=<slug>`; slugs exactly: `state`, `exchange`, `token`, `claims`, `account_conflict`, `provider`. Never a raw 500 mid-flow.
- No schema migration; no license-key check; SAML/userinfo/SLO/multi-IdP out of scope.
- Local pytest baseline (pre-existing failures): run `python3 -m pytest tests/ -q --ignore=tests/test_iceberg_writer.py --ignore=tests/test_pipelines` in backend/ → "4 failed, NN passed"; the 4 failures are not yours. CI py3.11 authoritative.
- Branch: `feat/sso-oidc-ee`; squash-merge PR at the end.

---

### Task 1: OIDC protocol client + tests (TDD)

**Files:**
- Create: `ee/backend/ee/__init__.py`, `ee/backend/ee/sso/__init__.py`, `ee/backend/ee/sso/oidc.py`
- Test: `ee/backend/tests/__init__.py` (empty), `ee/backend/tests/test_oidc.py`

**Interfaces:**
- Produces (Task 2 consumes): `oidc_enabled() -> bool`; `_cfg() -> dict` (keys: issuer, client_id, client_secret, scopes, redirect_url, group_claim, admin_group, default_role); `async build_authorize_url() -> str`; `async state_pop(state: str) -> Optional[dict]` (returns `{"nonce": str, "verifier": str}` or None); `async exchange_code(code: str, verifier: str) -> dict` (token endpoint JSON); `async verify_id_token(id_token: str, nonce: str) -> dict` (claims; raises `OIDCError`); `class OIDCError(Exception)`. Pure testable core: `make_pkce() -> tuple[str, str]`, `verify_claims(id_token, jwks: dict, *, issuer, client_id, nonce, leeway=60) -> dict`.

- [ ] **Step 1: Write the failing tests** — `ee/backend/tests/test_oidc.py`:

```python
"""Unit tests for the /ee OIDC protocol client (pure parts — no network)."""
import base64
import hashlib
import time

import pytest
from jose import jwt as jose_jwt
from jose.backends import RSAKey  # noqa: F401  (cryptography backend present)
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from ee.sso.oidc import OIDCError, make_pkce, verify_claims


# ── local RSA key + JWKS fixtures ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_numbers()

    def b64u(i: int, length: int) -> str:
        return base64.urlsafe_b64encode(i.to_bytes(length, "big")).rstrip(b"=").decode()

    jwks = {"keys": [{
        "kty": "RSA", "use": "sig", "kid": "test-key", "alg": "RS256",
        "n": b64u(pub.n, 256), "e": b64u(pub.e, 3),
    }]}
    return priv_pem, jwks


ISS, AUD, NONCE = "https://idp.example.com", "datapond-client", "nonce-123"


def _token(priv_pem, *, iss=ISS, aud=AUD, nonce=NONCE, exp_delta=3600,
           alg="RS256", kid="test-key", extra=None):
    claims = {"iss": iss, "aud": aud, "sub": "user-1", "nonce": nonce,
              "exp": int(time.time()) + exp_delta, "iat": int(time.time()),
              "preferred_username": "alice", "email": "alice@example.com"}
    claims.update(extra or {})
    return jose_jwt.encode(claims, priv_pem, algorithm=alg, headers={"kid": kid})


def _verify(tok, jwks, **kw):
    args = dict(issuer=ISS, client_id=AUD, nonce=NONCE)
    args.update(kw)
    return verify_claims(tok, jwks, **args)


def test_valid_token_returns_claims(rsa_keypair):
    priv, jwks = rsa_keypair
    claims = _verify(_token(priv), jwks)
    assert claims["sub"] == "user-1"
    assert claims["preferred_username"] == "alice"


def test_expired_token_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, exp_delta=-120), jwks)


def test_wrong_audience_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, aud="other-client"), jwks)


def test_wrong_issuer_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, iss="https://evil.example.com"), jwks)


def test_wrong_nonce_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, nonce="stolen"), jwks)


def test_hs256_alg_confusion_rejected(rsa_keypair):
    _, jwks = rsa_keypair
    forged = jose_jwt.encode(
        {"iss": ISS, "aud": AUD, "sub": "user-1", "nonce": NONCE,
         "exp": int(time.time()) + 3600},
        "shared-secret", algorithm="HS256", headers={"kid": "test-key"})
    with pytest.raises(OIDCError):
        _verify(forged, jwks)


def test_unknown_kid_rejected(rsa_keypair):
    priv, jwks = rsa_keypair
    with pytest.raises(OIDCError):
        _verify(_token(priv, kid="rotated-away"), jwks)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = make_pkce()
    expect = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expect
    assert 43 <= len(verifier) <= 128


def test_state_store_single_use(monkeypatch):
    import asyncio
    from ee.sso import oidc
    monkeypatch.setattr(oidc, "_redis_client", lambda: None)  # force memory fallback
    asyncio.get_event_loop().run_until_complete(
        oidc.state_put("s1", {"nonce": "n", "verifier": "v"}))
    loop = asyncio.get_event_loop()
    assert loop.run_until_complete(oidc.state_pop("s1")) == {"nonce": "n", "verifier": "v"}
    assert loop.run_until_complete(oidc.state_pop("s1")) is None      # single-use
    assert loop.run_until_complete(oidc.state_pop("nope")) is None    # unknown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/luke/datapond/backend && PYTHONPATH=../ee/backend python3 -m pytest ../ee/backend/tests/test_oidc.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'ee'`

- [ ] **Step 3: Implement** — create the package files.

`ee/backend/ee/__init__.py` and `ee/backend/ee/sso/__init__.py`:
```python
# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.
```

`ee/backend/ee/sso/oidc.py`:
```python
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
    r = await asyncio.to_thread(_redis_client) if not callable(getattr(_redis_client, "__wrapped__", None)) else _redis_client()
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
```

NOTE for the implementer: in `state_put` above, the first line containing `getattr(_redis_client, "__wrapped__", ...)` is a mistake if transcribed — the function body must be exactly:

```python
async def state_put(state: str, payload: dict) -> None:
    r = _redis_client()
    if r is not None:
        await asyncio.to_thread(r.setex, f"oidc:state:{state}", STATE_TTL_SEC, json.dumps(payload))
        return
    _mem_state[state] = (time.time() + STATE_TTL_SEC, payload)
```
(single `_redis_client()` call; the tests monkeypatch `_redis_client` to force the memory path.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/luke/datapond/backend && PYTHONPATH=../ee/backend python3 -m pytest ../ee/backend/tests/test_oidc.py -v`
Expected: 10/10 PASS. (`app.runtime` imports resolve because CWD is backend/.)

- [ ] **Step 5: Commit**

```bash
git add ee/backend
git commit -m "feat(ee/sso): OIDC protocol client — PKCE, JWKS verify, single-use state store"
```

---

### Task 2: SSO router + JIT provisioning + tests

**Files:**
- Create: `ee/backend/ee/sso/router.py`
- Test: append to `ee/backend/tests/test_oidc.py` (new test classes) — or create `ee/backend/tests/test_router.py` (preferred, one file per unit)

**Interfaces:**
- Consumes: everything from Task 1; `app.api.auth._create_token(user_id, username, role)` and `app.api.auth._get_pool()` (existing, backend/app/api/auth.py).
- Produces: `ee.sso.router.router` (FastAPI `APIRouter` with `GET /auth/oidc/login`, `GET /auth/oidc/callback`) — Task 3's main.py hook imports exactly `from ee.sso.router import router as sso_router`.

- [ ] **Step 1: Write the failing tests** — `ee/backend/tests/test_router.py`:

```python
# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.
"""Router-level tests: role mapping + JIT upsert conflict semantics (mocked pool)."""
import pytest

from ee.sso.router import _map_role, _upsert_oidc_user


def test_map_role_admin_when_group_present():
    claims = {"groups": ["datapond-admins", "everyone"]}
    assert _map_role(claims, group_claim="groups",
                     admin_group="datapond-admins", default_role="viewer") == "admin"


def test_map_role_default_when_group_absent():
    claims = {"groups": ["everyone"]}
    assert _map_role(claims, group_claim="groups",
                     admin_group="datapond-admins", default_role="viewer") == "viewer"


def test_map_role_default_when_claim_missing_or_not_list():
    assert _map_role({}, group_claim="groups", admin_group="g", default_role="viewer") == "viewer"
    assert _map_role({"groups": "not-a-list"}, group_claim="groups",
                     admin_group="g", default_role="viewer") == "viewer"


def test_map_role_no_admin_group_configured():
    assert _map_role({"groups": ["anything"]}, group_claim="groups",
                     admin_group="", default_role="data_engineer") == "data_engineer"


class _FakeConn:
    def __init__(self, row_after):
        self.row_after = row_after
        self.executed = []
    async def execute(self, sql, *args):
        self.executed.append((sql, args))
    async def fetchrow(self, sql, *args):
        return self.row_after
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self, conn): self._conn = conn
    def acquire(self): return self._conn


@pytest.mark.asyncio
async def test_upsert_returns_row_for_oidc_user(monkeypatch):
    from ee.sso import router as r
    row = {"id": "u1", "username": "alice", "role": "viewer",
           "auth_method": "oidc", "is_active": True}
    conn = _FakeConn(row)
    async def fake_pool(): return _FakePool(conn)
    monkeypatch.setattr(r, "_pool", fake_pool)
    got = await _upsert_oidc_user({"email": "a@x", "username": "alice",
                                   "display_name": "Alice", "role": "viewer",
                                   "external_id": "sub-1"})
    assert got["username"] == "alice"
    assert "WHERE users.auth_method = 'oidc'" in conn.executed[0][0]


@pytest.mark.asyncio
async def test_upsert_conflict_with_local_account_returns_none(monkeypatch):
    """Upsert WHERE-clause skips a local row; SELECT comes back auth_method='local' → None."""
    from ee.sso import router as r
    row = {"id": "u1", "username": "admin", "role": "admin",
           "auth_method": "local", "is_active": True}
    async def fake_pool(): return _FakePool(_FakeConn(row))
    monkeypatch.setattr(r, "_pool", fake_pool)
    got = await _upsert_oidc_user({"email": "a@x", "username": "admin",
                                   "display_name": "A", "role": "viewer",
                                   "external_id": "sub-1"})
    assert got is None
```

Add `pytest-asyncio` note: backend/requirements-dev.txt — check whether `pytest-asyncio` is present (`grep -i asyncio backend/requirements-dev.txt`). If absent, mark the two async tests with a small self-contained runner instead:

```python
def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)
```
and call `_run(_upsert_oidc_user(...))` in plain `def` tests (drop the `@pytest.mark.asyncio` decorators). Use whichever matches the repo's existing dev deps — do not add a new dependency.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/luke/datapond/backend && PYTHONPATH=../ee/backend python3 -m pytest ../ee/backend/tests/test_router.py -v`
Expected: ImportError (`ee.sso.router` missing).

- [ ] **Step 3: Implement** — `ee/backend/ee/sso/router.py`:

```python
# DataPond Enterprise — Commercial License (see ee/LICENSE). Not covered by the root Apache-2.0 grant.
"""OIDC SSO endpoints: /api/auth/oidc/login (302 to IdP) + /api/auth/oidc/callback."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from starlette.responses import RedirectResponse

from ee.sso.oidc import (
    OIDCError, build_authorize_url, exchange_code, oidc_enabled,
    state_pop, verify_id_token, _cfg,
)

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE_MAX_AGE = 24 * 3600


async def _pool():
    from app.api.auth import _get_pool
    return await _get_pool()


def _map_role(claims: dict, *, group_claim: str, admin_group: str, default_role: str) -> str:
    groups = claims.get(group_claim)
    if admin_group and isinstance(groups, list) and admin_group in groups:
        return "admin"
    return default_role


async def _upsert_oidc_user(u: dict) -> Optional[dict]:
    """JIT-provision an OIDC user (LDAP-parity semantics).

    Conflict update is scoped WHERE auth_method='oidc' and never touches is_active,
    so (a) a local/ldap account with the same username is never modified — detected
    afterwards and treated as a conflict; (b) a deactivated OIDC user stays deactivated."""
    pool = await _pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (id, email, username, display_name, role, auth_method,
                               external_id, is_active, require_password_change)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, 'oidc', $5, true, false)
            ON CONFLICT (username) DO UPDATE
              SET display_name = EXCLUDED.display_name,
                  email        = EXCLUDED.email,
                  role         = EXCLUDED.role,
                  external_id  = EXCLUDED.external_id
              WHERE users.auth_method = 'oidc'
            """,
            u["email"], u["username"], u["display_name"], u["role"], u["external_id"],
        )
        row = await conn.fetchrow(
            """SELECT id, username, role, auth_method, is_active
               FROM users WHERE username=$1""",
            u["username"],
        )
    if row is None or row["auth_method"] != "oidc":
        return None
    return dict(row)


def _fail(reason: str, detail: str = "") -> RedirectResponse:
    logger.warning("[oidc] sso login failed: reason=%s %s", reason, detail)
    return RedirectResponse(f"/login?error=sso_failed&reason={reason}", status_code=302)


@router.get("/auth/oidc/login")
async def oidc_login():
    if not oidc_enabled():
        raise HTTPException(status_code=404, detail="SSO not enabled")
    try:
        url = await build_authorize_url()
    except (OIDCError, Exception) as e:
        return _fail("provider", str(e))
    return RedirectResponse(url, status_code=302)


@router.get("/auth/oidc/callback")
async def oidc_callback(code: str = "", state: str = "", error: str = ""):
    if not oidc_enabled():
        raise HTTPException(status_code=404, detail="SSO not enabled")
    if error or not code or not state:
        return _fail("provider", f"idp error={error!r}")

    st = await state_pop(state)
    if not st:
        return _fail("state")

    try:
        tokens = await exchange_code(code, st["verifier"])
    except (OIDCError, Exception) as e:
        return _fail("exchange", str(e))
    id_token = tokens.get("id_token")
    if not id_token:
        return _fail("exchange", "no id_token in response")

    try:
        claims = await verify_id_token(id_token, st["nonce"])
    except OIDCError as e:
        return _fail("token", str(e))

    username = (claims.get("preferred_username") or claims.get("email") or "").strip()
    if not username:
        return _fail("claims", "no preferred_username/email claim")
    cfg = _cfg()
    role = _map_role(claims, group_claim=cfg["group_claim"],
                     admin_group=cfg["admin_group"], default_role=cfg["default_role"])

    row = await _upsert_oidc_user({
        "email": claims.get("email") or f"{username}@sso.local",
        "username": username,
        "display_name": claims.get("name") or username,
        "role": role,
        "external_id": claims.get("sub"),
    })
    if row is None or not row["is_active"]:
        return _fail("account_conflict", f"username={username}")

    from app.api.auth import _create_token
    token = _create_token(str(row["id"]), row["username"], row["role"])
    resp = RedirectResponse("/login?sso=1", status_code=302)
    resp.set_cookie("datapond_token", token, max_age=COOKIE_MAX_AGE,
                    samesite="lax", path="/")
    return resp
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd /Users/luke/datapond/backend && PYTHONPATH=../ee/backend python3 -m pytest ../ee/backend/tests/ -v`
Expected: all PASS (Task 1's 10 + these 6).

- [ ] **Step 5: Commit**

```bash
git add ee/backend
git commit -m "feat(ee/sso): OIDC login/callback endpoints + JIT provisioning (LDAP-parity guards)"
```

---

### Task 3: Community-side integration (main.py hook, exemptions, capabilities, CI tests)

**Files:**
- Modify: `backend/main.py` (AUTH_EXEMPT ~line 50; app setup after middleware; capabilities endpoint ~line 261)
- Modify: `.github/workflows/ci.yml` (backend-tests "Run unit tests" step)
- Test: `backend/tests/test_ee_hook.py`

**Interfaces:**
- Consumes: `ee.sso.router.router` (Task 2).
- Produces: `EE_SSO: bool` module flag in main.py; `/api/capabilities` response gains `"sso"`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_ee_hook.py`:

```python
"""The /api/capabilities sso flag logic (pure — mirrors main.py's expression)."""
from app.capabilities import compute_capabilities


def _sso_flag(ee_loaded: bool, env: dict) -> bool:
    # Same expression main.py uses for the "sso" capability
    return ee_loaded and str(env.get("OIDC_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")


def test_sso_false_without_ee():
    assert _sso_flag(False, {"OIDC_ENABLED": "true"}) is False


def test_sso_false_without_oidc_enabled():
    assert _sso_flag(True, {}) is False


def test_sso_true_when_both():
    assert _sso_flag(True, {"OIDC_ENABLED": "true"}) is True


def test_base_capabilities_unaffected():
    caps = compute_capabilities({})
    assert "sso" not in caps  # sso is layered on in main.py, not in the pure fn
```

- [ ] **Step 2: main.py edits** (three spots):

(a) After the `app.add_middleware(AuthMiddleware)` line, add:

```python
# ── Enterprise (/ee) features — present only in enterprise-edition images ──────
# Community builds lack /app/ee entirely; the import fails and SSO stays off.
try:
    from ee.sso.router import router as sso_router
    app.include_router(sso_router, prefix="/api")
    EE_SSO = True
except ImportError:
    EE_SSO = False
```

(Check how existing routers are included first — `grep -n "include_router" backend/main.py | head -3` — and use the SAME prefix convention: if auth_router is included with `prefix="/api"`, mirror it; if the router paths already carry `/api`, adjust so the final paths are exactly `/api/auth/oidc/login` and `/api/auth/oidc/callback`.)

(b) `AUTH_EXEMPT` — add three entries with a comment:

```python
    "/api/auth/oidc/login",     # SSO redirect entry (pre-auth by definition)
    "/api/auth/oidc/callback",  # IdP redirects back here without our JWT
    "/api/capabilities",        # login page needs the sso flag pre-auth (feature flags only)
```

(c) capabilities endpoint (~line 261) — change the return to layer the sso flag:

```python
@app.get("/api/capabilities")
async def get_capabilities():
    caps = compute_capabilities(os.environ)
    caps["sso"] = EE_SSO and str(os.environ.get("OIDC_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")
    return caps
```
(keep any existing docstring/comments on the endpoint.)

- [ ] **Step 3: ci.yml — run ee tests in the backend job.** In the `backend-tests` job's "Run unit tests" step, replace the run line:

```yaml
        run: |
          python -m pytest tests -q
          PYTHONPATH=../ee/backend python -m pytest ../ee/backend/tests -q
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/luke/datapond/backend
python3 -m pytest tests/test_ee_hook.py -v                       # 4 PASS
PYTHONPATH=../ee/backend python3 -m pytest ../ee/backend/tests -q  # all PASS
python3 -m pytest tests/ -q --ignore=tests/test_iceberg_writer.py --ignore=tests/test_pipelines  # baseline + new
python3 -m py_compile main.py
python3 -c "import yaml; yaml.safe_load(open('../.github/workflows/ci.yml'))" && echo CI-YAML-OK
```

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_ee_hook.py .github/workflows/ci.yml
git commit -m "feat(sso): ee try-import hook, auth exemptions, sso capability flag, ee tests in CI"
```

---

### Task 4: Edition-aware image build

**Files:**
- Modify: `backend/Dockerfile` (multi-stage; context becomes repo root)
- Create: `.dockerignore` (repo root)
- Modify: `scripts/build.sh` (backend build context + EDITION), `scripts/bundle-airgap.sh` (same pattern — find its backend docker build invocation: `grep -n "docker build\|backend" scripts/bundle-airgap.sh | head`)
- Modify: `docs/AWS_MVP_RUNBOOK.md` (tar-sync note), `ee/README.md` (SSO now present)

- [ ] **Step 1: Rewrite `backend/Dockerfile`** as multi-stage (build context = REPO ROOT):

```dockerfile
# Backend Dockerfile for DataPond — build from REPO ROOT:
#   docker build -f backend/Dockerfile --target enterprise .
#   docker build -f backend/Dockerfile --target community .
# enterprise = community + /ee (commercially licensed, see ee/LICENSE).
FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# ── Community edition: Apache-2.0 code only ────────────────────────────────────
FROM base AS community
RUN useradd -m -u 1000 datapond && chown -R datapond:datapond /app
USER datapond
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Enterprise edition: + /ee (DataPond Commercial License) ────────────────────
FROM base AS enterprise
COPY ee/backend/ee /app/ee
RUN useradd -m -u 1000 datapond && chown -R datapond:datapond /app
USER datapond
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create root `.dockerignore`**:

```
.git
.github
.superpowers
.claude
docs
node_modules
frontend/node_modules
frontend/.next
**/__pycache__
**/*.pyc
terraform
helm
scripts
*.md
!ee/**/*.md
```

- [ ] **Step 3: `scripts/build.sh`** — change the backend case (and the backend line inside `all`):

```bash
  backend)
    # EDITION: enterprise (default, includes /ee) | community (Apache-2.0 only)
    log "Building datapond/backend:${TAG} (${EDITION:-enterprise})..."
    docker build -t "datapond/backend:${TAG}" -f backend/Dockerfile --target "${EDITION:-enterprise}" .
    log "Importing into k3s containerd..."
    docker save "datapond/backend:${TAG}" | \
      k3s ctr --address /run/k3s/containerd/containerd.sock images import -
    ok "backend image ready"
    restart_deployment backend
    ;;
```

(the generic `build_and_import backend backend/` call no longer fits the backend — inline as above or extend `build_and_import` with optional dockerfile/target args; keep frontend/jupyter calls unchanged. Match the script's existing style. The `all` case must build backend the same new way.)

- [ ] **Step 4: `bundle-airgap.sh`** — apply the same `-f backend/Dockerfile --target "${EDITION:-enterprise}" .` change to its backend build (run from repo root; verify with `bash -n scripts/bundle-airgap.sh`).

- [ ] **Step 5: Docs.** `docs/AWS_MVP_RUNBOOK.md` — extend the existing tar-sync caveat section with: `ee/ must be included in the tar-sync set — the enterprise image build COPYs ee/backend/ee; a sync that omits ee/ silently produces a community image.` `ee/README.md` — change "This directory currently contains no code; its first planned tenant is the SSO (SAML/OIDC) implementation (roadmap item P0-3)." to "First tenant: SSO (OIDC) — `backend/ee/sso/` (endpoints `/api/auth/oidc/*`). SAML is a planned follow-up."

- [ ] **Step 6: Verify + commit**

```bash
bash -n scripts/build.sh && bash -n scripts/bundle-airgap.sh && echo SH-OK
# docker build verification is deploy-time (no docker guaranteed here); if docker IS
# available locally, smoke both targets:
docker build -q -f backend/Dockerfile --target community . && docker build -q -f backend/Dockerfile --target enterprise . || echo "docker unavailable — CI/deploy-time verification"
git add backend/Dockerfile .dockerignore scripts/build.sh scripts/bundle-airgap.sh docs/AWS_MVP_RUNBOOK.md ee/README.md
git commit -m "build: edition-aware backend image (community|enterprise) from repo-root context"
```

---

### Task 5: Helm wiring (values, backend env block, secret)

**Files:**
- Modify: `helm/datapond/values.yaml` (auth block, after the ldap sub-block ~line 664)
- Modify: `helm/datapond/templates/backend-deployment.yaml` (directly after the LDAP block's `{{- end }}` ~line 219)
- Modify: `helm/datapond/templates/secrets.yaml` (next to the LDAP_BIND_PASSWORD with-block ~line 196)
- Modify: `.github/workflows/ci.yml` (helm-lint job assertions)

- [ ] **Step 1: values.yaml** — add under `auth:` after the `ldap:` block:

```yaml
  # OIDC SSO (Enterprise, /ee) — off by default. Requires an enterprise-edition
  # backend image; community images do not contain the endpoints.
  oidc:
    enabled: false
    issuer: ""            # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    clientId: ""
    clientSecret: ""      # → datapond-secrets/OIDC_CLIENT_SECRET (from your IdP)
    scopes: "openid profile email"
    redirectUrl: ""       # empty ⇒ {externalScheme}://{domain}/api/auth/oidc/callback
    groupClaim: "groups"
    adminGroup: ""        # IdP group whose members get role=admin
    defaultRole: "viewer"
```

- [ ] **Step 2: backend-deployment.yaml** — after the LDAP block's `{{- end }}`:

```yaml
        {{- if (((.Values.auth).oidc).enabled) }}
        # OIDC SSO (Enterprise /ee feature)
        - name: OIDC_ENABLED
          value: "true"
        - name: OIDC_ISSUER
          value: "{{ .Values.auth.oidc.issuer }}"
        - name: OIDC_CLIENT_ID
          value: "{{ .Values.auth.oidc.clientId }}"
        - name: OIDC_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: OIDC_CLIENT_SECRET
        - name: OIDC_SCOPES
          value: {{ .Values.auth.oidc.scopes | default "openid profile email" | quote }}
        - name: OIDC_REDIRECT_URL
          value: "{{ .Values.auth.oidc.redirectUrl | default (printf "%s://%s/api/auth/oidc/callback" (.Values.global.externalScheme | default "http") (.Values.ingress.domain | default .Values.global.domain)) }}"
        - name: OIDC_GROUP_CLAIM
          value: "{{ .Values.auth.oidc.groupClaim | default "groups" }}"
        - name: OIDC_ADMIN_GROUP
          value: "{{ .Values.auth.oidc.adminGroup | default "" }}"
        - name: OIDC_DEFAULT_ROLE
          value: "{{ .Values.auth.oidc.defaultRole | default "viewer" }}"
        {{- end }}
```

- [ ] **Step 3: secrets.yaml** — after the LDAP_BIND_PASSWORD with-block:

```yaml
  {{- with (((.Values.auth).oidc).clientSecret) }}
  # OIDC client secret (Enterprise SSO) — provided by your IdP, no generation
  OIDC_CLIENT_SECRET: {{ . | quote }}
  {{- end }}
```

- [ ] **Step 4: CI helm assertion** — in the helm-lint job after `OK: component credentials wired`:

```bash
          echo "== OIDC env wiring (enterprise SSO) =="
          r=$(helm template datapond helm/datapond \
            --set auth.oidc.enabled=true --set auth.oidc.issuer=https://idp.example \
            --set auth.oidc.clientId=cid --set auth.oidc.clientSecret=csecret)
          echo "$r" | grep -q 'name: OIDC_CLIENT_SECRET' || { echo "FAIL OIDC secretKeyRef"; exit 1; }
          echo "$r" | grep -q 'OIDC_CLIENT_SECRET: "csecret"' || { echo "FAIL OIDC secret entry"; exit 1; }
          echo "$r" | grep -q 'name: OIDC_ISSUER' || { echo "FAIL OIDC env"; exit 1; }
          helm template datapond helm/datapond | grep -q 'OIDC_' && { echo "FAIL OIDC leaks into default render"; exit 1; }
          echo "OK: OIDC wired"
```

- [ ] **Step 5: Verify + commit**

```bash
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('helm/datapond/values*.yaml')]" && echo VALUES-OK
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo CI-YAML-OK
git add helm/datapond .github/workflows/ci.yml
git commit -m "feat(helm): auth.oidc block — gated env + secret (LDAP parity)"
```

---

### Task 6: Frontend — SSO button + callback completion

**Files:**
- Modify: `frontend/app/login/page.tsx` (useEffect ~line 49; below the submit Button ~line 279)
- Modify: `frontend/proxy.ts` (PUBLIC_PATHS line 4)

- [ ] **Step 1: proxy.ts** — extend PUBLIC_PATHS:

```ts
const PUBLIC_PATHS = ["/login", "/api/auth/login", "/api/auth/oidc", "/api/capabilities"]
```
(startsWith matching makes `/api/auth/oidc` cover both login and callback.)

- [ ] **Step 2: login page state + effects.** Add state near the other useState lines:

```tsx
  const [ssoEnabled, setSsoEnabled] = useState(false)
```

At the TOP of the existing `useEffect` (before the `isAuthenticated()` block), add SSO return-leg + error handling:

```tsx
    // SSO return leg: /login?sso=1 arrives with the datapond_token cookie set by
    // the backend callback. Promote it into localStorage (saveAuth) and enter.
    const params = new URLSearchParams(window.location.search)
    if (params.get("sso") === "1") {
      const m = document.cookie.match(/(?:^|;\s*)datapond_token=([^;]+)/)
      const ssoToken = m?.[1]
      if (ssoToken) {
        fetch("/api/auth/me", { headers: { Authorization: `Bearer ${ssoToken}` } })
          .then(r => { if (!r.ok) throw new Error("sso session invalid"); return r.json() })
          .then(me => { saveAuth(ssoToken, me); window.location.replace("/dashboard") })
          .catch(() => { clearAuth(); setError("SSO 로그인에 실패했습니다. 다시 시도해 주세요.") })
        return
      }
    }
    if (params.get("error") === "sso_failed") {
      const reason = params.get("reason") ?? "unknown"
      setError(`SSO 로그인 실패 (${reason}). 관리자에게 문의하거나 로컬 계정으로 로그인하세요.`)
    }
    // Feature flag: show the SSO button only when the backend (enterprise image +
    // OIDC_ENABLED) reports it. Fail-quiet: button simply doesn't render.
    fetch("/api/capabilities").then(r => r.ok ? r.json() : null)
      .then(caps => setSsoEnabled(Boolean(caps?.sso))).catch(() => {})
```

(`saveAuth` needs importing if not already: check the file's existing import from `@/lib/auth` and extend it.)

- [ ] **Step 3: SSO button** — directly below the submit `</Button>` (~line 279):

```tsx
            {ssoEnabled && (
              <Button type="button" variant="outline" className="w-full h-10 font-medium mt-2"
                      onClick={() => { window.location.href = "/api/auth/oidc/login" }}>
                Sign in with SSO
              </Button>
            )}
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/luke/datapond/frontend && npx tsc --noEmit 2>&1 | tail -3   # type check (matches CI)
git add frontend/app/login/page.tsx frontend/proxy.ts
git commit -m "feat(frontend): SSO login button (capability-gated) + OIDC return-leg handling"
```
(If `npx tsc` is unavailable locally, note it — CI's frontend-check is authoritative.)

---

### Task 7: PR + CI green + final review

- [ ] **Step 1:** `git push -u origin feat/sso-oidc-ee`; `gh pr create` (token via `git credential fill`). PR body: OIDC RP on existing deps, /ee first tenant, edition-aware image build (community/enterprise targets, root context), LDAP-parity helm config, capability-gated SSO button, JIT provisioning with anti-shadow guard; deviations: role written to `users.role` only (LDAP parity; spec's user_roles line superseded); out-of-scope list from spec §7.
- [ ] **Step 2:** CI green (backend incl. ee tests, frontend, helm incl. OIDC assertions, license gate — note: ee files are first-party commercial code, NOT third-party; the license gate scans deps only and is unaffected).
- [ ] **Step 3:** Final whole-branch review (controller dispatches, most capable model), fix loop, merge decision to the user.

---

## Self-Review

**Spec coverage:** §2 layout/build → Tasks 1 (package) + 4 (Dockerfile/build.sh/.dockerignore/docs); §3 flow → Tasks 1-2 (all six reason slugs present in router; state single-use; alg allowlist; JWKS refetch-on-kid); §4 helm → Task 5 (incl. redirectUrl default derivation); §5 frontend → Task 6 + AUTH_EXEMPT/PUBLIC_PATHS in Tasks 3/6; §6 testing → Tasks 1-3 test files + CI edits; §7 out-of-scope honored.

**Deviation from spec (intentional, stated):** roles go to `users.role` only, not `user_roles` — matches the LDAP precedent the spec elsewhere mandates; the RLS loader's fallback covers it. Recorded in Global Constraints and the PR body.

**Placeholder scan:** all code complete; the one flagged transcription hazard (state_put stray line) is explicitly corrected inline in Task 1 Step 3. pytest-asyncio contingency gives both concrete alternatives.

**Type consistency:** `state_pop → {"nonce","verifier"}` consumed as `st["verifier"]`/`st["nonce"]` (Task 2); `_create_token(user_id, username, role)` matches auth.py's actual signature; `from ee.sso.router import router as sso_router` identical in Task 2 Produces and Task 3 hook; capabilities `"sso"` expression identical in main.py edit and test_ee_hook.py.
