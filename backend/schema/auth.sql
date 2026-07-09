-- DataPond Authentication & Authorization Schema
-- PostgreSQL 16+
-- All tables reside in the 'datapond' database

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- ENUMS
-- ============================================================================

CREATE TYPE auth_method AS ENUM ('local', 'ldap', 'saml', 'oidc');
CREATE TYPE user_status AS ENUM ('active', 'inactive', 'locked', 'pending_activation');
CREATE TYPE mfa_device_type AS ENUM ('totp', 'webauthn');
CREATE TYPE mfa_device_status AS ENUM ('active', 'disabled', 'pending_verification');
CREATE TYPE api_key_status AS ENUM ('active', 'revoked', 'expired');
CREATE TYPE audit_event_type AS ENUM (
    'login_success', 'login_failure', 'logout',
    'token_refresh', 'token_revoked',
    'mfa_enroll', 'mfa_verify_success', 'mfa_verify_failure', 'mfa_device_removed',
    'password_change', 'password_reset_request', 'password_reset_complete',
    'role_assigned', 'role_removed', 'role_created', 'role_updated', 'role_deleted',
    'permission_denied',
    'session_terminated', 'session_expired',
    'account_locked', 'account_unlocked', 'account_activated', 'account_deactivated',
    'api_key_created', 'api_key_revoked',
    'user_created', 'user_updated', 'user_deleted',
    'ldap_config_updated', 'saml_config_updated', 'oidc_config_updated',
    'rls_policy_created', 'rls_policy_updated', 'rls_policy_deleted',
    'masking_policy_created', 'masking_policy_updated', 'masking_policy_deleted'
);

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(320) NOT NULL UNIQUE,       -- RFC 5321 max email length
    username VARCHAR(128) UNIQUE,
    display_name VARCHAR(256),
    password_hash VARCHAR(256),                -- bcrypt hash; NULL for SSO-only users
    auth_method auth_method NOT NULL DEFAULT 'local',
    status user_status NOT NULL DEFAULT 'active',

    -- Minimal-shape columns read directly by auth.py (login/admin-seed/directory-upsert)
    -- and the RLS loader (rls_migration backfills user_roles from users.role). These
    -- coexist with status/roles/user_roles; auth.py uses role/is_active/require_password_change.
    role VARCHAR(32) NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT true,
    require_password_change BOOLEAN NOT NULL DEFAULT false,

    -- External identity (populated for LDAP/SAML/OIDC users)
    external_id VARCHAR(512),                  -- DN for LDAP, NameID for SAML, sub for OIDC
    external_provider VARCHAR(128),            -- e.g., 'corporate-ad', 'keycloak', 'adfs'

    -- Profile attributes (used for RLS, display, etc.)
    attributes JSONB NOT NULL DEFAULT '{}',    -- {"department": "eng", "region": "us-east"}

    -- Password management
    password_changed_at TIMESTAMPTZ,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_at TIMESTAMPTZ,
    locked_until TIMESTAMPTZ,

    -- MFA
    mfa_enabled BOOLEAN NOT NULL DEFAULT false,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT chk_local_password CHECK (
        auth_method != 'local' OR password_hash IS NOT NULL
    )
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_status ON users(status);
CREATE INDEX idx_users_external ON users(external_provider, external_id);
CREATE INDEX idx_users_auth_method ON users(auth_method);

-- Password history (prevent reuse)
CREATE TABLE IF NOT EXISTS password_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash VARCHAR(256) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_password_history_user ON password_history(user_id, created_at DESC);

-- ============================================================================
-- ROLES & PERMISSIONS
-- ============================================================================

-- Roles
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128),
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT false,  -- System roles cannot be deleted
    parent_role_id UUID REFERENCES roles(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_roles_name ON roles(name);
CREATE INDEX idx_roles_parent ON roles(parent_role_id);

-- Permissions
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource VARCHAR(64) NOT NULL,     -- e.g., 'catalog', 'query', 'pipeline', 'notebook', 'ml', 'connector', 'streaming', 'admin'
    action VARCHAR(64) NOT NULL,       -- e.g., 'create', 'read', 'update', 'delete', 'execute', 'manage'
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_permission UNIQUE (resource, action)
);

