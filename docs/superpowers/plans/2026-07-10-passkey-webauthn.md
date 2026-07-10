# Passkey / WebAuthn (Passwordless) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement passwordless-primary passkey/WebAuthn login for DataPond in the Apache community core — a `py_webauthn` backend router + a `webauthn_credentials` table + an `@simplewebauthn/browser` frontend, HTTPS-gated via capabilities.

**Spec:** `docs/superpowers/specs/2026-07-10-passkey-webauthn-design.md`

**Architecture:** A community FastAPI router `backend/app/api/webauthn.py` (mounted alongside the base auth router in `main.py`, NOT via the `/ee` try-import) exposes register/authenticate begin+complete + credential management. Credentials live in a new `webauthn_credentials` table applied by an idempotent startup migration (mirroring `ensure_rls_schema`). Challenges are single-use in Valkey (mirroring OIDC `state_pop`). A successful passkey auth issues the same JWT as password login (`auth._create_token`). The frontend adds a passkey login button + a settings "add passkey" flow, both gated on a new `webauthn` capability flag.

**Tech Stack:** Python (FastAPI, py_webauthn ≥2.0, redis), Next.js/React (@simplewebauthn/browser), PostgreSQL, Valkey.

## Global Constraints

- **Community, NOT /ee**: `backend/app/api/webauthn.py` mounts via `app.include_router(webauthn_router, prefix="/api")` next to the base auth router — do NOT touch the `/ee` try-import.
- **Reuse auth primitives** verbatim: `from app.api.auth import _create_token, require_user, get_current_user, _get_pool`. A passkey login returns the SAME `{access_token, token_type, user}` shape as `POST /api/auth/login`.
- **Library-backed** (no hand-rolled crypto): py_webauthn for all verification. New deps: backend `webauthn` (BSD-3, pulls cbor2/cryptography), frontend `@simplewebauthn/browser` (MIT) — both must pass the P0-2 CI `license-gate` (allowlist).
- **Migration path**: new tables come through an always-run idempotent migration (`CREATE TABLE IF NOT EXISTS`), because `auth.sql` is sentinel-guarded and won't re-run on existing DBs. Mirror `app/rls/migrate.py::ensure_rls_schema` wiring in `main.py`.
- **Challenge store**: single-use, Valkey, 5-min TTL, deleted on consume. Mirror `ee/sso/oidc.py::state_pop` but as its OWN community helper in webauthn.py (cannot import from `/ee`).
- **Security invariants**: origin + RP_ID exact match; COSE alg allowlist ES256/RS256; `sign_count` strictly increasing (reject regression; 0/0 allowed); registration `require_user`-gated; `user_handle` = user_id UUID bytes.
- **HTTPS gating**: `webauthn_enabled()` = origin https (or localhost) AND RP_ID set. `/api/capabilities` exposes `webauthn` = that value; frontend renders passkey UI only when true.
- **Local test note**: system `python3` is 3.9 (repo needs 3.11 for some modules); the container image is python:3.11.15-slim. Run new tests in a 3.11 venv with `pip install webauthn`; CI (3.11) is authoritative.

---

### Task 1: Dependencies + `webauthn_credentials` migration + startup wiring

**Files:**
- Modify: `backend/requirements.txt` (add `webauthn`)
- Modify: `frontend/package.json` (add `@simplewebauthn/browser`)
- Create: `backend/app/webauthn_schema.py`
- Modify: `backend/main.py` (call `ensure_webauthn_schema` at startup, after `ensure_rls_schema`)

**Interfaces:**
- Produces: `webauthn_schema.ensure_webauthn_schema(pool)` — creates the table idempotently. `webauthn_credentials` table (cols per spec §3).

- [ ] **Step 1: add deps**. `backend/requirements.txt` — append `webauthn>=2.0.0`. `frontend/package.json` `dependencies` — add `"@simplewebauthn/browser": "^13.0.0"` (keep alphanumeric ordering with neighbors). Do NOT run `npm install`/`pip install` as part of the commit (CI installs); just declare.

- [ ] **Step 2: create `backend/app/webauthn_schema.py`**

