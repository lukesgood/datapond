-- The Portable Core schema as the application actually produces it.
--
-- Generated with pg_dump --schema-only from the live reference deployment
-- (2026-08-27), not written by hand: 41 tables, 62 indexes, 105 constraints, 8 enum
-- types, 3 functions and 10 triggers is more than anyone transcribes correctly.
--
-- This runs only against a database with no application tables. A deployment that
-- already has them is stamped at this revision instead, because it is already here.
-- See app/migrations.py.
--
-- Verified by building a scratch database from this file and diffing it against the
-- live schema. What remains in that diff is Postgres re-rendering CHECK constraints
-- into an equivalent form, which it does to any constraint that survives a dump and
-- reload, and which no amount of editing this file removes.
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TYPE public.api_key_status AS ENUM (
    'active',
    'revoked',
    'expired'
);

CREATE TYPE public.audit_event_type AS ENUM (
    'login_success',
    'login_failure',
    'logout',
    'token_refresh',
    'token_revoked',
    'mfa_enroll',
    'mfa_verify_success',
    'mfa_verify_failure',
    'mfa_device_removed',
    'password_change',
    'password_reset_request',
    'password_reset_complete',
    'role_assigned',
    'role_removed',
    'role_created',
    'role_updated',
    'role_deleted',
    'permission_denied',
    'session_terminated',
    'session_expired',
    'account_locked',
    'account_unlocked',
    'account_activated',
    'account_deactivated',
    'api_key_created',
    'api_key_revoked',
    'user_created',
    'user_updated',
    'user_deleted',
    'ldap_config_updated',
    'saml_config_updated',
    'oidc_config_updated',
    'rls_policy_created',
    'rls_policy_updated',
    'rls_policy_deleted',
    'masking_policy_created',
    'masking_policy_updated',
    'masking_policy_deleted',
    'chat_action_proposed',
    'chat_action_approved',
    'chat_action_rejected',
    'chat_action_executed',
    'chat_action_failed',
    'chat_action_refused'
);

CREATE TYPE public.auth_method AS ENUM (
    'local',
    'ldap',
    'saml',
    'oidc',
    'service'
);

CREATE TYPE public.chat_invocation_status AS ENUM (
    'proposed',
    'approved',
    'rejected',
    'executed',
    'failed'
);

CREATE TYPE public.masking_type AS ENUM (
    'full',
    'partial_email',
    'partial_ssn',
    'partial_phone',
    'hash',
    'null',
    'custom'
);

CREATE TYPE public.mfa_device_status AS ENUM (
    'active',
    'disabled',
    'pending_verification'
);

CREATE TYPE public.mfa_device_type AS ENUM (
    'totp',
    'webauthn'
);

CREATE TYPE public.user_status AS ENUM (
    'active',
    'inactive',
    'locked',
    'pending_activation'
);

CREATE FUNCTION public.update_dashboard_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.user_has_permission(p_user_id uuid, p_resource character varying, p_action character varying) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
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
$$;

CREATE TABLE public.ai_chunks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    collection_id uuid NOT NULL,
    source text,
    chunk_index integer,
    content text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    embedding public.vector(1024),
    created_at timestamp with time zone DEFAULT now(),
    source_group text
);

CREATE TABLE public.ai_collections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    embed_model text NOT NULL,
    dim integer NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    owner_id uuid,
    refresh_source jsonb,
    refresh_interval_minutes integer,
    refresh_enabled boolean DEFAULT false NOT NULL,
    last_refreshed_at timestamp with time zone,
    last_refresh_status text,
    chunk_preset text,
    chunk_size integer,
    chunk_overlap integer
);

CREATE TABLE public.api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    key_prefix character varying(16) NOT NULL,
    key_hash character varying(128) NOT NULL,
    status public.api_key_status DEFAULT 'active'::public.api_key_status NOT NULL,
    scopes text[] DEFAULT '{}'::text[] NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    last_used_ip inet,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by uuid
);

