# DataPond Authentication & Authorization Architecture

## 1. Overview

DataPond requires a production-grade authentication and authorization system to serve regulated industries (financial services, healthcare, defense, public sector) that operate under strict data sovereignty mandates. This document specifies the complete auth architecture, including authentication flows, authorization model, session management, and integration points with every platform component.

**Design principles:**

1. **Air-gap first** -- Every auth mechanism must work without internet access. No dependency on external OAuth providers (Google, GitHub, Okta cloud) unless the customer explicitly configures one.
2. **Defense in depth** -- Multiple layers: TLS termination at ingress, JWT validation at the API gateway, per-endpoint RBAC checks, row/column-level security at the query engine.
3. **Auditable by default** -- Every authentication event, permission check, and administrative action is recorded in an append-only audit log.
4. **Standards-based** -- SAML 2.0, OIDC, LDAP v3, TOTP (RFC 6238), SCIM 2.0 (future).

---

## 2. System Architecture

```
                        ┌─────────────────────────────────────────┐
                        │            External IdPs                │
                        │  (AD/LDAP, SAML IdP, OIDC Provider)    │
                        └────────────────┬────────────────────────┘
                                         │
                                         ▼
┌──────────────┐    ┌──────────────────────────────────────────────────┐
│   Browser /  │    │                 Ingress (Traefik)                │
│   CLI / SDK  │───▶│  TLS termination · Rate limiting · CORS         │
└──────────────┘    └──────────────────────┬──────────────────────────┘
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────────┐
                    │              Auth Gateway Middleware              │
                    │  (FastAPI middleware in backend service)          │
                    │                                                  │
                    │  1. Extract JWT from Authorization header         │
                    │  2. Validate signature (RS256) + expiry           │
                    │  3. Check token not in revocation set (Valkey)    │
                    │  4. Attach user context to request                │
                    │  5. Enforce RBAC via permission decorator         │
                    └──────────────────────┬──────────────────────────┘
                                           │
                          ┌────────────────┼────────────────┐
                          ▼                ▼                ▼
                   ┌────────────┐  ┌────────────┐  ┌────────────────┐
                   │  Auth API  │  │ Platform   │  │ Data APIs      │
                   │  /api/auth │  │ APIs       │  │ /api/query     │
                   │            │  │ /api/svc   │  │ /api/catalog   │
                   └──────┬─────┘  └────────────┘  └────────────────┘
                          │
         ┌────────────────┼──────────────────┐
         ▼                ▼                  ▼
  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐
  │ PostgreSQL  │  │   Valkey    │  │  LDAP / SAML  │
  │ (users,     │  │ (sessions,  │  │  / OIDC       │
  │  roles,     │  │  token      │  │  (external    │
  │  audit_log) │  │  revocation,│  │   identity)   │
  └─────────────┘  │  rate limit)│  └───────────────┘
                   └─────────────┘
```

---

## 3. Authentication

### 3.1 Supported Methods

| Method | Use Case | Air-gap Compatible | Phase |
|--------|----------|--------------------|-------|
| Local (username + bcrypt password) | Dev, small teams, bootstrap admin | Yes | 1 |
| LDAP v3 / Active Directory | Enterprise on-prem | Yes | 2 |
| SAML 2.0 SSO | Enterprise SSO (ADFS, Shibboleth, Keycloak) | Yes (on-prem IdP) | 3 |
| OIDC (OpenID Connect) | Enterprise SSO (Keycloak, Dex, on-prem Okta) | Yes (on-prem IdP) | 3 |
| TOTP MFA (RFC 6238) | Second factor for any primary method | Yes | 3 |
| API Keys | Service-to-service, CLI, SDK | Yes | 1 |

### 3.2 Authentication Flows

#### 3.2.1 Local Authentication