```python
"""Idempotent webauthn_credentials migration — applied every startup (auth.sql is
sentinel-guarded and won't re-run on an existing DB). Mirrors app/rls/migrate.py."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key    BYTEA NOT NULL,
    sign_count    BIGINT NOT NULL DEFAULT 0,
    transports    TEXT[],
    aaguid        UUID,
    name          VARCHAR(128),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webauthn_cred_user ON webauthn_credentials(user_id);
"""


async def ensure_webauthn_schema(pool):
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
```

- [ ] **Step 3: wire into `main.py` startup** — after the `ensure_rls_schema` block (around line 169). Add:

```python
    # WebAuthn/passkey credentials table (idempotent — every startup). best-effort.
    try:
        from app.api.connectors import get_db_pool
        from app.webauthn_schema import ensure_webauthn_schema
        await ensure_webauthn_schema(await get_db_pool())
        logger.info("[startup] webauthn schema ready")
    except Exception as e:
        logger.warning(f"[startup] webauthn schema skipped: {e}")
```

- [ ] **Step 4: Verify + commit**

```bash
cd backend && python3 -m py_compile app/webauthn_schema.py main.py && echo "compiles"
python3 -c "import ast; ast.parse(open('app/webauthn_schema.py').read())"
grep -q 'webauthn>=2.0.0' requirements.txt && grep -q '@simplewebauthn/browser' ../frontend/package.json && echo "deps declared"
cd .. && git add backend/requirements.txt frontend/package.json backend/app/webauthn_schema.py backend/main.py
git commit -m "feat(webauthn): deps + webauthn_credentials table + startup migration"
```

---

### Task 2: Backend config, challenge store, capability flag

**Files:**
- Create: `backend/app/api/webauthn.py` (config + challenge helpers + `webauthn_enabled`; router added in Task 5)
- Modify: `backend/app/capabilities.py` (add `webauthn` flag)
- Test: `backend/tests/test_webauthn.py`

**Interfaces:**
- Produces: `webauthn._webauthn_cfg() -> dict` (keys: rp_id, rp_name, origin), `webauthn.webauthn_enabled() -> bool`, `webauthn._challenge_store(nonce, challenge_b64, ttl=300)`, `webauthn._challenge_pop(nonce) -> Optional[str]`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_webauthn.py`:

```python
import importlib, os


def _fresh(monkeypatch, env):
    for k in ("WEBAUTHN_RP_ID", "WEBAUTHN_ORIGIN", "WEBAUTHN_RP_NAME", "EXTERNAL_SCHEME", "APP_DOMAIN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.api.webauthn as w
    return importlib.reload(w)


def test_enabled_requires_https(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "datapond.example.com", "WEBAUTHN_ORIGIN": "https://datapond.example.com"})
    assert w.webauthn_enabled() is True


def test_disabled_on_http(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "datapond.example.com", "WEBAUTHN_ORIGIN": "http://datapond.example.com"})
    assert w.webauthn_enabled() is False


def test_localhost_allowed(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    assert w.webauthn_enabled() is True


def test_disabled_when_unconfigured(monkeypatch):
    w = _fresh(monkeypatch, {})
    assert w.webauthn_enabled() is False


def test_cfg_derives_origin_from_rp_id(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "d.example.com"})
    assert w._webauthn_cfg()["origin"] == "https://d.example.com"
```

- [ ] **Step 2: Run → fail** (`cd backend && python3 -m pytest tests/test_webauthn.py -v` → ModuleNotFoundError app.api.webauthn). Use a py3.11 venv with `webauthn` installed if local import chain needs it.

- [ ] **Step 3: create `backend/app/api/webauthn.py`** (config + challenge store; router/endpoints in later tasks):

```python
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
```

- [ ] **Step 4: Run → pass** (5 tests). `python3 -m py_compile app/api/webauthn.py`.

- [ ] **Step 5: capabilities flag** — in `backend/app/capabilities.py`, add `webauthn` to the returned capabilities dict:

```python
    from app.api.webauthn import webauthn_enabled
    caps["webauthn"] = webauthn_enabled()
