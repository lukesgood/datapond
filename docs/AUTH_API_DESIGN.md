# DataPond Auth API Design

Complete endpoint specifications for the authentication and authorization system. All endpoints are prefixed with `/api`.

---

## 1. Authentication Endpoints

### POST /api/auth/login

Authenticate a user and return JWT tokens.

**Request:**
```json
{
  "email": "jane.doe@acme.com",
  "password": "SecureP@ss123",
  "auth_method": "local"
}
```

`auth_method` is optional. If omitted, the backend tries `local` first, then each configured IdP in priority order. Explicit values: `"local"`, `"ldap"`.

**Response (200 -- success, no MFA):**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "jane.doe@acme.com",
    "display_name": "Jane Doe",
    "roles": ["data_engineer"],
    "auth_method": "local",
    "mfa_enabled": false
  }
}
```

**Response (202 -- MFA required):**
```json
{
  "mfa_required": true,
  "mfa_challenge_id": "chal_abc123def456",
  "mfa_methods": ["totp"],
  "expires_in": 300
}
```

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"detail": "Email and password are required"}` | Missing fields |
| 401 | `{"detail": "Invalid email or password"}` | Bad credentials |
| 403 | `{"detail": "Account is locked. Try again after 2026-04-29T12:00:00Z"}` | Account locked |
| 403 | `{"detail": "Account is inactive"}` | Deactivated user |
| 403 | `{"detail": "Password expired. Please change your password."}` | Password past max age |
| 429 | `{"detail": "Too many login attempts. Try again in 45 seconds."}` | Rate limited |

---

### POST /api/auth/logout

Revoke the current session and tokens.

**Headers:** `Authorization: Bearer <access_token>`

**Request:** Empty body or:
```json
{
  "all_sessions": false
}
```

If `all_sessions` is `true`, all sessions for the user are terminated.

**Response (200):**
```json
{
  "message": "Logged out successfully"
}
```

---

### POST /api/auth/refresh

Exchange a refresh token for a new token pair. Implements rotation with reuse detection.

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJSUzI1NiIs..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 401 | `{"detail": "Invalid or expired refresh token"}` | Token invalid |
| 401 | `{"detail": "Token reuse detected. All sessions revoked."}` | Replay attack -- entire token family revoked |

---

### GET /api/auth/me

Return the authenticated user's profile, roles, and permissions.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "jane.doe@acme.com",
  "username": "jane.doe",
  "display_name": "Jane Doe",
  "auth_method": "ldap",
  "status": "active",
  "mfa_enabled": true,
  "roles": [
    {
      "id": "role-uuid",
      "name": "data_engineer",
      "display_name": "Data Engineer"
    }
  ],
  "permissions": [
    "catalog:create",
    "catalog:drop",
    "catalog:read",
    "query:execute_ddl",
    "query:execute_dml",
    "query:execute_select"
  ],
  "attributes": {
    "department": "engineering",
    "region": "us-east"
  },
  "last_login_at": "2026-04-29T10:00:00Z",
  "password_expires_at": "2026-07-28T10:00:00Z"
}
```

---

### POST /api/auth/password/change

Change the current user's password (self-service).

**Headers:** `Authorization: Bearer <access_token>`

**Request:**
```json
{
  "current_password": "OldP@ss123",
  "new_password": "NewSecureP@ss456"
}
```

**Response (200):**
```json
{
  "message": "Password changed successfully"
}
```

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"detail": "New password does not meet policy", "requirements": {"min_length": 12, ...}}` | Policy violation |
| 400 | `{"detail": "Password was used recently"}` | Password in history |
| 401 | `{"detail": "Current password is incorrect"}` | Wrong current password |
| 403 | `{"detail": "Password change not allowed for SSO users"}` | LDAP/SAML/OIDC user |

---

## 2. MFA Endpoints

### POST /api/auth/mfa/enroll

Begin TOTP MFA enrollment. Returns a TOTP secret and QR code URI.

**Headers:** `Authorization: Bearer <access_token>`

**Request:**
```json
{
  "device_name": "Work Phone"
}
```