```
Client                    Backend                 PostgreSQL      Valkey
  │                         │                         │              │
  │  POST /api/auth/login   │                         │              │
  │  {email, password}      │                         │              │
  │────────────────────────▶│                         │              │
  │                         │  SELECT user by email   │              │
  │                         │────────────────────────▶│              │
  │                         │  user row               │              │
  │                         │◀────────────────────────│              │
  │                         │                         │              │
  │                         │  bcrypt.verify(password, │              │
  │                         │    user.password_hash)   │              │
  │                         │                         │              │
  │                         │  [If MFA enabled]       │              │
  │  202 {mfa_challenge_id} │                         │              │
  │◀────────────────────────│  Store challenge ──────▶│──────────────│
  │                         │                         │              │
  │  POST /api/auth/mfa/verify                        │              │
  │  {challenge_id, code}   │                         │              │
  │────────────────────────▶│  Verify TOTP code       │              │
  │                         │                         │              │
  │                         │  [Auth success]         │              │
  │                         │  Generate JWT pair       │              │
  │                         │  Store session ─────────│──────────────│
  │                         │  Write audit_log ──────▶│              │
  │  200 {access_token,     │                         │              │
  │       refresh_token,    │                         │              │
  │       expires_in}       │                         │              │
  │◀────────────────────────│                         │              │
```

#### 3.2.2 LDAP / Active Directory

```
Client               Backend              LDAP/AD Server        PostgreSQL
  │                    │                        │                    │
  │ POST /api/auth/login                        │                    │
  │ {email, password,  │                        │                    │
  │  auth_method:"ldap"}                        │                    │
  │───────────────────▶│                        │                    │
  │                    │  LDAP bind (svc acct)  │                    │
  │                    │───────────────────────▶│                    │
  │                    │  Search user by email   │                    │
  │                    │───────────────────────▶│                    │
  │                    │  User DN returned       │                    │
  │                    │◀───────────────────────│                    │
  │                    │  LDAP bind (user DN +   │                    │
  │                    │    user password)        │                    │
  │                    │───────────────────────▶│                    │
  │                    │  Bind success           │                    │
  │                    │◀───────────────────────│                    │
  │                    │  Fetch group membership  │                    │
  │                    │───────────────────────▶│                    │
  │                    │  Groups returned         │                    │
  │                    │◀───────────────────────│                    │
  │                    │                        │                    │
  │                    │  Upsert user + map groups to roles ────────▶│
  │                    │  Generate JWT pair       │                    │
  │  200 {tokens}      │                        │                    │
  │◀───────────────────│                        │                    │
```

**LDAP group-to-role mapping** is configured in `ldap_group_mappings` table:

| LDAP Group DN | DataPond Role |
|---------------|---------------|
| `CN=DataPond-Admins,OU=Groups,...` | `admin` |
| `CN=Data-Engineers,OU=Groups,...` | `data_engineer` |
| `CN=Data-Scientists,OU=Groups,...` | `data_scientist` |
| `CN=Analysts,OU=Groups,...` | `business_analyst` |
| `CN=Domain Users,OU=Groups,...` | `viewer` |

#### 3.2.3 SAML 2.0 SSO

```
Client              Backend (SP)          SAML IdP (ADFS/Keycloak)
  │                    │                         │
  │ GET /api/auth/saml/login                     │
  │───────────────────▶│                         │
  │                    │  Generate AuthnRequest   │
  │  302 Redirect to IdP                         │
  │◀───────────────────│                         │
  │                    │                         │
  │  Redirect to IdP ─────────────────────────▶ │
  │                    │                         │  User authenticates
  │  POST /api/auth/saml/acs (Assertion Consumer)│  at IdP
  │◀───────────────────────────────────────────── │
  │───────────────────▶│                         │
  │                    │  Validate XML signature  │
  │                    │  Extract attributes       │
  │                    │  (email, name, groups)    │
  │                    │  Upsert user + map roles  │
  │                    │  Generate JWT pair         │
  │  302 Redirect to   │                         │
  │  frontend + tokens │                         │
  │◀───────────────────│                         │
```

**SP metadata** is served at `GET /api/auth/saml/metadata` for IdP configuration.

#### 3.2.4 OIDC (OpenID Connect)