CREATE INDEX idx_permissions_resource ON permissions(resource);

-- Role-Permission mapping
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (role_id, permission_id)
);

-- User-Role mapping
CREATE TABLE IF NOT EXISTS user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    granted_by UUID REFERENCES users(id) ON DELETE SET NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,              -- Optional: time-limited role assignment

    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);
CREATE INDEX idx_user_roles_expires ON user_roles(expires_at) WHERE expires_at IS NOT NULL;

-- ============================================================================
-- MFA DEVICES
-- ============================================================================

CREATE TABLE IF NOT EXISTS mfa_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_type mfa_device_type NOT NULL DEFAULT 'totp',
    device_name VARCHAR(128) NOT NULL,         -- e.g., "Work Phone", "YubiKey"
    status mfa_device_status NOT NULL DEFAULT 'pending_verification',

    -- TOTP-specific fields
    totp_secret_encrypted TEXT,                 -- AES-256-GCM encrypted TOTP secret
    totp_verified_at TIMESTAMPTZ,

    -- WebAuthn-specific fields (future)
    webauthn_credential_id TEXT,
    webauthn_public_key TEXT,

    -- Recovery codes (hashed, one-time use)
    recovery_codes_hash TEXT[],                -- Array of bcrypt-hashed recovery codes

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_mfa_devices_user ON mfa_devices(user_id);
CREATE INDEX idx_mfa_devices_status ON mfa_devices(user_id, status);

-- ============================================================================
-- API KEYS
-- ============================================================================

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    key_prefix VARCHAR(16) NOT NULL,           -- First 8 chars for identification: "dp_live_ab"
    key_hash VARCHAR(128) NOT NULL UNIQUE,     -- SHA-256 hash of the full key
    status api_key_status NOT NULL DEFAULT 'active',
    scopes TEXT[] NOT NULL DEFAULT '{}',       -- Restrict to specific permissions
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    last_used_ip INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    revoked_by UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_api_keys_user ON api_keys(user_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_status ON api_keys(status);
CREATE INDEX idx_api_keys_prefix ON api_keys(key_prefix);

-- ============================================================================
-- SESSIONS
-- ============================================================================
-- Primary session storage is in Valkey (for performance).
-- This table is a persistent record for auditing and device management.

CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(64) PRIMARY KEY,                -- Same as Valkey session key
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auth_method auth_method NOT NULL,
    ip_address INET,
    user_agent TEXT,
    device_fingerprint VARCHAR(128),
    mfa_verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    terminated_at TIMESTAMPTZ,                 -- NULL = active
    terminated_reason VARCHAR(64)              -- 'logout', 'admin_kill', 'expired', 'replaced'
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_active ON sessions(user_id, terminated_at) WHERE terminated_at IS NULL;
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- ============================================================================
-- IDENTITY PROVIDER CONFIGURATIONS
-- ============================================================================

-- LDAP/AD Configuration
CREATE TABLE IF NOT EXISTS ldap_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL UNIQUE,          -- e.g., "Corporate Active Directory"
    enabled BOOLEAN NOT NULL DEFAULT true,
    priority INTEGER NOT NULL DEFAULT 0,        -- Lower = tried first

    -- Connection
    url VARCHAR(512) NOT NULL,                  -- ldaps://ad.example.com:636
    bind_dn VARCHAR(512) NOT NULL,
    bind_password_encrypted TEXT NOT NULL,       -- AES-256-GCM encrypted
    base_dn VARCHAR(512) NOT NULL,
    connection_timeout INTEGER NOT NULL DEFAULT 5,  -- seconds
    read_timeout INTEGER NOT NULL DEFAULT 10,       -- seconds

    -- Search configuration
    user_search_base VARCHAR(512),              -- Defaults to base_dn
    user_search_filter VARCHAR(512) NOT NULL DEFAULT '(&(objectClass=person)(mail={email}))',
    username_attribute VARCHAR(64) NOT NULL DEFAULT 'sAMAccountName',
    email_attribute VARCHAR(64) NOT NULL DEFAULT 'mail',
    display_name_attribute VARCHAR(64) NOT NULL DEFAULT 'displayName',
    group_search_base VARCHAR(512),
    group_search_filter VARCHAR(512) NOT NULL DEFAULT '(&(objectClass=group)(member={user_dn}))',
    group_attribute VARCHAR(64) NOT NULL DEFAULT 'cn',

    -- TLS
    tls_verify BOOLEAN NOT NULL DEFAULT true,
    tls_ca_cert TEXT,                           -- PEM-encoded CA certificate
    tls_client_cert TEXT,                       -- PEM-encoded client certificate (mutual TLS)
    tls_client_key_encrypted TEXT,              -- AES-256-GCM encrypted client private key

    -- Sync settings
    sync_groups_on_login BOOLEAN NOT NULL DEFAULT true,
    sync_interval_minutes INTEGER DEFAULT 60,   -- Background group sync frequency

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- LDAP Group-to-Role Mapping
CREATE TABLE IF NOT EXISTS ldap_group_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ldap_config_id UUID NOT NULL REFERENCES ldap_configs(id) ON DELETE CASCADE,
    ldap_group_dn VARCHAR(512) NOT NULL,        -- Full DN of the LDAP group
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_ldap_group_mapping UNIQUE (ldap_config_id, ldap_group_dn, role_id)
);