**Response (200):**
```json
{
  "device_id": "mfa-device-uuid",
  "totp_uri": "otpauth://totp/DataPond:jane.doe@acme.com?secret=JBSWY3DPEHPK3PXP&issuer=DataPond&digits=6&period=30",
  "secret": "JBSWY3DPEHPK3PXP",
  "qr_code_base64": "data:image/png;base64,iVBOR...",
  "recovery_codes": [
    "A1B2C3D4E5",
    "F6G7H8I9J0",
    "K1L2M3N4O5",
    "P6Q7R8S9T0",
    "U1V2W3X4Y5",
    "Z6A7B8C9D0",
    "E1F2G3H4I5",
    "J6K7L8M9N0",
    "O1P2Q3R4S5",
    "T6U7V8W9X0"
  ]
}
```

**Important:** Recovery codes are shown exactly once. The user must save them. They are stored as bcrypt hashes.

---

### POST /api/auth/mfa/enroll/verify

Confirm MFA enrollment by providing a valid TOTP code. This activates the MFA device.

**Headers:** `Authorization: Bearer <access_token>`

**Request:**
```json
{
  "device_id": "mfa-device-uuid",
  "code": "123456"
}
```

**Response (200):**
```json
{
  "message": "MFA device activated successfully",
  "mfa_enabled": true
}
```

---

### POST /api/auth/mfa/verify

Verify MFA during login (after receiving a `202` response from `/api/auth/login`).

**Request (no auth header -- uses challenge ID):**
```json
{
  "mfa_challenge_id": "chal_abc123def456",
  "code": "123456"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "user": { ... }
}
```

**Error responses:**

| Status | Body | Condition |
|--------|------|-----------|
| 400 | `{"detail": "Invalid or expired MFA challenge"}` | Challenge expired (5 min TTL) |
| 401 | `{"detail": "Invalid MFA code"}` | Wrong TOTP code |
| 429 | `{"detail": "Too many MFA attempts"}` | Rate limited (5/min) |

---

### POST /api/auth/mfa/recovery

Use a recovery code when TOTP device is unavailable.

**Request (no auth header -- uses challenge ID):**
```json
{
  "mfa_challenge_id": "chal_abc123def456",
  "recovery_code": "A1B2C3D4E5"
}
```

**Response (200):** Same as `/api/auth/mfa/verify`. The used recovery code is invalidated.

---

### GET /api/auth/mfa/devices

List the current user's MFA devices.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "devices": [
    {
      "id": "mfa-device-uuid",
      "device_name": "Work Phone",
      "device_type": "totp",
      "status": "active",
      "created_at": "2026-04-29T10:00:00Z",
      "last_used_at": "2026-04-29T11:30:00Z"
    }
  ],
  "recovery_codes_remaining": 8
}
```

---

### DELETE /api/auth/mfa/devices/{device_id}

Remove an MFA device. If it is the user's only device, MFA is disabled on the account.

**Headers:** `Authorization: Bearer <access_token>`

**Request:**
```json
{
  "current_password": "SecureP@ss123"
}
```

Password confirmation is required for MFA device removal.

**Response (200):**
```json
{
  "message": "MFA device removed",
  "mfa_enabled": false
}
```

---

## 3. API Key Endpoints

### POST /api/auth/api-keys

Create a new API key for the current user.

**Headers:** `Authorization: Bearer <access_token>`

**Request:**
```json
{
  "name": "CI Pipeline Key",
  "scopes": ["query:execute_select", "catalog:read"],
  "expires_in_days": 90
}
```

`scopes` restricts the key to a subset of the user's permissions. If empty, inherits all user permissions. `expires_in_days` is optional (null = no expiry).

**Response (201):**
```json
{
  "id": "api-key-uuid",
  "name": "CI Pipeline Key",
  "key": "dp_live_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "key_prefix": "dp_live_a1",
  "scopes": ["query:execute_select", "catalog:read"],
  "expires_at": "2026-07-28T10:00:00Z",
  "created_at": "2026-04-29T10:00:00Z"
}
```

**Important:** The full `key` value is returned exactly once. It cannot be retrieved again.

---

### GET /api/auth/api-keys

List the current user's API keys.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "api_keys": [
    {
      "id": "api-key-uuid",
      "name": "CI Pipeline Key",
      "key_prefix": "dp_live_a1",
      "scopes": ["query:execute_select", "catalog:read"],
      "status": "active",
      "expires_at": "2026-07-28T10:00:00Z",
      "last_used_at": "2026-04-29T11:00:00Z",
      "last_used_ip": "10.0.1.50",
      "created_at": "2026-04-29T10:00:00Z"
    }
  ]
}
```

