# DataPond Auth Implementation Plan

**Date:** 2026-04-30  
**Status:** Designed, awaiting implementation  
**Owner:** Backend Team  
**Total duration:** 4 weeks (20 working days)  
**Dependencies:** PostgreSQL (running), Valkey (running), FastAPI backend (running)

---

## Phase 1: Local Auth + JWT + API Keys (Days 1--5)

**Goal:** Every API endpoint is protected. Users authenticate with email/password. Sessions are managed via JWT. API keys are supported for programmatic access. Audit logging is active from day one.

### Day 1: Database Schema + Project Structure

| Task | Details |
|------|---------|
| Run `backend/schema/auth.sql` | Create all tables, seed roles, permissions, default admin user |
| Create module layout | `backend/app/auth/` with `__init__.py`, `models.py`, `schemas.py`, `service.py`, `dependencies.py`, `router.py`, `jwt.py`, `password.py`, `audit.py` |
| Add Python dependencies | `python-jose[cryptography]`, `passlib[bcrypt]`, `pyotp` (for Phase 3), `python3-saml` (for Phase 3) |
| Generate RSA key pair | Create 2048-bit RSA key pair, store as Kubernetes Secret `datapond-jwt-signing-key` |
| Config module | `backend/app/auth/config.py` -- read all auth settings from env vars / Helm values |

**Files created:**
```
backend/app/auth/__init__.py
backend/app/auth/config.py
backend/app/auth/models.py         (SQLAlchemy ORM models for all auth tables)
backend/app/auth/schemas.py        (Pydantic request/response schemas)
backend/app/auth/password.py       (bcrypt hashing, password validation)
backend/app/auth/jwt.py            (JWT creation, validation, key loading)
backend/app/auth/audit.py          (Audit log writer)
backend/app/auth/service.py        (Business logic: login, register, etc.)
backend/app/auth/dependencies.py   (FastAPI Depends: get_current_user, require_permission)
backend/app/auth/router.py         (API routes)
backend/schema/auth.sql            (already exists)
```

### Day 2: Core Auth Service + Login/Logout

| Task | Details |
|------|---------|
| `password.py` | `hash_password()`, `verify_password()`, `validate_password_policy()`, `check_password_history()` |
| `jwt.py` | `create_access_token()`, `create_refresh_token()`, `decode_token()`, `load_signing_keys()` |
| `service.py` -- login | Validate credentials, check account status (locked/inactive), enforce password expiry, handle failed login count, generate token pair, create Valkey session, write audit log |
| `service.py` -- logout | Revoke tokens (add to Valkey revocation set), terminate session, write audit log |
| `router.py` | `POST /api/auth/login`, `POST /api/auth/logout` |
| Valkey integration | Session storage, token revocation set, rate limiting counters |

### Day 3: Auth Middleware + Permission System

| Task | Details |
|------|---------|
| `dependencies.py` | `get_current_user()` -- extract JWT from `Authorization: Bearer` header, validate, check revocation, return user context |
| `dependencies.py` | `require_permission(resource, action)` -- decorator/dependency that checks RBAC |
| Auth middleware | FastAPI middleware that runs `get_current_user()` on all `/api/*` routes except `/api/auth/login`, `/api/health` |
| Protect existing routes | Add `require_permission()` to all existing API endpoints in `queries.py`, `catalog.py`, `connectors.py` |
| Rate limiting | Implement sliding window rate limiter in Valkey for auth endpoints |

### Day 4: User Management + API Keys

| Task | Details |
|------|---------|
| User CRUD | `POST /api/admin/users`, `GET /api/admin/users`, `GET /api/admin/users/{id}`, `PUT /api/admin/users/{id}`, `DELETE /api/admin/users/{id}` |
| Role assignment | `POST /api/admin/users/{id}/roles`, `DELETE /api/admin/users/{id}/roles/{role_id}` |
| Password management | `POST /api/auth/password/change` (self-service), `POST /api/admin/users/{id}/password/reset` (admin) |
| API key management | `POST /api/auth/api-keys` (create), `GET /api/auth/api-keys` (list own), `DELETE /api/auth/api-keys/{id}` (revoke) |
| API key auth | Support `X-API-Key` header as alternative to JWT `Authorization` header |
| Session management | `GET /api/auth/sessions` (list own), `DELETE /api/auth/sessions/{id}` (terminate own), `GET /api/admin/sessions` (admin: list all), `DELETE /api/admin/sessions/{id}` (admin: terminate any) |

### Day 5: Token Refresh + Testing + Polish