CREATE TABLE public.auth_audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type public.audit_event_type NOT NULL,
    user_id uuid,
    user_email character varying(320),
    target_user_id uuid,
    session_id character varying(64),
    ip_address inet,
    user_agent text,
    resource character varying(256),
    action character varying(128),
    result character varying(32) DEFAULT 'success'::character varying NOT NULL,
    failure_reason text,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.auth_settings (
    key character varying(128) NOT NULL,
    value jsonb NOT NULL,
    description text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid
);

CREATE TABLE public.chat_action_invocations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid,
    user_id uuid NOT NULL,
    action_id character varying(64) NOT NULL,
    page character varying(128),
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    preview jsonb,
    request_text text,
    status public.chat_invocation_status DEFAULT 'proposed'::public.chat_invocation_status NOT NULL,
    approved_by uuid,
    approved_at timestamp with time zone,
    executed_at timestamp with time zone,
    result jsonb,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.chat_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    page character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_activity_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.column_masking_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    description text,
    catalog_name character varying(128) NOT NULL,
    schema_name character varying(128) NOT NULL,
    table_name character varying(128) NOT NULL,
    column_name character varying(128) NOT NULL,
    masking_type public.masking_type NOT NULL,
    custom_expression text,
    enabled boolean DEFAULT true NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.concept_terms (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    concept_id uuid NOT NULL,
    term text NOT NULL,
    kind text DEFAULT 'alias'::text NOT NULL
);

CREATE TABLE public.connector_connections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    connector_type character varying(50) NOT NULL,
    config_encrypted text NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    last_sync_at timestamp without time zone,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    schedule text,
    CONSTRAINT check_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'error'::character varying, 'testing'::character varying])::text[])))
);

CREATE TABLE public.connector_credentials_audit (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    connection_id uuid NOT NULL,
    action character varying(50) NOT NULL,
    performed_by character varying(255),
    performed_at timestamp without time zone DEFAULT now() NOT NULL,
    details jsonb,
    CONSTRAINT check_action CHECK (((action)::text = ANY ((ARRAY['created'::character varying, 'updated'::character varying, 'deleted'::character varying, 'accessed'::character varying, 'rotated'::character varying])::text[])))
);

CREATE TABLE public.connector_sync_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    connection_id uuid NOT NULL,
    source_table character varying(255) NOT NULL,
    target_table character varying(255) NOT NULL,
    sync_mode character varying(20) DEFAULT 'full'::character varying NOT NULL,
    schedule character varying(50),
    incremental_column character varying(100),
    last_value text,
    partition_spec jsonb,
    key_columns jsonb,
    pii_columns jsonb,
    primary_keys text[],
    last_run_at timestamp without time zone,
    last_run_status character varying(20),
    rows_synced integer DEFAULT 0,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_last_run_status CHECK (((last_run_status IS NULL) OR ((last_run_status)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'running'::character varying, 'pending'::character varying, 'cancelled'::character varying])::text[])))),
    CONSTRAINT check_sync_mode CHECK (((sync_mode)::text = ANY ((ARRAY['full'::character varying, 'incremental'::character varying, 'cdc'::character varying, 'snapshot'::character varying])::text[])))
);

CREATE VIEW public.connector_health_summary AS
 SELECT cc.id,
    cc.name,
    cc.connector_type,
    cc.status,
    cc.last_sync_at,
    count(csj.id) AS total_jobs,
    sum(
        CASE
            WHEN ((csj.last_run_status)::text = 'success'::text) THEN 1
            ELSE 0
        END) AS successful_jobs,
    sum(
        CASE
            WHEN ((csj.last_run_status)::text = 'failed'::text) THEN 1
            ELSE 0
        END) AS failed_jobs,
    sum(
        CASE
            WHEN ((csj.last_run_status)::text = 'running'::text) THEN 1
            ELSE 0
        END) AS running_jobs,
    sum(csj.rows_synced) AS total_rows_synced
   FROM (public.connector_connections cc
     LEFT JOIN public.connector_sync_jobs csj ON ((cc.id = csj.connection_id)))
  GROUP BY cc.id, cc.name, cc.connector_type, cc.status, cc.last_sync_at;

CREATE TABLE public.connector_quality_checks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    connection_id uuid NOT NULL,
    source_table text NOT NULL,
    checked_at timestamp without time zone DEFAULT now() NOT NULL,
    rows_current bigint,
    rows_previous bigint,
    row_change_pct double precision,
    row_change_status text,
    null_checks jsonb,
    overall_status text,
    warnings jsonb
);