---

### DELETE /api/auth/api-keys/{key_id}

Revoke an API key.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "message": "API key revoked"
}
```

---

## 4. Session Endpoints

### GET /api/auth/sessions

List the current user's active sessions.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "sessions": [
    {
      "id": "sess_abc123",
      "ip_address": "10.0.1.50",
      "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
      "auth_method": "ldap",
      "mfa_verified": true,
      "created_at": "2026-04-29T10:00:00Z",
      "last_activity_at": "2026-04-29T11:30:00Z",
      "is_current": true
    },
    {
      "id": "sess_def456",
      "ip_address": "10.0.2.100",
      "user_agent": "DataPond CLI v1.0",
      "auth_method": "local",
      "mfa_verified": false,
      "created_at": "2026-04-28T09:00:00Z",
      "last_activity_at": "2026-04-28T17:00:00Z",
      "is_current": false
    }
  ]
}
```

---

### DELETE /api/auth/sessions/{session_id}

Terminate a specific session.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "message": "Session terminated"
}
```

---

## 5. SSO Endpoints

### GET /api/auth/saml/login?config_id={id}

Initiate SAML SSO login. Redirects the browser to the IdP.

**Response (302):** Redirect to SAML IdP with AuthnRequest.

---

### POST /api/auth/saml/acs

SAML Assertion Consumer Service. Receives the SAML response from the IdP.

**Request:** `application/x-www-form-urlencoded` with `SAMLResponse` and `RelayState` fields (standard SAML POST binding).

**Response (302):** Redirect to frontend with tokens:
```
https://datapond.local/auth/callback?access_token=...&refresh_token=...&expires_in=3600
```

---

### GET /api/auth/saml/metadata

Serve the SP metadata XML for IdP registration.

**Response (200, `application/xml`):**
```xml
<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="datapond">
  <md:SPSSODescriptor ...>
    <md:AssertionConsumerService
      Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
      Location="https://datapond.local/api/auth/saml/acs" />
  </md:SPSSODescriptor>
</md:EntityDescriptor>
```

---

### GET /api/auth/oidc/login?config_id={id}

Initiate OIDC login. Redirects the browser to the OIDC provider's authorization endpoint.

**Response (302):** Redirect to OIDC provider with:
- `response_type=code`
- `client_id=datapond`
- `redirect_uri=https://datapond.local/api/auth/oidc/callback`
- `scope=openid profile email groups`
- `state=<random>`
- `code_challenge=<S256 challenge>` (PKCE)

---

### GET /api/auth/oidc/callback

OIDC callback endpoint. Exchanges the authorization code for tokens.

**Query params:** `code`, `state`

**Response (302):** Redirect to frontend with DataPond tokens (same pattern as SAML ACS).

---

### GET /api/auth/sso/providers

List available SSO providers for the login page.

**No authentication required.**

**Response (200):**
```json
{
  "providers": [
    {
      "id": "saml-config-uuid",
      "type": "saml",
      "name": "Corporate ADFS",
      "login_url": "/api/auth/saml/login?config_id=saml-config-uuid"
    },
    {
      "id": "oidc-config-uuid",
      "type": "oidc",
      "name": "Keycloak SSO",
      "login_url": "/api/auth/oidc/login?config_id=oidc-config-uuid"
    }
  ],
  "local_auth_enabled": true,
  "ldap_auth_enabled": true
}
```

---

## 6. Admin: User Management

All admin endpoints require the `admin:manage_users` permission.

### GET /api/admin/users

List all users with pagination, filtering, and sorting.

**Headers:** `Authorization: Bearer <access_token>`

**Query params:**
- `page` (default: 1)
- `page_size` (default: 50, max: 200)
- `search` (searches email, username, display_name)
- `status` (filter: `active`, `inactive`, `locked`, `pending_activation`)
- `role` (filter by role name)
- `auth_method` (filter: `local`, `ldap`, `saml`, `oidc`)
- `sort_by` (default: `created_at`)
- `sort_order` (default: `desc`)

**Response (200):**
```json
{
  "users": [
    {
      "id": "user-uuid",
      "email": "jane.doe@acme.com",
      "username": "jane.doe",
      "display_name": "Jane Doe",
      "auth_method": "ldap",
      "status": "active",
      "mfa_enabled": true,
      "roles": [
        {"id": "role-uuid", "name": "data_engineer", "display_name": "Data Engineer"}
      ],
      "last_login_at": "2026-04-29T10:00:00Z",
      "created_at": "2026-01-15T08:00:00Z"
    }
  ],
  "total": 142,
  "page": 1,
  "page_size": 50,
  "total_pages": 3
}
```