```
(Read capabilities.py first to match its exact dict-building style + import placement; if it builds a Pydantic model, add a `webauthn: bool = False` field and set it.)

- [ ] **Step 6: Commit**

```bash
cd backend && python3 -m pytest tests/test_webauthn.py -v   # 5 pass
cd .. && git add backend/app/api/webauthn.py backend/app/capabilities.py backend/tests/test_webauthn.py
git commit -m "feat(webauthn): config + HTTPS gating + single-use challenge store + capability flag"
```

---

### Task 3: Registration endpoints (`/register/begin` + `/register/complete`)

**Files:**
- Modify: `backend/app/api/webauthn.py` (add `router` + register endpoints)
- Test: `backend/tests/test_webauthn.py` (append)

**Interfaces:**
- Consumes: `_webauthn_cfg`, `_challenge_store/_pop`, `_new_nonce`, `require_user`, `_get_pool` (auth).
- Produces: `router` (APIRouter), `POST /api/auth/webauthn/register/begin|complete`.

- [ ] **Step 1: Write the failing test** (registration options are generated + a nonce is stored; full complete needs a real authenticator so we test the options + challenge single-use, and the credential-INSERT via a monkeypatched verify):

```python
def test_register_begin_returns_options_and_stores_challenge(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    import asyncio
    opts, nonce = asyncio.get_event_loop().run_until_complete(
        w._build_registration_options(user_id="00000000-0000-0000-0000-000000000001", username="admin", existing=[])
    )
    assert "challenge" in opts and "rp" in opts
    assert w._challenge_pop(nonce) is not None      # stored
    assert w._challenge_pop(nonce) is None           # single-use consumed
```

- [ ] **Step 2: Run → fail** (`_build_registration_options` undefined).

- [ ] **Step 3: implement** — append to `webauthn.py`:

```python
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
import uuid

router = APIRouter(prefix="/auth/webauthn", tags=["webauthn"])


def _require_enabled():
    if not webauthn_enabled():
        raise HTTPException(status_code=404, detail="WebAuthn is not enabled")


async def _build_registration_options(user_id: str, username: str, existing: list):
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement,
        PublicKeyCredentialDescriptor,
    )
    cfg = _webauthn_cfg()
    opts = generate_registration_options(
        rp_id=cfg["rp_id"], rp_name=cfg["rp_name"],
        user_id=uuid.UUID(user_id).bytes, user_name=username,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    nonce = _new_nonce()
    _challenge_store(nonce, base64.b64encode(opts.challenge).decode())
    return json.loads(options_to_json(opts)), nonce


class CompleteReq(BaseModel):
    nonce: str
    credential: dict
    name: str | None = None


@router.post("/register/begin")
async def register_begin(user: dict = Depends(require_user)):
    _require_enabled()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT credential_id FROM webauthn_credentials WHERE user_id=$1", uuid.UUID(user["id"]))
    opts, nonce = await _build_registration_options(user["id"], user["username"], [r["credential_id"] for r in rows])
    return {"nonce": nonce, "options": opts}


@router.post("/register/complete")
async def register_complete(req: CompleteReq, user: dict = Depends(require_user)):
    _require_enabled()
    from webauthn import verify_registration_response
    chal = _challenge_pop(req.nonce)
    if not chal:
        raise HTTPException(status_code=400, detail="Challenge expired or already used")
    cfg = _webauthn_cfg()
    try:
        v = verify_registration_response(
            credential=req.credential,
            expected_challenge=base64.b64decode(chal),
            expected_origin=cfg["origin"], expected_rp_id=cfg["rp_id"],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration verification failed: {e}")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO webauthn_credentials (user_id, credential_id, public_key, sign_count, aaguid, name)
               VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (credential_id) DO NOTHING""",
            uuid.UUID(user["id"]), v.credential_id, v.credential_public_key, v.sign_count,
            (uuid.UUID(v.aaguid) if getattr(v, "aaguid", None) else None), req.name,
        )
    return {"status": "ok"}
```
(Import auth primitives at top of webauthn.py: `from app.api.auth import require_user, _get_pool, _create_token, get_current_user`. Verify the exact py_webauthn ≥2.0 struct import paths during implementation — `webauthn.helpers.structs` — and the `VerifiedRegistration` attribute names `credential_id`/`credential_public_key`/`sign_count`/`aaguid`.)

- [ ] **Step 4: Run → pass** the options test; `py_compile`.

- [ ] **Step 5: Commit** (`git commit -m "feat(webauthn): passkey registration endpoints (begin/complete)"`).

---

### Task 4: Authentication endpoints (`/authenticate/begin` + `/complete`) — the critical path

**Files:**
- Modify: `backend/app/api/webauthn.py`
- Test: `backend/tests/test_webauthn.py` (append)

**Interfaces:**
- Consumes: register-side helpers + `_create_token`.
- Produces: `POST /api/auth/webauthn/authenticate/begin|complete`; returns `{access_token, token_type, user}` (same as password login).

- [ ] **Step 1: Write the failing test** — sign_count regression is rejected; success issues a JWT-shaped response. Since a real assertion needs an authenticator, test the sign_count-guard helper directly:

```python
def test_sign_count_regression_rejected(monkeypatch):
    w = _fresh(monkeypatch, {"WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": "http://localhost:3000"})
    assert w._sign_count_ok(stored=5, new=6) is True
    assert w._sign_count_ok(stored=5, new=5) is False   # no increase
    assert w._sign_count_ok(stored=5, new=4) is False   # regression
    assert w._sign_count_ok(stored=0, new=0) is True    # counter-less authenticator
```

- [ ] **Step 2: Run → fail** (`_sign_count_ok` undefined).

- [ ] **Step 3: implement** — append:

```python
def _sign_count_ok(stored: int, new: int) -> bool:
    if stored == 0 and new == 0:
        return True          # authenticator doesn't implement a counter
    return new > stored


@router.post("/authenticate/begin")
async def authenticate_begin():
    _require_enabled()
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement
    cfg = _webauthn_cfg()
    opts = generate_authentication_options(
        rp_id=cfg["rp_id"], user_verification=UserVerificationRequirement.PREFERRED,
    )  # no allow_credentials → discoverable/usernameless
    nonce = _new_nonce()
    _challenge_store(nonce, base64.b64encode(opts.challenge).decode())
    return {"nonce": nonce, "options": json.loads(options_to_json(opts))}


class AuthCompleteReq(BaseModel):
    nonce: str
    credential: dict


@router.post("/authenticate/complete")
async def authenticate_complete(req: AuthCompleteReq):
    _require_enabled()
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    chal = _challenge_pop(req.nonce)
    if not chal:
        raise HTTPException(status_code=400, detail="Challenge expired or already used")
    raw_id = base64url_to_bytes(req.credential["rawId"] if "rawId" in req.credential else req.credential["id"])
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.id cid, c.public_key, c.sign_count, u.id uid, u.username, u.role
               FROM webauthn_credentials c JOIN users u ON u.id = c.user_id
               WHERE c.credential_id = $1""", raw_id)
    if not row:
        raise HTTPException(status_code=401, detail="Unknown credential")
    cfg = _webauthn_cfg()
    try:
        v = verify_authentication_response(
            credential=req.credential, expected_challenge=base64.b64decode(chal),
            expected_origin=cfg["origin"], expected_rp_id=cfg["rp_id"],
            credential_public_key=row["public_key"], credential_current_sign_count=row["sign_count"],
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")
    if not _sign_count_ok(row["sign_count"], v.new_sign_count):
        raise HTTPException(status_code=401, detail="Possible cloned authenticator (sign count)")
    async with pool.acquire() as conn:
        await conn.execute("UPDATE webauthn_credentials SET sign_count=$1, last_used_at=NOW() WHERE id=$2",
                           v.new_sign_count, row["cid"])
    token = _create_token(str(row["uid"]), row["username"], row["role"])
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": str(row["uid"]), "username": row["username"], "role": row["role"]}}
```

- [ ] **Step 4: Run → pass** the sign_count test; `py_compile`.

- [ ] **Step 5: Commit** (`git commit -m "feat(webauthn): passwordless authenticate endpoints + sign-count clone guard + JWT"`).

---

### Task 5: Credential management + mount the router

**Files:**
- Modify: `backend/app/api/webauthn.py` (list/delete)
- Modify: `backend/main.py` (mount `webauthn_router`)
- Test: `backend/tests/test_webauthn.py`

- [ ] **Step 1: implement list/delete** — append to webauthn.py:

```python
@router.get("/credentials")
async def list_credentials(user: dict = Depends(require_user)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, created_at, last_used_at FROM webauthn_credentials
               WHERE user_id=$1 ORDER BY created_at DESC""", uuid.UUID(user["id"]))
    return [{"id": str(r["id"]), "name": r["name"], "created_at": r["created_at"].isoformat(),
             "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None} for r in rows]


@router.delete("/credentials/{cred_id}")
async def delete_credential(cred_id: str, user: dict = Depends(require_user)):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM webauthn_credentials WHERE id=$1 AND user_id=$2",
                                 uuid.UUID(cred_id), uuid.UUID(user["id"]))
    if res.endswith("0"):
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"status": "deleted"}
```

- [ ] **Step 2: mount in main.py** — near the base auth router include (line ~208 area, community routers):

```python
from app.api.webauthn import router as webauthn_router
app.include_router(webauthn_router, prefix="/api")
```
(Add the import with the other `app.api.*` imports at the top; the include with the other community `app.include_router(..., prefix="/api")` calls. NOT in the `/ee` try-block.)

- [ ] **Step 3: Verify + commit**

```bash
cd backend && python3 -m py_compile app/api/webauthn.py main.py
python3 -c "import ast; ast.parse(open('app/api/webauthn.py').read())"
# route table sanity (needs webauthn lib): python3 -c "from app.api.webauthn import router; print([r.path for r in router.routes])"
cd .. && git add backend/app/api/webauthn.py backend/main.py backend/tests/test_webauthn.py
git commit -m "feat(webauthn): credential list/delete (owner-scoped) + mount router"
```

---

### Task 6: Frontend — passkey login button + settings management

**Files:**
- Modify: `frontend/app/login/page.tsx` (passkey login button, capability-gated)
- Create: `frontend/components/passkey-manager.tsx` (add/list/delete, used in settings/profile)
- Modify: `frontend/app/settings/page.tsx` (mount the passkey manager)
- Modify: a capabilities hook/fetch to read `webauthn`

- [ ] **Step 1: login page passkey button** — add to `login/page.tsx` (read the file first to match its state/fetch style). Fetch `/api/capabilities`, and when `webauthn` is true render a "Sign in with a passkey" button:

```tsx
import { startAuthentication } from "@simplewebauthn/browser"
// ...inside the component:
async function passkeyLogin() {
  const begin = await fetch("/api/auth/webauthn/authenticate/begin", { method: "POST" }).then(r => r.json())
  const assertion = await startAuthentication({ optionsJSON: begin.options })
  const res = await fetch("/api/auth/webauthn/authenticate/complete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nonce: begin.nonce, credential: assertion }),
  })
  if (!res.ok) { setError("Passkey sign-in failed"); return }
  const data = await res.json()
  // store data.access_token exactly like the password path (reuse the existing token-store logic)
}
```
(Wire `passkeyLogin` to a button rendered only when the capabilities `webauthn` flag is true. Reuse the SAME token persistence the password login uses — read how the password path stores `access_token` and call the identical code.)

- [ ] **Step 2: `passkey-manager.tsx`** — authenticated component: "Add passkey" (`startRegistration`), list (`GET /credentials`), delete:

```tsx
import { startRegistration } from "@simplewebauthn/browser"
// addPasskey: POST /register/begin → startRegistration({optionsJSON: begin.options}) →
//   POST /register/complete {nonce, credential, name}; then refresh list.
// list: GET /api/auth/webauthn/credentials (Bearer token). delete: DELETE /credentials/{id}.
```
(Write the full component following the app's existing fetch-with-auth + list/table conventions — read a neighboring settings component for the pattern.)

- [ ] **Step 3: mount in settings + verify build**

```bash
cd frontend && npm run build 2>&1 | tail -20   # after `npm install` locally to resolve @simplewebauthn/browser
```
(CI `frontend-check` runs type+lint; ensure the new imports resolve — the dep was added to package.json in Task 1.)

- [ ] **Step 4: Commit** (`git commit -m "feat(webauthn): frontend passkey login + settings passkey management"`).

---

### Task 7: Helm/env wiring + license-gate + PR + final review

**Files:**
- Modify: `helm/datapond/values.yaml` (+ values-foundation/values-prod-single) — `auth.webauthn` block
- Modify: `helm/datapond/templates/backend-deployment.yaml` — inject `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN`/`WEBAUTHN_RP_NAME` env

- [ ] **Step 1: Helm env** — add an `auth.webauthn` values block (rpId/rpName/origin, all default "") mirroring the `auth.oidc` block, and inject the 3 env vars into `backend-deployment.yaml` (gated `{{- with }}` so empty = unset = feature off). Read the existing `auth.oidc` wiring and mirror it exactly.

- [ ] **Step 2: verify Helm renders**

```bash
helm lint helm/datapond --values helm/datapond/values-foundation.yaml
helm template datapond helm/datapond --values helm/datapond/values-foundation.yaml --set auth.webauthn.rpId=d.example.com --set auth.webauthn.origin=https://d.example.com | grep -q WEBAUTHN_RP_ID && echo OK
```

- [ ] **Step 3: license-gate check** — confirm the new deps pass the P0-2 CI denylist (webauthn BSD-3, cbor2 MIT, @simplewebauthn MIT are allowlist-clean). If the license-gate job pins a direct-deps manifest, add the new deps there.

- [ ] **Step 4: PR + CI + final review**

```bash
git add helm/datapond
git commit -m "feat(webauthn): Helm auth.webauthn env wiring"
git push -u origin feat/passkey-webauthn
gh pr create --title "feat: passwordless passkey/WebAuthn (community)" --body "..."
```
CI: backend-tests (test_webauthn), frontend-check, helm-lint, license-gate. Then opus whole-branch review.

---

## Self-Review

**Spec coverage:** §1 decisions → all tasks; §2 deps → Task 1 + Task 7 license-gate; §3 storage → Task 1 (table + migration); §4 backend endpoints → Task 2 (config/challenge/capability) + Task 3 (register) + Task 4 (authenticate) + Task 5 (manage + mount); §5 frontend → Task 6; §6 security → Task 2 (single-use challenge, HTTPS gate), Task 3 (require_user, exclude_credentials), Task 4 (sign-count guard, alg allowlist via py_webauthn, origin/RP-ID via verify), Task 5 (owner-scoped delete); §7 testing → tests in Tasks 2/3/4 + Task 7 license-gate; §8 out-of-scope honored (no MFA path, no attestation enforcement); §9 open items → Task 7 Helm env + the HTTPS/domain dependency documented.

**Placeholder scan:** the frontend steps (Task 6) reference "reuse the existing token-store logic" / "follow neighboring component conventions" — these are deliberate (the implementer must match the app's existing auth-token persistence, which varies) with the exact API calls + library functions given in full. The `gh pr create --body "..."` is filled at PR time. All backend code is complete + literal. No TBDs in backend logic.

**Consistency:** `webauthn_enabled()` defined in Task 2, consumed by `_require_enabled()` (Tasks 3/4) + capabilities (Task 2) + frontend gate (Task 6). `_challenge_store/_pop/_new_nonce` (Task 2) used by register (Task 3) + authenticate (Task 4). `_create_token`/`require_user`/`_get_pool` imported from auth consistently. Table columns (`credential_id`, `public_key`, `sign_count`, `aaguid`, `name`) identical across Task 1 (DDL), Task 3 (INSERT), Task 4 (SELECT/UPDATE), Task 5 (SELECT/DELETE). Endpoint paths `/api/auth/webauthn/{register,authenticate}/{begin,complete}` + `/credentials` consistent between backend (router prefix `/auth/webauthn` + `/api`) and frontend fetch URLs.

**Flagged for implementer:** the exact py_webauthn ≥2.0 API surface (`webauthn.helpers.structs` import paths, `VerifiedRegistration`/`VerifiedAuthentication` attribute names, `options_to_json`, `base64url_to_bytes`) must be confirmed against the installed version during Task 3/4 — the plan uses the v2.x names; if a newer major renamed them, adjust. This is the one external-API risk; everything else is internal.