CREATE TABLE public.connector_sync_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_id uuid NOT NULL,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    completed_at timestamp without time zone,
    status character varying(20) NOT NULL,
    rows_processed integer DEFAULT 0,
    rows_failed integer DEFAULT 0,
    error_message text,
    metadata jsonb,
    CONSTRAINT check_history_status CHECK (((status)::text = ANY ((ARRAY['success'::character varying, 'failed'::character varying, 'running'::character varying, 'pending'::character varying, 'cancelled'::character varying])::text[])))
);

CREATE TABLE public.dashboard_shares (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dashboard_id uuid NOT NULL,
    shared_with_user_id uuid,
    shared_with_role_id uuid,
    permission character varying(20) DEFAULT 'view'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid NOT NULL,
    CONSTRAINT check_permission CHECK (((permission)::text = ANY ((ARRAY['view'::character varying, 'edit'::character varying])::text[]))),
    CONSTRAINT check_share_target CHECK ((((shared_with_user_id IS NOT NULL) AND (shared_with_role_id IS NULL)) OR ((shared_with_user_id IS NULL) AND (shared_with_role_id IS NOT NULL))))
);

CREATE TABLE public.dashboards (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    query_text text NOT NULL,
    chart_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_public boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_name_not_empty CHECK ((TRIM(BOTH FROM name) <> ''::text))
);

CREATE TABLE public.ldap_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    url character varying(512) NOT NULL,
    bind_dn character varying(512) NOT NULL,
    bind_password_encrypted text NOT NULL,
    base_dn character varying(512) NOT NULL,
    connection_timeout integer DEFAULT 5 NOT NULL,
    read_timeout integer DEFAULT 10 NOT NULL,
    user_search_base character varying(512),
    user_search_filter character varying(512) DEFAULT '(&(objectClass=person)(mail={email}))'::character varying NOT NULL,
    username_attribute character varying(64) DEFAULT 'sAMAccountName'::character varying NOT NULL,
    email_attribute character varying(64) DEFAULT 'mail'::character varying NOT NULL,
    display_name_attribute character varying(64) DEFAULT 'displayName'::character varying NOT NULL,
    group_search_base character varying(512),
    group_search_filter character varying(512) DEFAULT '(&(objectClass=group)(member={user_dn}))'::character varying NOT NULL,
    group_attribute character varying(64) DEFAULT 'cn'::character varying NOT NULL,
    tls_verify boolean DEFAULT true NOT NULL,
    tls_ca_cert text,
    tls_client_cert text,
    tls_client_key_encrypted text,
    sync_groups_on_login boolean DEFAULT true NOT NULL,
    sync_interval_minutes integer DEFAULT 60,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.ldap_group_mappings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    ldap_config_id uuid NOT NULL,
    ldap_group_dn character varying(512) NOT NULL,
    role_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.masking_policy_roles (
    policy_id uuid NOT NULL,
    role_id uuid NOT NULL,
    is_exempt boolean DEFAULT false NOT NULL
);

CREATE TABLE public.mfa_devices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    device_type public.mfa_device_type DEFAULT 'totp'::public.mfa_device_type NOT NULL,
    device_name character varying(128) NOT NULL,
    status public.mfa_device_status DEFAULT 'pending_verification'::public.mfa_device_status NOT NULL,
    totp_secret_encrypted text,
    totp_verified_at timestamp with time zone,
    webauthn_credential_id text,
    webauthn_public_key text,
    recovery_codes_hash text[],
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);