---

### POST /api/admin/users

Create a new local user.

**Request:**
```json
{
  "email": "new.user@acme.com",
  "username": "new.user",
  "display_name": "New User",
  "password": "InitialP@ss123",
  "roles": ["business_analyst"],
  "attributes": {
    "department": "finance",
    "region": "eu-west"
  },
  "require_password_change": true
}
```

**Response (201):**
```json
{
  "id": "new-user-uuid",
  "email": "new.user@acme.com",
  "username": "new.user",
  "display_name": "New User",
  "status": "active",
  "roles": [{"id": "role-uuid", "name": "business_analyst", "display_name": "Business Analyst"}],
  "created_at": "2026-04-29T10:00:00Z"
}
```

---

### GET /api/admin/users/{user_id}

Get detailed user information.

**Response (200):**
```json
{
  "id": "user-uuid",
  "email": "jane.doe@acme.com",
  "username": "jane.doe",
  "display_name": "Jane Doe",
  "auth_method": "ldap",
  "external_provider": "corporate-ad",
  "external_id": "CN=Jane Doe,OU=Users,DC=acme,DC=com",
  "status": "active",
  "mfa_enabled": true,
  "roles": [...],
  "attributes": {"department": "engineering", "region": "us-east"},
  "last_login_at": "2026-04-29T10:00:00Z",
  "password_changed_at": "2026-03-15T10:00:00Z",
  "failed_login_count": 0,
  "created_at": "2026-01-15T08:00:00Z",
  "updated_at": "2026-04-29T10:00:00Z"
}
```

---

### PUT /api/admin/users/{user_id}

Update user profile and attributes.

**Request:**
```json
{
  "display_name": "Jane M. Doe",
  "status": "active",
  "attributes": {
    "department": "engineering",
    "region": "us-west"
  }
}
```

**Response (200):** Updated user object.

---

### DELETE /api/admin/users/{user_id}

Deactivate a user (soft delete). Sets status to `inactive`, terminates all sessions.

**Response (200):**
```json
{
  "message": "User deactivated",
  "sessions_terminated": 3
}
```

---

### POST /api/admin/users/{user_id}/roles

Assign a role to a user.

**Request:**
```json
{
  "role_id": "role-uuid",
  "expires_at": "2026-12-31T23:59:59Z"
}
```

`expires_at` is optional. Useful for temporary elevated access.

**Response (200):**
```json
{
  "message": "Role assigned",
  "user_id": "user-uuid",
  "role": {"id": "role-uuid", "name": "data_engineer"},
  "expires_at": "2026-12-31T23:59:59Z"
}
```

---

### DELETE /api/admin/users/{user_id}/roles/{role_id}

Remove a role from a user.

**Response (200):**
```json
{
  "message": "Role removed"
}
```

---

### POST /api/admin/users/{user_id}/unlock

Unlock a locked account.

**Response (200):**
```json
{
  "message": "Account unlocked",
  "failed_login_count_reset": true
}
```

---

### POST /api/admin/users/{user_id}/password/reset

Admin-initiated password reset. Generates a temporary password.

**Response (200):**
```json
{
  "temporary_password": "TempP@ss789xyz",
  "message": "User must change password on next login"
}
```

---

## 7. Admin: Role Management

Requires `admin:manage_roles` permission.

### GET /api/admin/roles

List all roles with their permissions.

**Response (200):**
```json
{
  "roles": [
    {
      "id": "role-uuid",
      "name": "data_engineer",
      "display_name": "Data Engineer",
      "description": "Create and manage data pipelines...",
      "is_system": true,
      "user_count": 23,
      "permissions": [
        {"resource": "catalog", "action": "create"},
        {"resource": "catalog", "action": "drop"},
        {"resource": "query", "action": "execute_ddl"}
      ]
    }
  ]
}
```

---

### POST /api/admin/roles

Create a custom role.