CREATE INDEX idx_ldap_group_mappings_config ON ldap_group_mappings(ldap_config_id);

-- SAML Configuration
CREATE TABLE IF NOT EXISTS saml_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL UNIQUE,          -- e.g., "Corporate ADFS"
    enabled BOOLEAN NOT NULL DEFAULT true,

    -- Identity Provider
    idp_entity_id VARCHAR(512) NOT NULL,
    idp_sso_url VARCHAR(512) NOT NULL,          -- SSO login URL
    idp_slo_url VARCHAR(512),                   -- Single logout URL (optional)
    idp_certificate TEXT NOT NULL,              -- PEM-encoded IdP signing certificate
    idp_metadata_xml TEXT,                      -- Raw IdP metadata (alternative to individual fields)

    -- Service Provider
    sp_entity_id VARCHAR(512) NOT NULL DEFAULT 'datapond',
    sp_acs_url VARCHAR(512) NOT NULL,           -- Assertion Consumer Service URL
    sp_certificate TEXT,                        -- PEM-encoded SP certificate (for signed requests)
    sp_private_key_encrypted TEXT,              -- AES-256-GCM encrypted SP private key

    -- Attribute mapping
    attribute_mapping JSONB NOT NULL DEFAULT '{
        "email": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
        "name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "groups": "http://schemas.xmlsoap.org/claims/Group"
    }',

    -- Options
    sign_requests BOOLEAN NOT NULL DEFAULT true,
    want_assertions_signed BOOLEAN NOT NULL DEFAULT true,
    want_assertions_encrypted BOOLEAN NOT NULL DEFAULT false,
    allow_idp_initiated BOOLEAN NOT NULL DEFAULT false,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- SAML Group-to-Role Mapping
CREATE TABLE IF NOT EXISTS saml_group_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    saml_config_id UUID NOT NULL REFERENCES saml_configs(id) ON DELETE CASCADE,
    saml_group_name VARCHAR(256) NOT NULL,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_saml_group_mapping UNIQUE (saml_config_id, saml_group_name, role_id)
);

CREATE INDEX idx_saml_group_mappings_config ON saml_group_mappings(saml_config_id);