```
Client              Backend (RP)           OIDC Provider (Keycloak/Dex)
  │                    │                         │
  │ GET /api/auth/oidc/login                     │
  │───────────────────▶│                         │
  │                    │  Build authorization URL  │
  │                    │  (with PKCE challenge)    │
  │  302 Redirect      │                         │
  │◀───────────────────│                         │
  │                    │                         │
  │  User authenticates at OIDC Provider ────────▶│
  │                    │                         │
  │  GET /api/auth/oidc/callback?code=...&state=...
  │───────────────────▶│                         │
  │                    │  Exchange code for tokens │
  │                    │───────────────────────▶  │
  │                    │  id_token + access_token  │
  │                    │◀───────────────────────  │
  │                    │  Validate id_token (JWT)  │
  │                    │  Extract claims            │
  │                    │  Upsert user + map roles   │
  │                    │  Generate DataPond JWT pair │
  │  302 Redirect to   │                         │
  │  frontend + tokens │                         │
  │◀───────────────────│                         │
```

**PKCE** (Proof Key for Code Exchange) is mandatory for all OIDC flows to prevent authorization code interception.

#### 3.2.5 API Key Authentication

For service-to-service communication and CLI/SDK access:

```
Client                    Backend                     Valkey
  │                         │                           │
  │  Any API request        │                           │
  │  X-API-Key: dp_live_... │                           │
  │────────────────────────▶│                           │
  │                         │  Hash key (SHA-256)       │
  │                         │  Lookup in cache ────────▶│
  │                         │  [miss] → PostgreSQL      │
  │                         │  Validate + get user ctx  │
  │                         │  Cache for 5 min ────────▶│
  │                         │                           │
  │  200 Response           │                           │
  │◀────────────────────────│                           │
```

API key format: `dp_live_<32-char-random>` (live) or `dp_test_<32-char-random>` (test/dev).
Only the SHA-256 hash is stored in the database -- the plaintext key is shown once at creation time.

---

## 4. Authorization (RBAC)

### 4.1 Role Hierarchy

```
admin
  ├── data_engineer
  │     ├── data_scientist
  │     │     └── business_analyst
  │     │           └── viewer
  │     └── business_analyst
  │           └── viewer
  └── (all permissions)
```

### 4.2 Default Roles and Permissions

| Permission | Admin | Data Engineer | Data Scientist | Business Analyst | Viewer |
|------------|:-----:|:-------------:|:--------------:|:----------------:|:------:|
| **Platform** | | | | | |
| Manage users & roles | X | | | | |
| Configure LDAP/SAML/OIDC | X | | | | |
| View audit logs | X | | | | |
| Manage platform settings | X | | | | |
| **Data Catalog** | | | | | |
| Create/drop catalogs | X | X | | | |
| Create/drop schemas | X | X | | | |
| Create/drop tables | X | X | | | |
| Alter tables | X | X | | | |
| View catalog metadata | X | X | X | X | X |
| **Query Engine** | | | | | |
| Execute DDL (CREATE/ALTER/DROP) | X | X | | | |
| Execute DML (INSERT/UPDATE/DELETE) | X | X | X | | |
| Execute SELECT queries | X | X | X | X | X |
| Kill other users' queries | X | X | | | |
| **Pipelines (Airflow)** | | | | | |
| Create/edit DAGs | X | X | | | |
| Trigger DAG runs | X | X | X | | |
| View DAG status/logs | X | X | X | X | X |
| **Notebooks (JupyterLab)** | | | | | |
| Create/edit notebooks | X | X | X | | |
| Execute notebooks | X | X | X | | |
| View shared notebooks | X | X | X | X | X |
| **ML (MLflow)** | | | | | |
| Create experiments | X | X | X | | |
| Register models | X | X | X | | |
| Deploy models | X | X | | | |
| View experiments/models | X | X | X | X | X |
| **Connectors** | | | | | |
| Create/edit connectors | X | X | | | |
| Delete connectors | X | | | | |
| View connector status | X | X | X | X | |
| **Streaming (RisingWave)** | | | | | |
| Create materialized views | X | X | | | |
| Create sources/sinks | X | X | | | |
| Query materialized views | X | X | X | X | X |