CREATE TABLE public.oidc_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    issuer_url character varying(512) NOT NULL,
    client_id character varying(256) NOT NULL,
    client_secret_encrypted text NOT NULL,
    scopes text[] DEFAULT ARRAY['openid'::text, 'profile'::text, 'email'::text] NOT NULL,
    authorization_endpoint character varying(512),
    token_endpoint character varying(512),
    userinfo_endpoint character varying(512),
    jwks_uri character varying(512),
    end_session_endpoint character varying(512),
    claim_mapping jsonb DEFAULT '{"name": "name", "email": "email", "groups": "groups"}'::jsonb NOT NULL,
    use_pkce boolean DEFAULT true NOT NULL,
    verify_nonce boolean DEFAULT true NOT NULL,
    tls_verify boolean DEFAULT true NOT NULL,
    tls_ca_cert text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.oidc_group_mappings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    oidc_config_id uuid NOT NULL,
    oidc_group_name character varying(256) NOT NULL,
    role_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.ontology_concepts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    description text,
    parent text,
    pii boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE public.password_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    password_hash character varying(256) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.password_reset_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.permissions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    resource character varying(64) NOT NULL,
    action character varying(64) NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.pipelines (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    schedule character varying(100),
    status character varying(20) NOT NULL,
    code text NOT NULL,
    nodes_json jsonb NOT NULL,
    edges_json jsonb NOT NULL,
    config_json jsonb NOT NULL,
    dag_id character varying(255),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE TABLE public.query_favorites (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    query_text text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.query_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    query_text text NOT NULL,
    execution_time_ms integer NOT NULL,
    rows_returned integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'success'::character varying NOT NULL,
    error_message text,
    catalog character varying(128),
    schema character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    origin character varying(16) DEFAULT 'ui'::character varying NOT NULL,
    CONSTRAINT check_status CHECK (((status)::text = ANY ((ARRAY['success'::character varying, 'error'::character varying, 'timeout'::character varying, 'cancelled'::character varying])::text[])))
);

CREATE TABLE public.rls_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    description text,
    catalog_name character varying(128) NOT NULL,
    schema_name character varying(128) NOT NULL,
    table_name character varying(128) NOT NULL,
    filter_expression text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.rls_policy_roles (
    policy_id uuid NOT NULL,
    role_id uuid NOT NULL,
    is_exempt boolean DEFAULT false NOT NULL
);

CREATE TABLE public.role_permissions (
    role_id uuid NOT NULL,
    permission_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(64) NOT NULL,
    display_name character varying(128),
    description text,
    is_system boolean DEFAULT false NOT NULL,
    parent_role_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.saml_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    idp_entity_id character varying(512) NOT NULL,
    idp_sso_url character varying(512) NOT NULL,
    idp_slo_url character varying(512),
    idp_certificate text NOT NULL,
    idp_metadata_xml text,
    sp_entity_id character varying(512) DEFAULT 'datapond'::character varying NOT NULL,
    sp_acs_url character varying(512) NOT NULL,
    sp_certificate text,
    sp_private_key_encrypted text,
    attribute_mapping jsonb DEFAULT '{"name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name", "email": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress", "groups": "http://schemas.xmlsoap.org/claims/Group"}'::jsonb NOT NULL,
    sign_requests boolean DEFAULT true NOT NULL,
    want_assertions_signed boolean DEFAULT true NOT NULL,
    want_assertions_encrypted boolean DEFAULT false NOT NULL,
    allow_idp_initiated boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.saml_group_mappings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    saml_config_id uuid NOT NULL,
    saml_group_name character varying(256) NOT NULL,
    role_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.saved_transforms (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    source_namespace character varying(50) NOT NULL,
    target_namespace character varying(50) NOT NULL,
    target_table character varying(255) NOT NULL,
    sql text NOT NULL,
    schedule character varying(100),
    status character varying(50),
    dag_id character varying(255),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

CREATE TABLE public.sessions (
    id character varying(64) NOT NULL,
    user_id uuid NOT NULL,
    auth_method public.auth_method NOT NULL,
    ip_address inet,
    user_agent text,
    device_fingerprint character varying(128),
    mfa_verified boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_activity_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    terminated_at timestamp with time zone,
    terminated_reason character varying(64)
);

CREATE TABLE public.system_settings (
    key text NOT NULL,
    value text,
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE public.user_roles (
    user_id uuid NOT NULL,
    role_id uuid NOT NULL,
    granted_by uuid,
    granted_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone
);

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(320) NOT NULL,
    username character varying(128),
    display_name character varying(256),
    password_hash character varying(256),
    auth_method public.auth_method DEFAULT 'local'::public.auth_method NOT NULL,
    status public.user_status DEFAULT 'active'::public.user_status NOT NULL,
    role character varying(32) DEFAULT 'viewer'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    require_password_change boolean DEFAULT false NOT NULL,
    external_id character varying(512),
    external_provider character varying(128),
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    password_changed_at timestamp with time zone,
    failed_login_count integer DEFAULT 0 NOT NULL,
    locked_at timestamp with time zone,
    locked_until timestamp with time zone,
    mfa_enabled boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_login_at timestamp with time zone,
    deactivated_at timestamp with time zone,
    CONSTRAINT chk_local_password CHECK (((auth_method <> 'local'::public.auth_method) OR (password_hash IS NOT NULL)))
);

CREATE TABLE public.webauthn_credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    sign_count bigint DEFAULT 0 NOT NULL,
    transports text[],
    aaguid uuid,
    name character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);

ALTER TABLE ONLY public.ai_chunks
    ADD CONSTRAINT ai_chunks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ai_collections
    ADD CONSTRAINT ai_collections_name_key UNIQUE (name);

ALTER TABLE ONLY public.ai_collections
    ADD CONSTRAINT ai_collections_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.auth_audit_log
    ADD CONSTRAINT auth_audit_log_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.auth_settings
    ADD CONSTRAINT auth_settings_pkey PRIMARY KEY (key);

ALTER TABLE ONLY public.chat_action_invocations
    ADD CONSTRAINT chat_action_invocations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.chat_conversations
    ADD CONSTRAINT chat_conversations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.column_masking_policies
    ADD CONSTRAINT column_masking_policies_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.concept_terms
    ADD CONSTRAINT concept_terms_concept_id_term_key UNIQUE (concept_id, term);

ALTER TABLE ONLY public.concept_terms
    ADD CONSTRAINT concept_terms_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.connector_connections
    ADD CONSTRAINT connector_connections_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.connector_credentials_audit
    ADD CONSTRAINT connector_credentials_audit_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.connector_quality_checks
    ADD CONSTRAINT connector_quality_checks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.connector_sync_history
    ADD CONSTRAINT connector_sync_history_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.connector_sync_jobs
    ADD CONSTRAINT connector_sync_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.dashboard_shares
    ADD CONSTRAINT dashboard_shares_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.dashboards
    ADD CONSTRAINT dashboards_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ldap_configs
    ADD CONSTRAINT ldap_configs_name_key UNIQUE (name);

ALTER TABLE ONLY public.ldap_configs
    ADD CONSTRAINT ldap_configs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ldap_group_mappings
    ADD CONSTRAINT ldap_group_mappings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.masking_policy_roles
    ADD CONSTRAINT masking_policy_roles_pkey PRIMARY KEY (policy_id, role_id);

ALTER TABLE ONLY public.mfa_devices
    ADD CONSTRAINT mfa_devices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.oidc_configs
    ADD CONSTRAINT oidc_configs_name_key UNIQUE (name);

ALTER TABLE ONLY public.oidc_configs
    ADD CONSTRAINT oidc_configs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.oidc_group_mappings
    ADD CONSTRAINT oidc_group_mappings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.ontology_concepts
    ADD CONSTRAINT ontology_concepts_name_key UNIQUE (name);

ALTER TABLE ONLY public.ontology_concepts
    ADD CONSTRAINT ontology_concepts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.password_history
    ADD CONSTRAINT password_history_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.pipelines
    ADD CONSTRAINT pipelines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.query_favorites
    ADD CONSTRAINT query_favorites_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.query_history
    ADD CONSTRAINT query_history_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.rls_policies
    ADD CONSTRAINT rls_policies_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.rls_policy_roles
    ADD CONSTRAINT rls_policy_roles_pkey PRIMARY KEY (policy_id, role_id);

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id);

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.saml_configs
    ADD CONSTRAINT saml_configs_name_key UNIQUE (name);

ALTER TABLE ONLY public.saml_configs
    ADD CONSTRAINT saml_configs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.saml_group_mappings
    ADD CONSTRAINT saml_group_mappings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.saved_transforms
    ADD CONSTRAINT saved_transforms_name_key UNIQUE (name);

ALTER TABLE ONLY public.saved_transforms
    ADD CONSTRAINT saved_transforms_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (key);

ALTER TABLE ONLY public.dashboard_shares
    ADD CONSTRAINT uq_dashboard_share UNIQUE (dashboard_id, shared_with_user_id, shared_with_role_id);

ALTER TABLE ONLY public.ldap_group_mappings
    ADD CONSTRAINT uq_ldap_group_mapping UNIQUE (ldap_config_id, ldap_group_dn, role_id);

ALTER TABLE ONLY public.column_masking_policies
    ADD CONSTRAINT uq_masking_policy UNIQUE (catalog_name, schema_name, table_name, column_name, name);

ALTER TABLE ONLY public.oidc_group_mappings
    ADD CONSTRAINT uq_oidc_group_mapping UNIQUE (oidc_config_id, oidc_group_name, role_id);

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT uq_permission UNIQUE (resource, action);

ALTER TABLE ONLY public.query_favorites
    ADD CONSTRAINT uq_query_favorite_name UNIQUE (user_id, name);

ALTER TABLE ONLY public.rls_policies
    ADD CONSTRAINT uq_rls_policy_name UNIQUE (catalog_name, schema_name, table_name, name);

ALTER TABLE ONLY public.saml_group_mappings
    ADD CONSTRAINT uq_saml_group_mapping UNIQUE (saml_config_id, saml_group_name, role_id);

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);

