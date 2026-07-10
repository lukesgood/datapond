# Passkey / WebAuthn (Passwordless) — Design

**Date**: 2026-07-10
**Status**: Design approved (pre-plan)
**Context**: DataPond auth today = local password (JWT), OIDC SSO (`/ee`), LDAP. Passkey/WebAuthn is **schema-only, zero implementation** — a `mfa_device_type='webauthn'` enum value + an unused `mfa_devices` table + an unused `users.mfa_enabled` column. No WebAuthn library, no endpoints, no UI, and the `login()` flow has no second-factor step. This spec implements passwordless-primary passkeys.

## 1. Decisions (confirmed)

| Axis | Decision | Rationale |
|---|---|---|
| Auth model | **Passwordless-primary** (passkey IS the login) | Modern passkey UX; password stays as fallback |
| Open-core | **Apache community** (`backend/app/api/`, NOT `/ee`) | Free adoption driver; SSO remains the premium auth tenant |
| Library | **`py_webauthn` (backend, BSD-3) + `@simplewebauthn/browser` (frontend, MIT)** | WebAuthn crypto (CBOR/COSE/attestation/sign-count) is too security-sensitive to hand-roll — a deliberate departure from the OIDC "zero new deps" precedent |
| Storage | **New `webauthn_credentials` table** | `mfa_devices` has MFA semantics (recovery codes, pending_verification) that don't fit passwordless-primary; leave it dormant |
| Challenge store | **Valkey, single-use, 5-min TTL** | Reuses the OIDC state pattern |
| RP ID / origin | **`WEBAUTHN_RP_ID` + `WEBAUTHN_ORIGIN` env** (derive from domain/`EXTERNAL_SCHEME` if unset); **HTTPS required** (localhost dev-exempt) | WebAuthn requires a secure context + a stable RP ID (domain-bound) |
| Token | **Reuse `auth._create_token`** — a passkey login yields the same JWT as password login | One session model |
| Gating | `/api/capabilities` exposes `webauthn` true only when HTTPS + configured | Hide the button where secure-context would fail |

## 2. Dependencies (first real new runtime deps — justified)

- Backend `requirements.txt`: `webauthn` (py_webauthn, BSD-3-Clause; pulls `cbor2` MIT, `cryptography` Apache/BSD — all license-gate-clean).
- Frontend `package.json`: `@simplewebauthn/browser` (MIT).
- **CI license-gate (P0-2)** must pass — BSD-3/MIT are on the allowlist; confirm the new transitive deps don't trip the denylist.

## 3. Storage — `webauthn_credentials`

```sql
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id BYTEA NOT NULL UNIQUE,        -- raw credential ID (the lookup key)
    public_key    BYTEA NOT NULL,               -- COSE-encoded public key
    sign_count    BIGINT NOT NULL DEFAULT 0,    -- clone-detection counter
    transports    TEXT[],                       -- e.g. {internal,hybrid,usb}
    aaguid        UUID,                          -- authenticator model id
    name          VARCHAR(128),                 -- user label, e.g. "MacBook Touch ID"
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webauthn_cred_user ON webauthn_credentials(user_id);
```

Applied via an **idempotent startup migration** (`CREATE TABLE IF NOT EXISTS` in a runner that runs every startup, like `rls_migration.sql`) — `auth.sql` is sentinel-guarded and won't re-run on an existing DB, so new tables must come through the always-run migration path. The dormant `mfa_devices` table is left untouched (unused).

## 4. Backend — `backend/app/api/webauthn.py` (community)

A FastAPI router (`prefix=/api/auth/webauthn`, mounted in `main.py` alongside the base auth router — NOT via the `/ee` try-import). Four endpoints + one management:

- **`POST /register/begin`** (`require_user`): `generate_registration_options()` (RP ID/name, user_handle = user_id UUID bytes, `exclude_credentials` = the user's existing creds, `resident_key=required`, `user_verification=preferred`). Store the challenge in Valkey keyed by a single-use nonce (5-min TTL). Return options JSON.
- **`POST /register/complete`** (`require_user`): pop+verify the challenge; `verify_registration_response(origin, rp_id)`; on success INSERT into `webauthn_credentials` (credential_id, public_key, sign_count, transports, aaguid, name from request). 400 on verification failure.
- **`POST /authenticate/begin`** (public): `generate_authentication_options()` with `user_verification=preferred`, no `allow_credentials` (discoverable/usernameless). Store challenge in Valkey (single-use, 5-min). Return options.
- **`POST /authenticate/complete`** (public): pop+verify challenge; look up the credential by `credential_id` (from the assertion); `verify_authentication_response(origin, rp_id, credential_public_key, credential_current_sign_count)`; **reject if new sign_count ≤ stored (clone detection)**, unless both are 0; update sign_count + last_used_at; issue a JWT via `auth._create_token(user_id, username, role)`. Return `{access_token, token_type, user}` — identical shape to `POST /api/auth/login`.
- **`GET /credentials`** + **`DELETE /credentials/{id}`** (`require_user`): list/remove the caller's passkeys (scoped to `user_id` — a user can only manage their own).

Config helper `_webauthn_cfg()`: `WEBAUTHN_RP_ID` (default derived from the app domain), `WEBAUTHN_RP_NAME` (default "DataPond"), `WEBAUTHN_ORIGIN` (default `https://{RP_ID}`). `webauthn_enabled()` = origin is HTTPS (or localhost) AND RP_ID set.

## 5. Frontend — `@simplewebauthn/browser`

- **Login page** (`app/login/page.tsx`): a **"Sign in with a passkey"** button next to the password form → `startAuthentication()` against `/authenticate/begin`→`complete` → store the returned JWT exactly like the password path. Password remains the fallback. Optional: `browserSupportsWebAuthnAutofill()` → conditional-UI autofill on the username field.
- **Settings/profile**: an **"Add passkey"** button (authenticated) → `startRegistration()` against `/register/begin`→`complete`; a list of the user's passkeys (name, created, last-used) with delete.
- **Capability gating**: `/api/capabilities` gains a `webauthn` boolean (true only when `webauthn_enabled()`); the login button + settings section render only when true — so an HTTP/misconfigured deploy hides passkey rather than offering a button that the browser's secure-context requirement would reject.

## 6. Security

- **Challenge**: server-generated random, stored single-use in Valkey (5-min TTL), deleted on consume — a replayed/duplicate challenge is rejected (OIDC state pattern).
- **Verification**: origin + RP ID exact match; challenge match; COSE algorithm allowlist (ES256/RS256).
- **Clone detection**: `sign_count` must strictly increase (reject on regression; 0/0 allowed for authenticators that don't implement a counter).
- **Account binding**: registration is `require_user`-gated so a passkey can only be bound to the authenticated caller; the discoverable credential `user_handle` = the user_id UUID, so authentication resolves to exactly one account.
- **HTTPS**: `webauthn_enabled()` is false on non-HTTPS (non-localhost) → the whole passkey path is gated off. Ties passkey to the production spec's Route53 domain + Let's Encrypt TLS.
- **No account enumeration**: `/authenticate/begin` returns options regardless of any username (usernameless), so it can't be used to probe accounts.

## 7. Testing

- **Backend pytest** (`backend/tests/test_webauthn.py`): challenge single-use (second pop fails); `_webauthn_cfg()` HTTPS-gating (http → disabled, https/localhost → enabled); registration stores a credential; authentication rejects a **sign_count regression**; origin/RP-ID mismatch → 400; algorithm outside the allowlist → rejected; JWT issued on success has the same shape as password login. Wrap `py_webauthn` verify calls; use fixtures for canned attestation/assertion objects (py_webauthn ships test vectors).
- **CI license-gate**: assert `webauthn`/`cbor2` + `@simplewebauthn/browser` pass the denylist (BSD-3/MIT).
- **Live (post-deploy)**: on a real domain + TLS, register a passkey (Touch ID / security key) and passwordless-login E2E.

## 8. Out of scope (YAGNI)

- Passkey as MFA second-factor (chose passwordless-primary); the dormant `mfa_devices`/TOTP path stays unimplemented.
- Enterprise attestation enforcement / AAGUID allowlists (accept `none`/`packed`; a `WEBAUTHN_REQUIRE_ATTESTATION` toggle is a later enhancement).
- Account-recovery flows specific to passkeys (password + admin reset remain the recovery path).
- SAML (unrelated; OIDC-only SSO stands).
- Conditional-UI autofill is optional/best-effort, not a v1 requirement.

## 9. Open items for deploy-time

- `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` = the production domain (from the single-node deploy spec). Passkey is inert until a real HTTPS domain exists.
- Helm: add `auth.webauthn` values (rpId/rpName/origin) + wire the env, mirroring the `auth.oidc` block.