| Task | Details |
|------|---------|
| Token refresh | `POST /api/auth/refresh` -- validate refresh token, rotate (issue new pair, invalidate old), detect reuse attacks |
| `GET /api/auth/me` | Return current user profile, roles, permissions |
| Account lockout | Auto-lock after N failed attempts, auto-unlock after configurable duration |
| Integration tests | Test login flow, permission checks, token refresh, API key auth, rate limiting, account lockout |
| Frontend auth | Add login page to Next.js frontend, store tokens, add `Authorization` header to all API calls, redirect to login on 401 |
| CORS tightening | Replace `allow_origins=["*"]` with actual domain |

**Phase 1 deliverables:**
- All API endpoints require authentication
- Login/logout with JWT (RS256)
- RBAC permission checks on every endpoint
- API key support for CLI/SDK
- Audit log for all auth events
- Rate limiting on auth endpoints
- Account lockout protection
- Frontend login page

---

## Phase 2: LDAP / Active Directory Integration (Days 6--10)

**Goal:** Enterprise customers can authenticate users against their existing Active Directory or LDAP server. Group memberships are mapped to DataPond roles automatically.

### Day 6: LDAP Client + Configuration

| Task | Details |
|------|---------|
| Add `python-ldap` dependency | Or `ldap3` (pure Python, no C deps -- better for containers) |
| LDAP client module | `backend/app/auth/ldap.py` -- connection pool, bind, search, group membership |
| IdP config APIs | `POST /api/admin/idp/ldap`, `GET /api/admin/idp/ldap`, `PUT /api/admin/idp/ldap/{id}`, `DELETE /api/admin/idp/ldap/{id}` |
| Connection test | `POST /api/admin/idp/ldap/{id}/test` -- validate connectivity, bind credentials, search |
| Secrets encryption | Encrypt LDAP bind password with AES-256-GCM before storing |

### Day 7: LDAP Authentication Flow

| Task | Details |
|------|---------|
| Login with LDAP | Extend `POST /api/auth/login` to accept `auth_method: "ldap"`, perform LDAP bind, validate credentials |
| User provisioning | On first LDAP login, create user record in `users` table with `auth_method='ldap'` and `external_id=DN` |
| User attribute sync | Pull display name, email, department, etc. from LDAP attributes on each login |
| Group-to-role mapping | Configure `ldap_group_mappings`, on login fetch user's LDAP groups and assign corresponding DataPond roles |
| Auto-deactivation | If user is disabled in AD (userAccountControl flag), set status to `inactive` in DataPond |

### Day 8: Group Mapping UI + Background Sync

| Task | Details |
|------|---------|
| Group mapping API | `POST /api/admin/idp/ldap/{id}/group-mappings`, `GET ...`, `PUT ...`, `DELETE ...` |
| LDAP browser | `GET /api/admin/idp/ldap/{id}/browse?base_dn=...&filter=...` -- browse LDAP tree for group selection |
| Background sync | Periodic background task (configurable interval) that syncs LDAP group memberships for all LDAP users |
| Stale user handling | If LDAP user no longer exists in directory, mark as `inactive` in DataPond |

### Day 9: TLS + Multiple LDAP Sources

| Task | Details |
|------|---------|
| LDAPS/StartTLS | Support both LDAPS (port 636) and StartTLS (port 389). Require TLS in production. |
| Custom CA certificates | Accept PEM-encoded CA cert for environments with internal PKI |
| Multiple LDAP configs | Support multiple LDAP servers with priority ordering (try primary first, failover to secondary) |
| Connection pooling | Reuse LDAP connections, configurable pool size and timeout |

### Day 10: Testing + Documentation

| Task | Details |
|------|---------|
| Integration tests | Test against a containerized OpenLDAP instance in CI |
| Test AD-specific features | Test `sAMAccountName`, `userPrincipalName`, nested group resolution |
| Frontend: LDAP config page | Admin settings page to configure LDAP connection, test it, manage group mappings |
| Documentation | LDAP setup guide with examples for Active Directory, OpenLDAP, FreeIPA |

**Phase 2 deliverables:**
- LDAP/AD authentication
- Automatic user provisioning from LDAP
- Group-to-role mapping
- Background group synchronization
- Multiple LDAP server support with failover
- TLS/LDAPS support with custom CA certificates

---

## Phase 3: SAML 2.0 + OIDC + MFA (Days 11--15)

**Goal:** Support enterprise SSO via SAML and OIDC. Add TOTP-based MFA as a second authentication factor.

### Day 11: SAML 2.0 Service Provider