ALTER TABLE ONLY public.webauthn_credentials
    ADD CONSTRAINT webauthn_credentials_credential_id_key UNIQUE (credential_id);

ALTER TABLE ONLY public.webauthn_credentials
    ADD CONSTRAINT webauthn_credentials_pkey PRIMARY KEY (id);

CREATE INDEX ai_chunks_coll_idx ON public.ai_chunks USING btree (collection_id);

CREATE INDEX ai_chunks_embed_idx ON public.ai_chunks USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX ai_chunks_group_idx ON public.ai_chunks USING btree (collection_id, source_group);

CREATE INDEX concept_terms_term_idx ON public.concept_terms USING btree (lower(term));

CREATE INDEX idx_api_keys_hash ON public.api_keys USING btree (key_hash);

CREATE INDEX idx_api_keys_prefix ON public.api_keys USING btree (key_prefix);

CREATE INDEX idx_api_keys_status ON public.api_keys USING btree (status);

CREATE INDEX idx_api_keys_user ON public.api_keys USING btree (user_id);

CREATE INDEX idx_audit_log_event ON public.auth_audit_log USING btree (event_type, created_at DESC);

CREATE INDEX idx_audit_log_ip ON public.auth_audit_log USING btree (ip_address);

CREATE INDEX idx_audit_log_session ON public.auth_audit_log USING btree (session_id);

