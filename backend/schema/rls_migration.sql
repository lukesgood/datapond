-- DataPond RLS schema migration (P0) — idempotent, see docs/RLS_DESIGN.md.
-- Creates ONLY what the RLS engine/loader/governance code needs, compatible with the
-- minimal running `users` table (id, username, role, is_active, ...). Safe to run on
-- every startup: every statement is IF NOT EXISTS / ON CONFLICT. If the full auth.sql
-- schema is already applied, the CREATE IF NOT EXISTS calls are no-ops.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- RLS attributes on users (department / region / clearance / ...)
ALTER TABLE users ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}';

-- Minimal-shape auth columns that auth.py reads directly (login/admin-seed/directory).
-- The "full" auth.sql historically omitted these (used status + roles/user_roles), so on
-- an already-bootstrapped DB (auth.sql is sentinel-guarded and won't re-run) they must be
-- added here — this migration runs every startup and is idempotent.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'viewer';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS require_password_change BOOLEAN NOT NULL DEFAULT false;

-- Roles + user-role assignment (loader reads these; falls back to users.role if absent)
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128),
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, role_id)
);

-- Row-level security policies
CREATE TABLE IF NOT EXISTS rls_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    description TEXT,
    catalog_name VARCHAR(128) NOT NULL,
    schema_name VARCHAR(128) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    filter_expression TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    priority INTEGER NOT NULL DEFAULT 0,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rls_policy_name UNIQUE (catalog_name, schema_name, table_name, name)
);
CREATE INDEX IF NOT EXISTS idx_rls_policies_table ON rls_policies(catalog_name, schema_name, table_name);

CREATE TABLE IF NOT EXISTS rls_policy_roles (
    policy_id UUID NOT NULL REFERENCES rls_policies(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    is_exempt BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (policy_id, role_id)
);

-- Column masking policies
CREATE TABLE IF NOT EXISTS column_masking_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    description TEXT,
    catalog_name VARCHAR(128) NOT NULL,
    schema_name VARCHAR(128) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    column_name VARCHAR(128) NOT NULL,
    masking_type VARCHAR(32) NOT NULL,
    custom_expression TEXT,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_masking_policy UNIQUE (catalog_name, schema_name, table_name, column_name, name)
);
CREATE INDEX IF NOT EXISTS idx_masking_policies_table ON column_masking_policies(catalog_name, schema_name, table_name);

CREATE TABLE IF NOT EXISTS masking_policy_roles (
    policy_id UUID NOT NULL REFERENCES column_masking_policies(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    is_exempt BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (policy_id, role_id)
);

-- Audit log (event_type kept as VARCHAR so it works without the auth.sql enum;
-- if the enum-typed table already exists, this CREATE is a no-op)
CREATE TABLE IF NOT EXISTS auth_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(64) NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    user_email VARCHAR(320),
    target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    resource VARCHAR(256),
    action VARCHAR(128),
    result VARCHAR(32) NOT NULL DEFAULT 'success',
    failure_reason TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON auth_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON auth_audit_log(event_type, created_at DESC);

-- Seed system roles
INSERT INTO roles (name, display_name, description, is_system) VALUES
    ('admin', 'Administrator', 'Full platform access.', true),
    ('data_engineer', 'Data Engineer', 'Pipelines, tables, connectors.', true),
    ('data_scientist', 'Data Scientist', 'Queries, experiments, notebooks.', true),
    ('business_analyst', 'Business Analyst', 'SELECT queries, dashboards.', true),
    ('viewer', 'Viewer', 'Read-only access.', true)
ON CONFLICT (name) DO NOTHING;

-- Backfill user_roles from the minimal users.role column (admin/viewer) when present.
-- Guarded: the full auth.sql schema has no users.role column, so check first.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'role'
    ) THEN
        INSERT INTO user_roles (user_id, role_id)
        SELECT u.id, r.id FROM users u JOIN roles r ON r.name = u.role
        WHERE u.role IS NOT NULL
        ON CONFLICT DO NOTHING;
    END IF;
END $$;