| Task | Details |
|------|---------|
| Add `python3-saml` dependency | OneLogin's SAML toolkit (well-maintained, production-grade) |
| SAML module | `backend/app/auth/saml.py` -- AuthnRequest generation, response parsing, signature validation |
| SP metadata endpoint | `GET /api/auth/saml/metadata` -- serve SP metadata XML for IdP registration |
| SAML login flow | `GET /api/auth/saml/login` -- redirect to IdP; `POST /api/auth/saml/acs` -- process assertion |
| SAML config API | `POST /api/admin/idp/saml`, `GET ...`, `PUT ...`, `DELETE ...` |

### Day 12: SAML Attribute Mapping + SLO

| Task | Details |
|------|---------|
| Attribute extraction | Parse SAML assertion attributes (email, name, groups) via configurable mapping |
| User provisioning | Create/update user on SAML login (same pattern as LDAP) |
| Group-to-role mapping | Map SAML group attributes to DataPond roles |
| Single Logout (SLO) | `GET /api/auth/saml/slo` -- initiate SLO, `POST /api/auth/saml/slo/callback` -- process SLO response |
| IdP-initiated SSO | Optional support for IdP-initiated login (disabled by default for security) |

### Day 13: OIDC Relying Party

| Task | Details |
|------|---------|
| Add `authlib` dependency | Comprehensive OAuth/OIDC library |
| OIDC module | `backend/app/auth/oidc.py` -- authorization URL, token exchange, ID token validation |
| OIDC discovery | Auto-discover endpoints from `/.well-known/openid-configuration` |
| OIDC login flow | `GET /api/auth/oidc/login` -- redirect to provider; `GET /api/auth/oidc/callback` -- exchange code |
| PKCE | Mandatory PKCE for all OIDC flows (S256 challenge method) |
| OIDC config API | `POST /api/admin/idp/oidc`, `GET ...`, `PUT ...`, `DELETE ...` |

### Day 14: TOTP MFA

| Task | Details |
|------|---------|
| Add `pyotp` dependency | TOTP implementation (RFC 6238) |
| MFA module | `backend/app/auth/mfa.py` -- TOTP secret generation, QR code generation, code verification |
| MFA enrollment | `POST /api/auth/mfa/enroll` -- generate secret, return QR code URI; `POST /api/auth/mfa/enroll/verify` -- confirm with initial code |
| MFA challenge | During login (after password verified), if MFA enabled: return `202` with `mfa_challenge_id`, require `POST /api/auth/mfa/verify` |
| Recovery codes | Generate 10 one-time recovery codes at enrollment, hash and store. `POST /api/auth/mfa/recovery` -- use recovery code |
| MFA device management | `GET /api/auth/mfa/devices`, `DELETE /api/auth/mfa/devices/{id}` |
| Admin MFA enforcement | Admins can require MFA for specific roles via `auth_settings` |

### Day 15: Testing + Frontend SSO Pages

| Task | Details |
|------|---------|
| SAML tests | Test against a containerized SimpleSAMLphp IdP |
| OIDC tests | Test against a containerized Keycloak instance |
| MFA tests | Test TOTP enrollment, verification, recovery codes, enforcement |
| Frontend: SSO buttons | Add "Login with SSO" button on login page (auto-detected from configured IdPs) |
| Frontend: MFA setup | User settings page for MFA enrollment with QR code display |
| Frontend: IdP admin | Admin pages for SAML/OIDC configuration |

**Phase 3 deliverables:**
- SAML 2.0 SSO with attribute mapping and SLO
- OIDC SSO with PKCE and auto-discovery
- TOTP MFA enrollment, challenge, and verification
- Recovery codes for MFA
- Admin-enforced MFA per role
- Frontend SSO and MFA pages

---

## Phase 4: RBAC Integration + Data Security (Days 16--20)

**Goal:** Extend auth to all platform components. Implement row-level security and column masking. Complete the admin UI.

### Day 16: Trino Access Control Plugin

| Task | Details |
|------|---------|
| Plugin scaffold | Java project: `datapond-trino-access-control` implementing `SystemAccessControl` interface |
| Permission checks | `checkCanSelectFromTable()`, `checkCanInsertIntoTable()`, `checkCanDropTable()`, etc. -- all check against DataPond RBAC |
| User identity | Read user identity from `X-Trino-Extra-Credential` header set by the DataPond backend |
| Policy caching | Cache permission lookups from PostgreSQL with 60-second TTL in Trino plugin memory |
| Deployment | Build JAR, deploy as Trino plugin via Helm |