**Request:**
```json
{
  "name": "senior_analyst",
  "display_name": "Senior Analyst",
  "description": "Analyst with DML and pipeline trigger privileges",
  "parent_role_id": "business-analyst-role-uuid",
  "permissions": [
    {"resource": "query", "action": "execute_dml"},
    {"resource": "pipeline", "action": "trigger"},
    {"resource": "catalog", "action": "read"},
    {"resource": "table", "action": "read"},
    {"resource": "query", "action": "execute_select"},
    {"resource": "query", "action": "kill_own"},
    {"resource": "pipeline", "action": "view"},
    {"resource": "notebook", "action": "view"},
    {"resource": "ml", "action": "view"},
    {"resource": "streaming", "action": "query"}
  ]
}
```

**Response (201):** Created role object.

---

### PUT /api/admin/roles/{role_id}

Update a custom role. System roles (`is_system=true`) cannot have their name changed but permissions can be modified.

**Response (200):** Updated role object.

---

### DELETE /api/admin/roles/{role_id}

Delete a custom role. System roles cannot be deleted. Users assigned this role will lose it.

**Response (200):**
```json
{
  "message": "Role deleted",
  "affected_users": 5
}
```

---

## 8. Admin: Identity Provider Configuration

Requires `admin:manage_idp` permission.

### LDAP

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/idp/ldap` | List all LDAP configurations |
| POST | `/api/admin/idp/ldap` | Create LDAP configuration |
| GET | `/api/admin/idp/ldap/{id}` | Get LDAP configuration details |
| PUT | `/api/admin/idp/ldap/{id}` | Update LDAP configuration |
| DELETE | `/api/admin/idp/ldap/{id}` | Delete LDAP configuration |
| POST | `/api/admin/idp/ldap/{id}/test` | Test LDAP connectivity and bind |
| GET | `/api/admin/idp/ldap/{id}/browse` | Browse LDAP directory tree |
| GET | `/api/admin/idp/ldap/{id}/group-mappings` | List group-to-role mappings |
| POST | `/api/admin/idp/ldap/{id}/group-mappings` | Create group-to-role mapping |
| DELETE | `/api/admin/idp/ldap/{id}/group-mappings/{mapping_id}` | Delete mapping |

**POST /api/admin/idp/ldap request example:**
```json
{
  "name": "Corporate Active Directory",
  "url": "ldaps://ad.acme.com:636",
  "bind_dn": "CN=datapond-svc,OU=Service Accounts,DC=acme,DC=com",
  "bind_password": "ServiceAccountP@ss",
  "base_dn": "DC=acme,DC=com",
  "user_search_filter": "(&(objectClass=person)(mail={email}))",
  "username_attribute": "sAMAccountName",
  "email_attribute": "mail",
  "display_name_attribute": "displayName",
  "group_search_filter": "(&(objectClass=group)(member={user_dn}))",
  "tls_verify": true,
  "tls_ca_cert": "-----BEGIN CERTIFICATE-----\nMIID...\n-----END CERTIFICATE-----",
  "sync_groups_on_login": true
}
```

**POST /api/admin/idp/ldap/{id}/test response:**
```json
{
  "status": "success",
  "connection_time_ms": 45,
  "bind_successful": true,
  "user_search_count": 1247,
  "group_search_count": 89,
  "tls_info": {
    "protocol": "TLSv1.3",
    "cipher": "TLS_AES_256_GCM_SHA384"
  }
}
```

### SAML

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/idp/saml` | List SAML configurations |
| POST | `/api/admin/idp/saml` | Create SAML configuration |
| GET | `/api/admin/idp/saml/{id}` | Get SAML configuration |
| PUT | `/api/admin/idp/saml/{id}` | Update SAML configuration |
| DELETE | `/api/admin/idp/saml/{id}` | Delete SAML configuration |
| GET | `/api/admin/idp/saml/{id}/group-mappings` | List group mappings |
| POST | `/api/admin/idp/saml/{id}/group-mappings` | Create group mapping |
| DELETE | `/api/admin/idp/saml/{id}/group-mappings/{mapping_id}` | Delete mapping |