CREATE INDEX idx_audit_log_target ON public.auth_audit_log USING btree (target_user_id, created_at DESC);

CREATE INDEX idx_audit_log_time ON public.auth_audit_log USING btree (created_at DESC);

CREATE INDEX idx_audit_log_user ON public.auth_audit_log USING btree (user_id, created_at DESC);

CREATE INDEX idx_chat_conversations_user ON public.chat_conversations USING btree (user_id);

CREATE INDEX idx_chat_invocations_user ON public.chat_action_invocations USING btree (user_id, created_at DESC);

CREATE INDEX idx_connector_connections_status ON public.connector_connections USING btree (status);

CREATE INDEX idx_connector_connections_type ON public.connector_connections USING btree (connector_type);

CREATE INDEX idx_connector_credentials_audit_connection ON public.connector_credentials_audit USING btree (connection_id);

CREATE INDEX idx_connector_credentials_audit_performed ON public.connector_credentials_audit USING btree (performed_at DESC);

CREATE INDEX idx_connector_sync_history_job ON public.connector_sync_history USING btree (job_id);

CREATE INDEX idx_connector_sync_history_started ON public.connector_sync_history USING btree (started_at DESC);

CREATE INDEX idx_connector_sync_history_status ON public.connector_sync_history USING btree (status);

CREATE INDEX idx_connector_sync_jobs_connection ON public.connector_sync_jobs USING btree (connection_id);