### 4.3 Custom Roles

Administrators can create custom roles by composing individual permissions:

```json
{
  "role_name": "senior_analyst",
  "description": "Analyst with DML privileges",
  "parent_role": "business_analyst",
  "additional_permissions": [
    "query:execute_dml",
    "pipeline:trigger"
  ]
}
```

### 4.4 Row-Level Security (RLS)

Row-level security is enforced at the query engine layer via Trino's system access control plugin and RisingWave's view-based isolation.

**Policy definition:**

```json
{
  "table": "iceberg.finance.transactions",
  "policy_name": "region_isolation",
  "filter_expression": "region = current_user_attribute('region')",
  "applies_to_roles": ["business_analyst", "viewer"],
  "exempt_roles": ["admin", "data_engineer"]
}
```

**Implementation path:**

1. Policies are stored in `rls_policies` table in PostgreSQL.
2. Backend injects a custom Trino system access control plugin that reads policies from PostgreSQL.
3. The plugin rewrites queries by appending WHERE clauses based on the authenticated user's attributes.
4. For RisingWave, we create per-role views with built-in WHERE filters.

### 4.5 Column-Level Masking

Sensitive columns (PII, financial data) are masked based on user role:

| Masking Type | Example Input | Masked Output | Use Case |
|--------------|---------------|---------------|----------|
| `full` | `John Smith` | `****` | Full redaction |
| `partial_email` | `john@acme.com` | `j***@acme.com` | Email PII |
| `partial_ssn` | `123-45-6789` | `***-**-6789` | SSN/ID numbers |
| `hash` | `John Smith` | `a8f5f167f...` | Pseudonymization |
| `null` | `any value` | `NULL` | Complete suppression |

**Policy definition:**

```json
{
  "table": "iceberg.hr.employees",
  "column": "salary",
  "masking_type": "full",
  "applies_to_roles": ["business_analyst", "viewer"],
  "exempt_roles": ["admin", "data_engineer"]
}
```

**Implementation:** Trino column masking functions applied in the system access control plugin. The plugin intercepts column references and wraps them in masking UDFs.

---

## 5. Token Architecture

### 5.1 JWT Token Design

**Algorithm:** RS256 (RSA 2048-bit asymmetric signing)

Rationale: Asymmetric signing allows downstream services (Trino, JupyterLab) to verify tokens using only the public key, without access to the signing key.

**Access Token (short-lived):**

```json
{
  "header": {
    "alg": "RS256",
    "typ": "JWT",
    "kid": "datapond-signing-key-2026-01"
  },
  "payload": {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "jane.doe@acme.com",
    "name": "Jane Doe",
    "roles": ["data_engineer"],
    "permissions": ["catalog:create", "query:execute_ddl", "query:execute_dml"],
    "attributes": {
      "department": "engineering",
      "region": "us-east"
    },
    "auth_method": "ldap",
    "session_id": "sess_abc123",
    "iat": 1714400000,
    "exp": 1714403600,
    "iss": "datapond",
    "aud": "datapond-api"
  }
}
```

**Access token TTL:** 1 hour (configurable: 15 min -- 24 hours)

**Refresh Token (long-lived):**

```json
{
  "payload": {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "session_id": "sess_abc123",
    "token_family": "fam_xyz789",
    "iat": 1714400000,
    "exp": 1715004800,
    "iss": "datapond",
    "aud": "datapond-refresh"
  }
}
```

**Refresh token TTL:** 7 days (configurable: 1 hour -- 90 days)

### 5.2 Token Rotation

Refresh tokens use **rotation with reuse detection**:

1. Each refresh token belongs to a `token_family`.
2. When a refresh token is used, a new access + refresh pair is issued and the old refresh token is invalidated.
3. If a previously-used (invalidated) refresh token is presented, the entire token family is revoked (indicating token theft).
4. Token family metadata is stored in Valkey with TTL matching the refresh token lifetime.

### 5.3 Token Revocation

Active revocation is performed via a **Valkey-based revocation set**:

- On logout or admin-initiated session kill, the token's `jti` (JWT ID) is added to a Valkey SET with TTL matching the token's remaining lifetime.
- The auth middleware checks the revocation set on every request.
- Valkey's in-memory nature ensures this check adds <1ms latency.

### 5.4 Key Management

- **Signing keys** are RSA 2048-bit key pairs stored as Kubernetes Secrets.
- **Key rotation** is supported via the `kid` (Key ID) header claim. Multiple active keys can coexist during rotation.
- Rotation procedure: generate new key pair -> deploy as new Secret -> update backend config to use new key for signing -> old key remains valid for verification until all existing tokens expire -> remove old key.

---

## 6. Session Management

### 6.1 Session Storage (Valkey)

```
Session key:    datapond:session:{session_id}
Session value:  {
  "user_id": "550e8400-...",
  "email": "jane.doe@acme.com",
  "roles": ["data_engineer"],
  "auth_method": "ldap",
  "ip_address": "10.0.1.50",
  "user_agent": "Mozilla/5.0 ...",
  "device_fingerprint": "fp_abc123",
  "created_at": "2026-04-29T10:00:00Z",
  "last_activity": "2026-04-29T11:30:00Z",
  "mfa_verified": true
}
TTL:            86400 (24 hours, configurable)
```

### 6.2 Concurrent Session Policy

| Policy | Description |
|--------|-------------|
| `unlimited` | No limit on concurrent sessions (default) |
| `per_device` | One session per device fingerprint |
| `single` | Only one active session at a time (strictest) |
| `max_n` | Maximum N concurrent sessions (configurable) |

When a new session exceeds the limit, the oldest session is forcefully terminated.

### 6.3 Session Timeout

| Timeout Type | Default | Configurable Range |
|--------------|---------|-------------------|
| Absolute timeout | 24 hours | 1 hour -- 30 days |
| Idle timeout | 2 hours | 15 min -- 24 hours |
| MFA re-verification | 12 hours | 1 hour -- 24 hours |

---

## 7. Integration with Platform Components

### 7.1 Apache Polaris (Catalog Permissions)

DataPond's RBAC maps to Polaris catalog privileges:

| DataPond Permission | Polaris Privilege |
|---------------------|-------------------|
| `catalog:create` | `CREATE_CATALOG` |
| `catalog:drop` | `DROP_CATALOG` |
| `schema:create` | `CREATE_NAMESPACE` |
| `table:create` | `CREATE_TABLE` |
| `table:select` | `TABLE_READ_DATA` |
| `table:write` | `TABLE_WRITE_DATA` |

**Implementation:** The backend acts as a Polaris auth proxy. When a user requests catalog operations, the backend validates the user's DataPond JWT, checks RBAC permissions, and forwards the request to Polaris using a service account token with the appropriate Polaris privileges.

### 7.2 Trino (Query Authorization)

Trino integration uses a **custom system access control plugin** (`datapond-trino-access-control`):

1. User authenticates to DataPond, receives JWT.
2. When submitting a query via `/api/query/execute`, the backend passes the user's identity and roles to Trino via `X-Trino-Extra-Credential` headers.
3. The Trino access control plugin reads these headers and enforces:
   - Table-level access based on role permissions
   - Row-level filtering based on RLS policies
   - Column masking based on masking policies