### OIDC

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/idp/oidc` | List OIDC configurations |
| POST | `/api/admin/idp/oidc` | Create OIDC configuration |
| GET | `/api/admin/idp/oidc/{id}` | Get OIDC configuration |
| PUT | `/api/admin/idp/oidc/{id}` | Update OIDC configuration |
| DELETE | `/api/admin/idp/oidc/{id}` | Delete OIDC configuration |
| POST | `/api/admin/idp/oidc/{id}/test` | Test OIDC discovery and connectivity |
| GET | `/api/admin/idp/oidc/{id}/group-mappings` | List group mappings |
| POST | `/api/admin/idp/oidc/{id}/group-mappings` | Create group mapping |
| DELETE | `/api/admin/idp/oidc/{id}/group-mappings/{mapping_id}` | Delete mapping |

---

## 9. Admin: Security Policies

Requires `security:manage_rls` or `security:manage_masking` permission.

### Row-Level Security

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/security/rls-policies` | List RLS policies |
| POST | `/api/admin/security/rls-policies` | Create RLS policy |
| GET | `/api/admin/security/rls-policies/{id}` | Get policy detail |
| PUT | `/api/admin/security/rls-policies/{id}` | Update policy |
| DELETE | `/api/admin/security/rls-policies/{id}` | Delete policy |

**POST /api/admin/security/rls-policies request:**
```json
{
  "name": "region_isolation",
  "description": "Users can only see data from their assigned region",
  "catalog_name": "iceberg",
  "schema_name": "finance",
  "table_name": "transactions",
  "filter_expression": "region = current_user_attribute('region')",
  "role_assignments": [
    {"role_id": "business-analyst-role-uuid", "is_exempt": false},
    {"role_id": "viewer-role-uuid", "is_exempt": false},
    {"role_id": "admin-role-uuid", "is_exempt": true}
  ]
}
```

