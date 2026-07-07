# SSO (OIDC) — First `/ee` Enterprise Feature (P0-3) — Design

**Date**: 2026-07-07
**Status**: Design approved (pre-implementation)
**Context**: auth.sql drafts rich SSO tables but they are DORMANT — live installs run the minimal `users` schema and the sentinel bootstrap skips auth.sql. The LDAP integration (#41) is the wiring precedent. P0-2 established `/ee` as the commercial directory; this is its first tenant.

## 1. Decisions (confirmed)

| Decision | Choice |
|---|---|
| Protocol | **OIDC only** (authorization-code + PKCE). SAML = future /ee fast-follow |
| Packaging | **Root build context + `EDITION` build arg** — multi-stage Dockerfile, `--target community` (no `/app/ee`) vs `--target enterprise` (`COPY ee/backend/ee /app/ee`); Apache-side hook = try-import in main.py; community images 404 the endpoints |
| Config surface | **Env vars, LDAP parity** — `auth.oidc.*` Helm values → gated env block; client secret via datapond-secrets. One IdP per deployment. The dormant `oidc_configs` DB tables stay dormant |
| OIDC client | **Hand-rolled RP on existing deps** — httpx (discovery/exchange) + python-jose (JWKS verify). Zero new dependencies in either edition |
| License enforcement | **None in v1** — contractual (ee/LICENSE); key validation arrives with Marketplace billing |
| Provisioning | JIT, LDAP-precedent semantics (anti-shadow guard, no reactivation, role refresh per login) |

## 2. `/ee` layout & build

```
ee/backend/ee/__init__.py
ee/backend/ee/sso/__init__.py
ee/backend/ee/sso/oidc.py      # discovery, PKCE, token exchange, id_token verification, JWKS cache
ee/backend/ee/sso/router.py    # GET /api/auth/oidc/login, GET /api/auth/oidc/callback
ee/backend/tests/test_oidc.py
```

- `backend/Dockerfile`: build context becomes **repo root** (`docker build -f backend/Dockerfile .`). Stages: `base` (current content, `COPY backend/ /app`), `community` (= base), `enterprise` (base + `COPY ee/backend/ee /app/ee`). Default target: enterprise.
- `scripts/build.sh` + `scripts/bundle-airgap.sh`: context/flag updates, `EDITION` env (default `enterprise`).
- New root `.dockerignore` (node_modules, .git, docs, .superpowers, frontend for the backend build path etc.).
- `backend/main.py` hook (stays Apache-licensed, generic):
  ```python
  try:
      from ee.sso.router import router as sso_router
      app.include_router(sso_router)
      EE_SSO = True
  except ImportError:
      EE_SSO = False
  ```
- `/api/capabilities` (#105 mechanism) gains `"sso": EE_SSO and OIDC_ENABLED`.
- Runbook note: the live EC2 tar-sync must now include `ee/` (same class as the existing full-source-sync caveat).
- `ee/README.md` updated: SSO is now present, not "planned".

## 3. Backend flow

**`GET /api/auth/oidc/login`** → 302 to IdP authorize URL:
- Discovery document fetched from `{OIDC_ISSUER}/.well-known/openid-configuration`, cached in-process (TTL 1h).
- Generates `state` (32B urlsafe), `nonce`, PKCE `code_verifier`/S256 challenge.
- Stores `state → {nonce, code_verifier}` in **Valkey, TTL 600s, single-use** (GETDEL semantics); in-memory dict fallback when Valkey is unreachable (dev).
- Params: `response_type=code`, `client_id`, `redirect_uri`, `scope` (default `openid profile email`), `state`, `nonce`, `code_challenge(+_method=S256)`.

**`GET /api/auth/oidc/callback?code&state`**:
1. Pop state from store (missing/reused → redirect `/login?error=sso_failed&reason=state`).
2. Token exchange (httpx POST, `client_secret_post` + `code_verifier`).
3. **id_token verification (python-jose)**: signature against IdP JWKS (cached 1h; refetch once on unknown `kid`), `iss` == issuer, `aud` == client_id, `exp`/`iat` with 60s skew, `nonce` matches stored. **Alg allowlist RS256/ES256** — `none`/HS* rejected (alg-confusion defense). Claims come from the id_token; userinfo endpoint is NOT called in v1.
4. Identity: `external_id = sub`; `username = preferred_username || email` (missing both → `reason=claims`); `email`, `display_name = name` claim.
5. **JIT upsert** (LDAP-precedent):
   `INSERT ... ON CONFLICT (username) DO UPDATE SET ... WHERE users.auth_method='oidc'` — sets `auth_method='oidc'`, `external_id`, no password, `is_active=true` on INSERT only (never reactivates); a `local`/`ldap` account with the same username is never modified → login fails with `reason=account_conflict`.
6. **Role mapping per login**: `OIDC_ADMIN_GROUP` ∈ claims[`OIDC_GROUP_CLAIM` (default `groups`)] → `admin`, else `OIDC_DEFAULT_ROLE` (default `viewer`). Synced to `user_roles` the same way `update_user` does (RLS context source).
7. Mint the standard DataPond JWT (reuse auth.py's existing token-issuance helper — same claims `{sub, username, role, exp}`), set `datapond_token` cookie (24h, SameSite=Lax, path=/), 302 → `/login?sso=1`.

**No schema migration**: uses the live minimal `users` columns (`auth_method` VARCHAR, `external_id`, `attributes`). `external_provider` (auth.sql-only column) is not used — single IdP per deployment.

**Error handling**: every failure mode (discovery down, state invalid, exchange failure, token invalid, claims missing, account conflict) → `logger.warning` with detail + 302 `/login?error=sso_failed&reason=<slug>`. Never a raw 500 mid-flow. Reason slugs: `state`, `exchange`, `token`, `claims`, `account_conflict`, `provider`.

## 4. Config & Helm (LDAP parity)

`values.yaml` under `auth:`:
```yaml
  oidc:
    enabled: false
    issuer: ""            # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    clientId: ""
    clientSecret: ""      # → datapond-secrets OIDC_CLIENT_SECRET (with-guarded, like LDAP_BIND_PASSWORD)
    scopes: "openid profile email"
    redirectUrl: ""       # empty ⇒ {global.externalScheme}://{ingress.domain}/api/auth/oidc/callback
    groupClaim: "groups"
    adminGroup: ""        # IdP group granting role=admin
    defaultRole: "viewer"
```
`backend-deployment.yaml`: gated block `{{- if (((.Values.auth).oidc).enabled) }}` exporting `OIDC_ENABLED/ISSUER/CLIENT_ID/SCOPES/REDIRECT_URL/GROUP_CLAIM/ADMIN_GROUP/DEFAULT_ROLE` + `OIDC_CLIENT_SECRET` via secretKeyRef. secrets.yaml: `with`-guarded `OIDC_CLIENT_SECRET` entry (explicit value only, like LDAP_BIND_PASSWORD — no generation; it comes from the IdP).

Reads in ee code are lazy/call-time; the secret is required-when-enabled via `component_secret("OIDC_CLIENT_SECRET", "", component="oidc")` inside the flow (prod fail-closed per P0-1b convention).

## 5. Frontend (community — no /ee frontend code)

- Login page: "Sign in with SSO" button shown when `/api/capabilities` reports `sso: true`; plain navigation to `/api/auth/oidc/login`.
- `/login?sso=1` handler: read `datapond_token` cookie → `GET /api/auth/me` → existing `saveAuth()` (repairs localStorage/cookie dual store) → `window.location.replace("/dashboard")`. `?error=sso_failed` renders the reason-slug message inline.
- `AUTH_EXEMPT` (backend main.py) and frontend proxy `PUBLIC_PATHS` gain `/api/auth/oidc/login` and `/api/auth/oidc/callback`.

## 6. Testing

- `ee/backend/tests/test_oidc.py` (pytest, CI py3.11 via `PYTHONPATH=ee/backend`): id_token verification against a locally-generated RSA key/JWKS — valid, expired, wrong-aud, wrong-iss, wrong-nonce, alg=none/HS256 rejection; state store single-use; PKCE challenge derivation; JIT upsert anti-shadow guard + no-reactivation (against the test DB pattern used by existing auth tests, or mocked pool); role mapping (admin group present/absent).
- CI: extend the backend test step to include ee tests; `py_compile` over `ee/backend`. Docker `--target` build verification is OUT of CI scope (no docker on runners; verified at deploy/build time — revisit with P0-4 image work).
- Capabilities flag: existing capabilities endpoint test pattern extended for `sso`.

## 7. Out of scope

SAML; DB-config + Settings UI (oidc_configs stays dormant); license-key runtime enforcement; IdP-initiated login; single logout (SLO)/back-channel logout; refresh tokens (DataPond JWT lifetime governs the session); multi-IdP; userinfo endpoint claims merge; frontend `/ee` packaging.