### Day 17: Row-Level Security + Column Masking

| Task | Details |
|------|---------|
| RLS in Trino plugin | Intercept queries, inject WHERE clauses based on `rls_policies` table. User attributes (department, region) available in filter expressions. |
| Column masking in Trino plugin | Wrap column references in masking functions based on `column_masking_policies` table. Support all masking types: full, partial_email, partial_ssn, hash, null, custom. |
| RLS policy API | `POST /api/admin/security/rls-policies`, `GET ...`, `PUT ...`, `DELETE ...` |
| Masking policy API | `POST /api/admin/security/masking-policies`, `GET ...`, `PUT ...`, `DELETE ...` |
| Policy testing | `POST /api/admin/security/test-policy` -- dry-run a policy against a sample query |

### Day 18: JupyterLab + Airflow + MLflow Integration

| Task | Details |
|------|---------|
| JupyterHub authenticator | Custom JupyterHub authenticator that validates DataPond JWT. Package as pip-installable module. |
| Airflow forward-auth | Configure Traefik forward-auth middleware to validate DataPond JWT before forwarding to Airflow |
| Airflow security manager | Custom Flask-AppBuilder security manager that maps DataPond roles to Airflow roles |
| MLflow forward-auth | Same pattern as Airflow -- Traefik forward-auth |
| Polaris auth proxy | Backend validates DataPond RBAC before proxying requests to Polaris |

### Day 19: Admin UI

| Task | Details |
|------|---------|
| User management page | List users, create/edit/delete, assign roles, lock/unlock, reset password |
| Role management page | List roles, view permissions, create custom roles |
| IdP configuration page | Unified page for LDAP, SAML, OIDC configuration with test connectivity |
| Security policies page | RLS and column masking policy management with visual editor |
| Audit log viewer | Searchable, filterable audit log with export to CSV |
| Session manager | View active sessions, terminate sessions |

### Day 20: End-to-End Testing + Hardening

| Task | Details |
|------|---------|
| E2E test suite | Full end-to-end tests: login -> query with RLS -> masked columns -> audit trail |
| Penetration testing checklist | OWASP Top 10 verification, JWT attack vectors (none alg, key confusion), SAML signature wrapping, LDAP injection |
| Performance testing | Auth middleware latency (target: <5ms per request), rate limiter accuracy, Valkey session lookup latency |
| Documentation | Complete auth administration guide |
| Helm chart updates | Add all auth configuration to `values.yaml`, create Kubernetes Secrets templates |
| Production checklist | Change default admin password, configure TLS, set proper CORS origins, review password policy |

**Phase 4 deliverables:**
- Trino access control plugin with RBAC, RLS, column masking
- JupyterLab, Airflow, MLflow authenticated via DataPond
- Polaris catalog access controlled via DataPond RBAC
- Full admin UI for user/role/IdP/security management
- Audit log viewer
- E2E test suite
- Production hardening checklist

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| LDAP/AD schema variations across customers | Medium | High | Configurable attribute mapping, LDAP browser for discovery |
| SAML response format differences between IdPs | Medium | Medium | Use battle-tested `python3-saml` library, test against multiple IdPs |
| Trino plugin Java/Python boundary complexity | High | Medium | Keep plugin minimal; delegate to PostgreSQL for policy storage |
| Performance degradation from per-request auth checks | Medium | Low | JWT validation is CPU-only (no DB), RBAC cached in Valkey |
| Key rotation without downtime | Medium | Low | `kid`-based key selection, overlapping validity windows |

---

## Dependencies

| Dependency | Version | Purpose | License |
|------------|---------|---------|---------|
| `python-jose[cryptography]` | 3.3.0+ | JWT creation and validation | MIT |
| `passlib[bcrypt]` | 1.7.4+ | Password hashing with bcrypt | BSD |
| `pyotp` | 2.9.0+ | TOTP generation and verification | MIT |
| `ldap3` | 2.9.1+ | LDAP v3 client (pure Python) | LGPL-3.0 |
| `python3-saml` | 1.16.0+ | SAML 2.0 SP implementation | MIT |
| `authlib` | 1.3.0+ | OIDC/OAuth2 client | BSD-3-Clause |
| `qrcode[pil]` | 7.4+ | QR code generation for TOTP enrollment | BSD |
| `cryptography` | 41.0+ | AES-256-GCM encryption (already in requirements.txt) | Apache-2.0 / BSD |

All dependencies are compatible with air-gapped deployment (can be pip-installed from a local mirror or vendored).