-- OIDC Configuration
CREATE TABLE IF NOT EXISTS oidc_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL UNIQUE,          -- e.g., "Keycloak Production"
    enabled BOOLEAN NOT NULL DEFAULT true,

    -- Provider
    issuer_url VARCHAR(512) NOT NULL,           -- e.g., https://keycloak.example.com/realms/datapond
    client_id VARCHAR(256) NOT NULL,
    client_secret_encrypted TEXT NOT NULL,       -- AES-256-GCM encrypted
    scopes TEXT[] NOT NULL DEFAULT ARRAY['openid', 'profile', 'email'],

    -- Discovery
    authorization_endpoint VARCHAR(512),        -- Auto-discovered from .well-known if NULL
    token_endpoint VARCHAR(512),
    userinfo_endpoint VARCHAR(512),
    jwks_uri VARCHAR(512),
    end_session_endpoint VARCHAR(512),

    -- Claim mapping
    claim_mapping JSONB NOT NULL DEFAULT '{
        "email": "email",
        "name": "name",
        "groups": "groups"
    }',

    -- Options
    use_pkce BOOLEAN NOT NULL DEFAULT true,
    verify_nonce BOOLEAN NOT NULL DEFAULT true,
    tls_verify BOOLEAN NOT NULL DEFAULT true,
    tls_ca_cert TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- OIDC Group-to-Role Mapping
CREATE TABLE IF NOT EXISTS oidc_group_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    oidc_config_id UUID NOT NULL REFERENCES oidc_configs(id) ON DELETE CASCADE,
    oidc_group_name VARCHAR(256) NOT NULL,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_oidc_group_mapping UNIQUE (oidc_config_id, oidc_group_name, role_id)
);

CREATE INDEX idx_oidc_group_mappings_config ON oidc_group_mappings(oidc_config_id);

-- ============================================================================
-- ROW-LEVEL SECURITY POLICIES
-- ============================================================================

CREATE TABLE IF NOT EXISTS rls_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    description TEXT,
    catalog_name VARCHAR(128) NOT NULL,         -- Polaris catalog
    schema_name VARCHAR(128) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    filter_expression TEXT NOT NULL,             -- SQL boolean expression, e.g., "region = current_user_attribute('region')"
    enabled BOOLEAN NOT NULL DEFAULT true,
    priority INTEGER NOT NULL DEFAULT 0,        -- Higher = applied later (AND-combined)
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_rls_policy_name UNIQUE (catalog_name, schema_name, table_name, name)
);

CREATE INDEX idx_rls_policies_table ON rls_policies(catalog_name, schema_name, table_name);

-- RLS Policy-Role mapping (which roles this policy applies to)
CREATE TABLE IF NOT EXISTS rls_policy_roles (
    policy_id UUID NOT NULL REFERENCES rls_policies(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    is_exempt BOOLEAN NOT NULL DEFAULT false,   -- true = role is exempt from this policy

    PRIMARY KEY (policy_id, role_id)
);

-- ============================================================================
-- COLUMN MASKING POLICIES
-- ============================================================================

CREATE TYPE masking_type AS ENUM ('full', 'partial_email', 'partial_ssn', 'partial_phone', 'hash', 'null', 'custom');

CREATE TABLE IF NOT EXISTS column_masking_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    description TEXT,
    catalog_name VARCHAR(128) NOT NULL,
    schema_name VARCHAR(128) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    column_name VARCHAR(128) NOT NULL,
    masking_type masking_type NOT NULL,
    custom_expression TEXT,                      -- SQL expression for 'custom' type
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_masking_policy UNIQUE (catalog_name, schema_name, table_name, column_name, name)
);

CREATE INDEX idx_masking_policies_table ON column_masking_policies(catalog_name, schema_name, table_name);