CREATE INDEX idx_connector_sync_jobs_last_run ON public.connector_sync_jobs USING btree (last_run_at DESC);

CREATE INDEX idx_connector_sync_jobs_status ON public.connector_sync_jobs USING btree (last_run_status);

CREATE INDEX idx_dashboard_shares_dashboard ON public.dashboard_shares USING btree (dashboard_id);

CREATE INDEX idx_dashboard_shares_role ON public.dashboard_shares USING btree (shared_with_role_id);

CREATE INDEX idx_dashboard_shares_user ON public.dashboard_shares USING btree (shared_with_user_id);

CREATE INDEX idx_dashboards_public ON public.dashboards USING btree (is_public, created_at DESC);

CREATE INDEX idx_dashboards_updated ON public.dashboards USING btree (updated_at DESC);

CREATE INDEX idx_dashboards_user ON public.dashboards USING btree (user_id, created_at DESC);

CREATE INDEX idx_ldap_group_mappings_config ON public.ldap_group_mappings USING btree (ldap_config_id);

CREATE INDEX idx_masking_policies_table ON public.column_masking_policies USING btree (catalog_name, schema_name, table_name);

CREATE INDEX idx_mfa_devices_status ON public.mfa_devices USING btree (user_id, status);

CREATE INDEX idx_mfa_devices_user ON public.mfa_devices USING btree (user_id);

CREATE INDEX idx_oidc_group_mappings_config ON public.oidc_group_mappings USING btree (oidc_config_id);

CREATE INDEX idx_password_history_user ON public.password_history USING btree (user_id, created_at DESC);

CREATE INDEX idx_password_reset_tokens_hash ON public.password_reset_tokens USING btree (token_hash);

CREATE INDEX idx_permissions_resource ON public.permissions USING btree (resource);

CREATE INDEX idx_quality_conn_table_time ON public.connector_quality_checks USING btree (connection_id, source_table, checked_at DESC);

CREATE INDEX idx_query_favorites_user ON public.query_favorites USING btree (user_id, created_at DESC);

CREATE INDEX idx_query_history_created ON public.query_history USING btree (created_at DESC);

CREATE INDEX idx_query_history_status ON public.query_history USING btree (status);

CREATE INDEX idx_query_history_user ON public.query_history USING btree (user_id, created_at DESC);

CREATE INDEX idx_rls_policies_table ON public.rls_policies USING btree (catalog_name, schema_name, table_name);

CREATE INDEX idx_roles_name ON public.roles USING btree (name);

CREATE INDEX idx_roles_parent ON public.roles USING btree (parent_role_id);

CREATE INDEX idx_saml_group_mappings_config ON public.saml_group_mappings USING btree (saml_config_id);

CREATE INDEX idx_sessions_active ON public.sessions USING btree (user_id, terminated_at) WHERE (terminated_at IS NULL);

CREATE INDEX idx_sessions_expires ON public.sessions USING btree (expires_at);

CREATE INDEX idx_sessions_user ON public.sessions USING btree (user_id);

CREATE INDEX idx_user_roles_expires ON public.user_roles USING btree (expires_at) WHERE (expires_at IS NOT NULL);

CREATE INDEX idx_user_roles_role ON public.user_roles USING btree (role_id);

CREATE INDEX idx_user_roles_user ON public.user_roles USING btree (user_id);

CREATE INDEX idx_users_auth_method ON public.users USING btree (auth_method);

CREATE INDEX idx_users_email ON public.users USING btree (email);

CREATE INDEX idx_users_external ON public.users USING btree (external_provider, external_id);

CREATE INDEX idx_users_status ON public.users USING btree (status);

CREATE INDEX idx_users_username ON public.users USING btree (username);

CREATE INDEX idx_webauthn_cred_user ON public.webauthn_credentials USING btree (user_id);

CREATE UNIQUE INDEX ix_pipelines_name ON public.pipelines USING btree (name);

CREATE TRIGGER trg_dashboards_updated_at BEFORE UPDATE ON public.dashboards FOR EACH ROW EXECUTE FUNCTION public.update_dashboard_updated_at();