4. The plugin fetches policies from PostgreSQL (cached in Trino's memory with 60-second TTL).

### 7.3 JupyterLab (Notebook Access)

JupyterLab uses **JupyterHub** as the multi-user gateway:

1. User authenticates to DataPond.
2. Frontend redirects to JupyterHub with a short-lived, single-use auth token.
3. JupyterHub validates the token against the DataPond backend via a custom authenticator.
4. JupyterHub spawns a per-user notebook server with the user's identity injected as environment variables.
5. The notebook server can access only the Iceberg tables the user has permission to query (enforced by Trino/Polaris when queries are executed).

### 7.4 Airflow (Pipeline Execution)

1. Airflow webserver is placed behind DataPond's auth gateway (Traefik forward-auth).
2. Traefik validates the DataPond JWT before forwarding requests to Airflow.
3. Airflow's RBAC maps to DataPond roles via a custom Flask-AppBuilder security manager.
4. DAG-level permissions: Users can only see/trigger DAGs tagged with their allowed namespaces.

### 7.5 MLflow (Experiment Access)

1. MLflow is placed behind the auth gateway (same Traefik forward-auth pattern).
2. Experiment-level access: Users can only see experiments in their permitted namespaces.
3. Model registry: Only `data_engineer` and above can register models; only `admin` can promote to production stage.

### 7.6 RisingWave (Streaming)

1. RisingWave uses PostgreSQL wire protocol -- connections are authenticated via DataPond credentials.
2. The backend creates per-role database users in RisingWave with appropriate GRANT statements.
3. Materialized views are owned by the creating user; SELECT is granted to roles based on DataPond RBAC.

---

## 8. Security Considerations

### 8.1 Password Policy

| Requirement | Default | Configurable |
|-------------|---------|-------------|
| Minimum length | 12 characters | 8 -- 128 |
| Require uppercase | Yes | Yes/No |
| Require lowercase | Yes | Yes/No |
| Require digit | Yes | Yes/No |
| Require special character | Yes | Yes/No |
| Password history | Last 12 passwords | 0 -- 50 |
| Max age | 90 days | 30 -- 365 days |
| Account lockout threshold | 5 failed attempts | 3 -- 20 |
| Lockout duration | 30 minutes | 5 min -- 24 hours |

### 8.2 Cryptographic Standards

| Purpose | Algorithm | Notes |
|---------|-----------|-------|
| Password hashing | bcrypt (cost factor 12) | Adaptive: increases with hardware improvements |
| JWT signing | RS256 (RSA-2048) | Asymmetric for distributed verification |
| API key hashing | SHA-256 | Fast lookup, key entropy provides security |
| TOTP secrets | AES-256-GCM | Encrypted at rest in database |
| LDAP passwords (transit) | TLS 1.2+ (LDAPS) | Never transmit over plaintext LDAP |
| Session IDs | CSPRNG (32 bytes, base64url) | Unpredictable, sufficient entropy |

### 8.3 Rate Limiting

| Endpoint | Rate Limit | Window |
|----------|-----------|--------|
| `POST /api/auth/login` | 10 requests | Per minute, per IP |
| `POST /api/auth/mfa/verify` | 5 requests | Per minute, per user |
| `POST /api/auth/refresh` | 30 requests | Per minute, per user |
| `POST /api/auth/password/reset` | 3 requests | Per hour, per email |
| All other authenticated endpoints | 1000 requests | Per minute, per user |

Rate limit state is stored in Valkey using sliding window counters.

### 8.4 HTTPS Enforcement

- All auth endpoints MUST be accessed over HTTPS in production.
- The backend sets `Strict-Transport-Security` headers.
- JWT cookies (if used) have `Secure`, `HttpOnly`, and `SameSite=Strict` flags.
- In air-gapped environments, TLS certificates are managed via cert-manager with a private CA or manually provisioned certificates.

### 8.5 CORS Policy

Production CORS configuration replaces the current `allow_origins=["*"]`:

```python
allow_origins=[f"https://{DOMAIN}"]
allow_credentials=True
allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"]
```

### 8.6 Audit Logging

Every security-relevant event is written to the `auth_audit_log` table:

| Event Type | Details Captured |
|------------|-----------------|
| `login_success` | User, method, IP, user agent, MFA used |
| `login_failure` | Email attempted, method, IP, failure reason |
| `logout` | User, session ID |
| `token_refresh` | User, session ID, old/new token family |
| `mfa_enroll` | User, device name |
| `mfa_verify_success` | User, device |
| `mfa_verify_failure` | User, device, IP |
| `password_change` | User, initiated by (self or admin) |
| `role_change` | Target user, old roles, new roles, changed by |
| `permission_denied` | User, resource, action attempted |
| `session_terminated` | User, session ID, terminated by |
| `account_locked` | User, reason, IP of last attempt |
| `api_key_created` | User, key prefix, permissions |
| `api_key_revoked` | User, key prefix, revoked by |

Audit logs are append-only (no UPDATE/DELETE allowed via application code). Retention: configurable, default 2 years.

---

## 9. Configuration

All auth configuration is managed via environment variables and Helm values:

```yaml
# values.yaml auth section
backend:
  auth:
    # JWT Configuration
    jwt_algorithm: RS256
    access_token_ttl: 3600          # seconds
    refresh_token_ttl: 604800       # seconds
    signing_key_secret: datapond-jwt-signing-key

    # Session Configuration
    session_ttl: 86400              # seconds
    idle_timeout: 7200              # seconds
    concurrent_session_policy: unlimited  # unlimited|single|per_device|max_n
    max_concurrent_sessions: 5

    # Password Policy
    password_min_length: 12
    password_require_uppercase: true
    password_require_lowercase: true
    password_require_digit: true
    password_require_special: true
    password_history_count: 12
    password_max_age_days: 90
    account_lockout_threshold: 5
    account_lockout_duration: 1800  # seconds

    # LDAP Configuration (optional)
    ldap:
      enabled: false
      url: ldaps://ad.example.com:636
      bind_dn: CN=datapond-svc,OU=Service Accounts,DC=example,DC=com
      bind_password_secret: datapond-ldap-bind
      base_dn: DC=example,DC=com
      user_search_filter: "(&(objectClass=person)(mail={email}))"
      group_search_filter: "(&(objectClass=group)(member={user_dn}))"
      tls_verify: true
      tls_ca_cert_secret: ldap-ca-cert

    # SAML Configuration (optional)
    saml:
      enabled: false
      idp_metadata_url: ""          # or idp_metadata_xml for air-gap
      idp_metadata_xml_secret: ""
      sp_entity_id: "datapond"
      sp_acs_url: "https://datapond.local/api/auth/saml/acs"
      sp_cert_secret: datapond-saml-sp
      attribute_mapping:
        email: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
        name: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
        groups: "http://schemas.xmlsoap.org/claims/Group"

    # OIDC Configuration (optional)
    oidc:
      enabled: false
      issuer_url: "https://keycloak.example.com/realms/datapond"
      client_id: "datapond"
      client_secret_secret: datapond-oidc-client
      scopes: ["openid", "profile", "email", "groups"]
      claim_mapping:
        email: "email"
        name: "name"
        groups: "groups"

    # MFA Configuration
    mfa:
      enabled: false                 # Global toggle
      required_for_roles: ["admin"]  # Force MFA for specific roles
      totp_issuer: "DataPond"
      totp_digits: 6
      totp_period: 30
```

---

## 10. High Availability

### 10.1 Stateless Backend

The FastAPI backend is stateless with respect to auth:
- All session state is in Valkey (replicated).
- All persistent data is in PostgreSQL (with HA replication).
- JWT validation uses cached public keys (no DB hit for most requests).

This means the backend can be horizontally scaled to any number of replicas with zero auth-related coordination.

### 10.2 Valkey HA

For production, Valkey should run in Sentinel or Cluster mode:
- Session data is replicated across 3 nodes.
- If the primary fails, Sentinel promotes a replica within seconds.
- Token revocation sets are replicated, so revoked tokens remain revoked during failover.

### 10.3 PostgreSQL HA

Auth tables (users, roles, audit logs) are in the shared PostgreSQL instance:
- Streaming replication with synchronous commit for auth writes.
- Read replicas can serve permission lookups.

---

## 11. Future Considerations

| Feature | Priority | Notes |
|---------|----------|-------|
| SCIM 2.0 provisioning | High | Auto-provision/deprovision users from IdP |
| WebAuthn / FIDO2 | Medium | Hardware security key support |
| Attribute-Based Access Control (ABAC) | Medium | More flexible than pure RBAC |
| OAuth 2.0 token exchange | Low | For service mesh scenarios |
| Certificate-based auth (mTLS) | Low | For service-to-service in high-security environments |
| Kerberos / SPNEGO | Medium | For environments with existing Kerberos infrastructure |