-- Column Masking Policy-Role mapping
CREATE TABLE IF NOT EXISTS masking_policy_roles (
    policy_id UUID NOT NULL REFERENCES column_masking_policies(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    is_exempt BOOLEAN NOT NULL DEFAULT false,

    PRIMARY KEY (policy_id, role_id)
);

-- ============================================================================
-- AUDIT LOG
-- ============================================================================

CREATE TABLE IF NOT EXISTS auth_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type audit_event_type NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    user_email VARCHAR(320),                    -- Denormalized for when user is deleted
    target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id VARCHAR(64),
    ip_address INET,
    user_agent TEXT,
    resource VARCHAR(256),                      -- Resource involved (table name, DAG id, etc.)
    action VARCHAR(128),                        -- Action attempted
    result VARCHAR(32) NOT NULL DEFAULT 'success',  -- 'success' or 'failure'
    failure_reason TEXT,
    details JSONB DEFAULT '{}',                 -- Additional context
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partitioning by month for large-scale deployments (optional, applied via ALTER TABLE)
-- CREATE TABLE auth_audit_log (...) PARTITION BY RANGE (created_at);

CREATE INDEX idx_audit_log_user ON auth_audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_log_event ON auth_audit_log(event_type, created_at DESC);
CREATE INDEX idx_audit_log_time ON auth_audit_log(created_at DESC);
CREATE INDEX idx_audit_log_session ON auth_audit_log(session_id);
CREATE INDEX idx_audit_log_ip ON auth_audit_log(ip_address);
CREATE INDEX idx_audit_log_target ON auth_audit_log(target_user_id, created_at DESC);

-- Prevent application-level UPDATE/DELETE on audit log via row-level security
-- (enforced by using a read-only database role for normal operations)
-- The audit_writer role is the only role allowed to INSERT.

-- ============================================================================
-- PLATFORM SETTINGS
-- ============================================================================

CREATE TABLE IF NOT EXISTS auth_settings (
    key VARCHAR(128) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to all tables with updated_at
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name = 'updated_at'
          AND table_name NOT IN ('auth_audit_log', 'auth_settings')
          AND table_name IN (
              'users', 'roles', 'ldap_configs', 'saml_configs',
              'oidc_configs', 'rls_policies', 'column_masking_policies'
          )
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_update_%I_updated_at ON %I; ' ||
            'CREATE TRIGGER trg_update_%I_updated_at BEFORE UPDATE ON %I ' ||
            'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();',
            tbl, tbl, tbl, tbl
        );
    END LOOP;
END;
$$;

-- Function to check if a user has a specific permission (including role inheritance)
CREATE OR REPLACE FUNCTION user_has_permission(
    p_user_id UUID,
    p_resource VARCHAR,
    p_action VARCHAR
) RETURNS BOOLEAN AS $$
DECLARE
    has_perm BOOLEAN;
BEGIN
    -- Check direct role permissions and inherited permissions via parent_role chain
    WITH RECURSIVE role_chain AS (
        -- Start with user's directly assigned roles
        SELECT r.id, r.parent_role_id
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = p_user_id
          AND (ur.expires_at IS NULL OR ur.expires_at > NOW())

        UNION

        -- Walk up parent chain (child inherits parent permissions)
        -- Note: In our hierarchy, admin is the root. data_engineer's parent is admin, etc.
        -- A child role inherits NO permissions from parent by default.
        -- Permissions are explicitly assigned to each role.
        -- Parent_role_id is used for UI grouping, not permission inheritance.
        SELECT r.id, r.parent_role_id
        FROM roles r
        JOIN role_chain rc ON r.id = rc.parent_role_id
    )
    SELECT EXISTS (
        SELECT 1
        FROM role_chain rc2
        JOIN role_permissions rp ON rc2.id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.resource = p_resource AND p.action = p_action
    ) INTO has_perm;

    RETURN has_perm;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- SEED DATA: System Roles
-- ============================================================================

INSERT INTO roles (name, display_name, description, is_system) VALUES
    ('admin', 'Administrator', 'Full platform access. Can manage users, roles, settings, and all resources.', true),
    ('data_engineer', 'Data Engineer', 'Create and manage data pipelines, tables, connectors, and streaming jobs.', true),
    ('data_scientist', 'Data Scientist', 'Run queries, create experiments, train models, and execute notebooks.', true),
    ('business_analyst', 'Business Analyst', 'Run SELECT queries, view dashboards, trigger pipelines, and view shared notebooks.', true),
    ('viewer', 'Viewer', 'Read-only access to dashboards, catalog metadata, and shared resources.', true)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- SEED DATA: Permissions
-- ============================================================================

INSERT INTO permissions (resource, action, description) VALUES
    -- Admin
    ('admin', 'manage_users', 'Create, update, delete, lock/unlock user accounts'),
    ('admin', 'manage_roles', 'Create, update, delete roles and assign permissions'),
    ('admin', 'manage_settings', 'Modify platform-wide settings (auth, security, etc.)'),
    ('admin', 'manage_idp', 'Configure LDAP, SAML, OIDC identity providers'),
    ('admin', 'view_audit_log', 'View authentication and authorization audit logs'),
    ('admin', 'manage_sessions', 'View and terminate other users sessions'),

    -- Catalog
    ('catalog', 'create', 'Create new catalogs in Polaris'),
    ('catalog', 'drop', 'Drop catalogs from Polaris'),
    ('catalog', 'read', 'View catalog metadata and browse schemas/tables'),
    ('schema', 'create', 'Create schemas within catalogs'),
    ('schema', 'drop', 'Drop schemas from catalogs'),
    ('table', 'create', 'Create tables within schemas'),
    ('table', 'drop', 'Drop tables from schemas'),
    ('table', 'alter', 'Alter table schema (add/drop columns, rename)'),
    ('table', 'read', 'Read table data via SELECT queries'),
    ('table', 'write', 'Write table data via INSERT/UPDATE/DELETE'),

    -- Query
    ('query', 'execute_ddl', 'Execute DDL statements (CREATE, ALTER, DROP)'),
    ('query', 'execute_dml', 'Execute DML statements (INSERT, UPDATE, DELETE)'),
    ('query', 'execute_select', 'Execute SELECT queries'),
    ('query', 'kill_own', 'Cancel own running queries'),
    ('query', 'kill_any', 'Cancel any user running queries'),

    -- Pipeline (Airflow)
    ('pipeline', 'create', 'Create and edit Airflow DAGs'),
    ('pipeline', 'delete', 'Delete Airflow DAGs'),
    ('pipeline', 'trigger', 'Manually trigger DAG runs'),
    ('pipeline', 'view', 'View DAG status, logs, and history'),

    -- Notebook (JupyterLab)
    ('notebook', 'create', 'Create and edit notebooks'),
    ('notebook', 'execute', 'Execute notebook cells'),
    ('notebook', 'delete', 'Delete notebooks'),
    ('notebook', 'view', 'View shared notebooks (read-only)'),

    -- ML (MLflow)
    ('ml', 'create_experiment', 'Create MLflow experiments'),
    ('ml', 'register_model', 'Register models in the model registry'),
    ('ml', 'deploy_model', 'Promote models to production stage'),
    ('ml', 'view', 'View experiments, runs, and registered models'),

    -- Connectors
    ('connector', 'create', 'Create and configure data connectors'),
    ('connector', 'update', 'Update existing connector configurations'),
    ('connector', 'delete', 'Delete data connectors'),
    ('connector', 'view', 'View connector status and sync history'),

    -- Streaming (RisingWave)
    ('streaming', 'create_mv', 'Create materialized views'),
    ('streaming', 'create_source', 'Create streaming sources and sinks'),
    ('streaming', 'drop', 'Drop materialized views, sources, sinks'),
    ('streaming', 'query', 'Query materialized views'),

    -- Data Security
    ('security', 'manage_rls', 'Create, update, delete row-level security policies'),
    ('security', 'manage_masking', 'Create, update, delete column masking policies'),
    ('security', 'view_policies', 'View RLS and masking policies')
ON CONFLICT (resource, action) DO NOTHING;

-- ============================================================================
-- SEED DATA: Role-Permission Assignments
-- ============================================================================

-- Admin: all permissions
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r, permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

-- Data Engineer
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r, permissions p
WHERE r.name = 'data_engineer'
  AND (p.resource, p.action) IN (
    ('catalog', 'create'), ('catalog', 'drop'), ('catalog', 'read'),
    ('schema', 'create'), ('schema', 'drop'),
    ('table', 'create'), ('table', 'drop'), ('table', 'alter'), ('table', 'read'), ('table', 'write'),
    ('query', 'execute_ddl'), ('query', 'execute_dml'), ('query', 'execute_select'),
    ('query', 'kill_own'), ('query', 'kill_any'),
    ('pipeline', 'create'), ('pipeline', 'delete'), ('pipeline', 'trigger'), ('pipeline', 'view'),
    ('notebook', 'create'), ('notebook', 'execute'), ('notebook', 'delete'), ('notebook', 'view'),
    ('ml', 'create_experiment'), ('ml', 'register_model'), ('ml', 'deploy_model'), ('ml', 'view'),
    ('connector', 'create'), ('connector', 'update'), ('connector', 'delete'), ('connector', 'view'),
    ('streaming', 'create_mv'), ('streaming', 'create_source'), ('streaming', 'drop'), ('streaming', 'query'),
    ('security', 'view_policies')
  )
ON CONFLICT DO NOTHING;

-- Data Scientist
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r, permissions p
WHERE r.name = 'data_scientist'
  AND (p.resource, p.action) IN (
    ('catalog', 'read'),
    ('table', 'read'), ('table', 'write'),
    ('query', 'execute_dml'), ('query', 'execute_select'), ('query', 'kill_own'),
    ('pipeline', 'trigger'), ('pipeline', 'view'),
    ('notebook', 'create'), ('notebook', 'execute'), ('notebook', 'view'),
    ('ml', 'create_experiment'), ('ml', 'register_model'), ('ml', 'view'),
    ('connector', 'view'),
    ('streaming', 'query'),
    ('security', 'view_policies')
  )
ON CONFLICT DO NOTHING;

-- Business Analyst
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r, permissions p
WHERE r.name = 'business_analyst'
  AND (p.resource, p.action) IN (
    ('catalog', 'read'),
    ('table', 'read'),
    ('query', 'execute_select'), ('query', 'kill_own'),
    ('pipeline', 'trigger'), ('pipeline', 'view'),
    ('notebook', 'view'),
    ('ml', 'view'),
    ('connector', 'view'),
    ('streaming', 'query')
  )
ON CONFLICT DO NOTHING;

-- Viewer
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r, permissions p
WHERE r.name = 'viewer'
  AND (p.resource, p.action) IN (
    ('catalog', 'read'),
    ('table', 'read'),
    ('query', 'execute_select'), ('query', 'kill_own'),
    ('pipeline', 'view'),
    ('notebook', 'view'),
    ('ml', 'view'),
    ('streaming', 'query')
  )
ON CONFLICT DO NOTHING;

-- ============================================================================
-- SEED DATA: Default Admin User
-- ============================================================================
-- Password: 'DataPond!Admin2026' (bcrypt hash)
-- IMPORTANT: Change this password immediately after first login.

INSERT INTO users (email, username, display_name, password_hash, auth_method, status)
VALUES (
    'admin@datapond.local',
    'admin',
    'DataPond Administrator',
    -- bcrypt hash of 'DataPond!Admin2026' with cost factor 12
    '$2b$12$placeholder_hash_replace_on_first_deploy',
    'local',
    'active'
) ON CONFLICT (email) DO NOTHING;

-- Assign admin role to default admin user
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id
FROM users u, roles r
WHERE u.email = 'admin@datapond.local' AND r.name = 'admin'
ON CONFLICT DO NOTHING;