CREATE TRIGGER trg_update_column_masking_policies_updated_at BEFORE UPDATE ON public.column_masking_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER trg_update_ldap_configs_updated_at BEFORE UPDATE ON public.ldap_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER trg_update_oidc_configs_updated_at BEFORE UPDATE ON public.oidc_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER trg_update_rls_policies_updated_at BEFORE UPDATE ON public.rls_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER trg_update_roles_updated_at BEFORE UPDATE ON public.roles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER trg_update_saml_configs_updated_at BEFORE UPDATE ON public.saml_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER trg_update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_connector_connections_updated_at BEFORE UPDATE ON public.connector_connections FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_connector_sync_jobs_updated_at BEFORE UPDATE ON public.connector_sync_jobs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE ONLY public.ai_chunks
    ADD CONSTRAINT ai_chunks_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.ai_collections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.auth_audit_log
    ADD CONSTRAINT auth_audit_log_target_user_id_fkey FOREIGN KEY (target_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.auth_audit_log
    ADD CONSTRAINT auth_audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.auth_settings
    ADD CONSTRAINT auth_settings_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.chat_action_invocations
    ADD CONSTRAINT chat_action_invocations_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.chat_action_invocations
    ADD CONSTRAINT chat_action_invocations_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.chat_conversations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chat_action_invocations
    ADD CONSTRAINT chat_action_invocations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.chat_conversations
    ADD CONSTRAINT chat_conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.column_masking_policies
    ADD CONSTRAINT column_masking_policies_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.concept_terms
    ADD CONSTRAINT concept_terms_concept_id_fkey FOREIGN KEY (concept_id) REFERENCES public.ontology_concepts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.connector_credentials_audit
    ADD CONSTRAINT connector_credentials_audit_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.connector_connections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.connector_sync_history
    ADD CONSTRAINT connector_sync_history_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.connector_sync_jobs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.connector_sync_jobs
    ADD CONSTRAINT connector_sync_jobs_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.connector_connections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.dashboard_shares
    ADD CONSTRAINT dashboard_shares_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.dashboard_shares
    ADD CONSTRAINT dashboard_shares_dashboard_id_fkey FOREIGN KEY (dashboard_id) REFERENCES public.dashboards(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.dashboard_shares
    ADD CONSTRAINT dashboard_shares_shared_with_role_id_fkey FOREIGN KEY (shared_with_role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.dashboard_shares
    ADD CONSTRAINT dashboard_shares_shared_with_user_id_fkey FOREIGN KEY (shared_with_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.dashboards
    ADD CONSTRAINT dashboards_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.ldap_group_mappings
    ADD CONSTRAINT ldap_group_mappings_ldap_config_id_fkey FOREIGN KEY (ldap_config_id) REFERENCES public.ldap_configs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.ldap_group_mappings
    ADD CONSTRAINT ldap_group_mappings_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.masking_policy_roles
    ADD CONSTRAINT masking_policy_roles_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.column_masking_policies(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.masking_policy_roles
    ADD CONSTRAINT masking_policy_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.mfa_devices
    ADD CONSTRAINT mfa_devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.oidc_group_mappings
    ADD CONSTRAINT oidc_group_mappings_oidc_config_id_fkey FOREIGN KEY (oidc_config_id) REFERENCES public.oidc_configs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.oidc_group_mappings
    ADD CONSTRAINT oidc_group_mappings_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.password_history
    ADD CONSTRAINT password_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.query_favorites
    ADD CONSTRAINT query_favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.query_history
    ADD CONSTRAINT query_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.rls_policies
    ADD CONSTRAINT rls_policies_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.rls_policy_roles
    ADD CONSTRAINT rls_policy_roles_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.rls_policies(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.rls_policy_roles
    ADD CONSTRAINT rls_policy_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_parent_role_id_fkey FOREIGN KEY (parent_role_id) REFERENCES public.roles(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.saml_group_mappings
    ADD CONSTRAINT saml_group_mappings_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.saml_group_mappings
    ADD CONSTRAINT saml_group_mappings_saml_config_id_fkey FOREIGN KEY (saml_config_id) REFERENCES public.saml_configs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.webauthn_credentials
    ADD CONSTRAINT webauthn_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