### Column Masking

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/security/masking-policies` | List masking policies |
| POST | `/api/admin/security/masking-policies` | Create masking policy |
| GET | `/api/admin/security/masking-policies/{id}` | Get policy detail |
| PUT | `/api/admin/security/masking-policies/{id}` | Update policy |
| DELETE | `/api/admin/security/masking-policies/{id}` | Delete policy |

**POST /api/admin/security/masking-policies request:**
```json
{
  "name": "mask_salary",
  "catalog_name": "iceberg",
  "schema_name": "hr",
  "table_name": "employees",
  "column_name": "salary",
  "masking_type": "full",
  "role_assignments": [
    {"role_id": "business-analyst-role-uuid", "is_exempt": false},
    {"role_id": "viewer-role-uuid", "is_exempt": false},
    {"role_id": "data-engineer-role-uuid", "is_exempt": true}
  ]
}
```

---

## 10. Admin: Audit Log

Requires `admin:view_audit_log` permission.

### GET /api/admin/audit-log

Query the audit log with filtering and pagination.

**Query params:**
- `page`, `page_size`
- `event_type` (filter by event type)
- `user_id` (filter by user)
- `ip_address` (filter by IP)
- `start_date`, `end_date` (time range)
- `result` (`success` or `failure`)
- `search` (full-text search in details)

**Response (200):**
```json
{
  "events": [
    {
      "id": "event-uuid",
      "event_type": "login_success",
      "user_id": "user-uuid",
      "user_email": "jane.doe@acme.com",
      "ip_address": "10.0.1.50",
      "user_agent": "Mozilla/5.0...",
      "result": "success",
      "details": {
        "auth_method": "ldap",
        "mfa_used": true,
        "session_id": "sess_abc123"
      },
      "created_at": "2026-04-29T10:00:00Z"
    }
  ],
  "total": 15420,
  "page": 1,
  "page_size": 50,
  "total_pages": 309
}
```

### GET /api/admin/audit-log/export

Export audit log as CSV (streaming download).

**Query params:** Same filters as `GET /api/admin/audit-log`.

**Response (200, `text/csv`):** Streaming CSV download.

---

## 11. Admin: Session Management

Requires `admin:manage_sessions` permission.

### GET /api/admin/sessions

List all active sessions across all users.

**Query params:**
- `page`, `page_size`
- `user_id` (filter by user)
- `auth_method` (filter)

**Response (200):**
```json
{
  "sessions": [
    {
      "id": "sess_abc123",
      "user_id": "user-uuid",
      "user_email": "jane.doe@acme.com",
      "ip_address": "10.0.1.50",
      "auth_method": "ldap",
      "mfa_verified": true,
      "created_at": "2026-04-29T10:00:00Z",
      "last_activity_at": "2026-04-29T11:30:00Z"
    }
  ],
  "total": 47,
  "page": 1,
  "page_size": 50
}
```

### DELETE /api/admin/sessions/{session_id}

Admin-terminate any session.

**Response (200):**
```json
{
  "message": "Session terminated",
  "user_id": "user-uuid",
  "user_email": "jane.doe@acme.com"
}
```

---

## 12. Admin: Platform Auth Settings

Requires `admin:manage_settings` permission.

### GET /api/admin/settings/auth

Get all auth-related platform settings.

**Response (200):**
```json
{
  "jwt": {
    "access_token_ttl": 3600,
    "refresh_token_ttl": 604800,
    "algorithm": "RS256"
  },
  "session": {
    "absolute_timeout": 86400,
    "idle_timeout": 7200,
    "concurrent_policy": "unlimited",
    "max_concurrent": 5
  },
  "password_policy": {
    "min_length": 12,
    "require_uppercase": true,
    "require_lowercase": true,
    "require_digit": true,
    "require_special": true,
    "history_count": 12,
    "max_age_days": 90
  },
  "lockout": {
    "threshold": 5,
    "duration_seconds": 1800
  },
  "mfa": {
    "enabled": false,
    "required_for_roles": ["admin"]
  },
  "local_auth_enabled": true
}
```

### PUT /api/admin/settings/auth

Update auth settings. Only provided fields are updated.

**Request:**
```json
{
  "password_policy": {
    "min_length": 16,
    "max_age_days": 60
  },
  "mfa": {
    "enabled": true,
    "required_for_roles": ["admin", "data_engineer"]
  }
}
```

**Response (200):** Updated settings object.

---

## 13. Error Response Format

All auth endpoints use a consistent error format:

```json
{
  "detail": "Human-readable error message",
  "error_code": "AUTH_INVALID_CREDENTIALS",
  "timestamp": "2026-04-29T10:00:00Z",
  "request_id": "req_abc123"
}
```

**Error codes:**

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `AUTH_INVALID_CREDENTIALS` | 401 | Wrong email/password |
| `AUTH_ACCOUNT_LOCKED` | 403 | Account locked due to failed attempts |
| `AUTH_ACCOUNT_INACTIVE` | 403 | Account deactivated |
| `AUTH_PASSWORD_EXPIRED` | 403 | Password past max age |
| `AUTH_MFA_REQUIRED` | 202 | MFA verification needed |
| `AUTH_MFA_INVALID` | 401 | Invalid MFA code |
| `AUTH_MFA_CHALLENGE_EXPIRED` | 400 | MFA challenge timed out |
| `AUTH_TOKEN_EXPIRED` | 401 | Access token expired |
| `AUTH_TOKEN_INVALID` | 401 | Malformed or tampered token |
| `AUTH_TOKEN_REVOKED` | 401 | Token was explicitly revoked |
| `AUTH_REFRESH_REUSE` | 401 | Refresh token reuse detected |
| `AUTH_INSUFFICIENT_PERMISSION` | 403 | RBAC check failed |
| `AUTH_RATE_LIMITED` | 429 | Too many requests |
| `AUTH_SSO_ERROR` | 502 | IdP communication failure |
| `AUTH_LDAP_BIND_FAILED` | 502 | Cannot connect to LDAP server |
| `AUTH_PASSWORD_POLICY` | 400 | Password does not meet policy |
| `AUTH_PASSWORD_HISTORY` | 400 | Password was recently used |

---

## 14. Authentication Header Formats

The API accepts authentication via two mechanisms (checked in order):

1. **JWT Bearer token:**
   ```
   Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
   ```

2. **API Key:**
   ```
   X-API-Key: dp_live_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
   ```

If both are present, the JWT Bearer token takes precedence.

---

## 15. Public Endpoints (No Auth Required)

The following endpoints do not require authentication:

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Root / health |
| `GET /api/health` | Health check |
| `POST /api/auth/login` | Login |
| `POST /api/auth/mfa/verify` | MFA verification (uses challenge ID) |
| `POST /api/auth/mfa/recovery` | Recovery code (uses challenge ID) |
| `POST /api/auth/refresh` | Token refresh (uses refresh token) |
| `GET /api/auth/saml/login` | SAML SSO initiation |
| `POST /api/auth/saml/acs` | SAML assertion consumer |
| `GET /api/auth/saml/metadata` | SP metadata |
| `GET /api/auth/oidc/login` | OIDC SSO initiation |
| `GET /api/auth/oidc/callback` | OIDC callback |
| `GET /api/auth/sso/providers` | List available SSO providers |
