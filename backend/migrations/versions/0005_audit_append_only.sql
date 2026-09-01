-- The audit tables become append-only in the database, not by convention.
-- Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (B3)
--
-- HONESTY NOTE — read this before assuming this is WORM. The role that runs this
-- migration is the same role the application connects as (migrations/env.py builds
-- its URL from app.database.connection.DATABASE_URL, which is the app's own
-- POSTGRES_USER/PASSWORD; helm/datapond/templates/backend-deployment.yaml wires one
-- credential pair to both). That role created security_audit_log (0004) and
-- auth_audit_log (0001_baseline), so it OWNS both tables. Per the PostgreSQL manual,
-- an owner can revoke their own ordinary privileges (the REVOKE below is real — a
-- bare UPDATE from the application's normal connection starts failing) but can
-- ALWAYS re-grant those privileges to themselves, because granting on an object you
-- own needs no privilege beyond ownership. The right to ALTER or DROP an object
-- (including dropping the trigger below) is inherent in ownership and cannot be
-- revoked from anyone by any migration. So: this stops the application's ordinary
-- code paths (a bug, a stray endpoint, a future feature that just does
-- `UPDATE security_audit_log SET ...`). It does NOT stop a caller able to run
-- arbitrary SQL as this same role (SQL injection with stacked statements, a
-- compromised maintenance shell, an operator at a psql prompt) — that caller can
-- GRANT itself the privilege back, set the escape-hatch GUC below directly, or drop
-- the trigger. A real WORM guarantee needs the application to connect as a role that
-- does NOT own these tables, granted only SELECT/INSERT — a separate credential,
-- out of scope here.

-- UPDATE is never legitimate on an audit row, under any circumstance, including
-- retention (B4 only ever deletes). Revoked unconditionally.
REVOKE UPDATE ON TABLE public.security_audit_log, public.auth_audit_log FROM CURRENT_USER;

-- Belt and suspenders on top of the REVOKE above, and the only thing at all standing
-- between DELETE and any caller: DELETE is not revoked at the table-privilege level
-- (retention needs it), so this trigger is the sole gate. It blocks UPDATE
-- unconditionally and blocks DELETE unless the escape-hatch GUC
-- 'datapond.audit_retention_delete' is set to 'on' for the current transaction — set
-- only by prune_security_audit_log()/prune_auth_audit_log() below, and only for the
-- duration of their own DELETE.
CREATE OR REPLACE FUNCTION public.reject_audit_log_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('datapond.audit_retention_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION
        'audit_append_only: % on %.% is not permitted; retention deletes must go '
        'through prune_security_audit_log()/prune_auth_audit_log()',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

DROP TRIGGER IF EXISTS security_audit_log_append_only ON public.security_audit_log;
CREATE TRIGGER security_audit_log_append_only
    BEFORE UPDATE OR DELETE ON public.security_audit_log
    FOR EACH ROW EXECUTE FUNCTION public.reject_audit_log_mutation();

DROP TRIGGER IF EXISTS auth_audit_log_append_only ON public.auth_audit_log;
CREATE TRIGGER auth_audit_log_append_only
    BEFORE UPDATE OR DELETE ON public.auth_audit_log
    FOR EACH ROW EXECUTE FUNCTION public.reject_audit_log_mutation();

-- The sanctioned deletion path B4 (retention) must call. SECURITY DEFINER does not
-- add a privilege boundary here — the definer is the same owning role, see the note
-- at the top of this file — but it does give retention exactly one function to call,
-- and this migration exactly one place that ever sets the escape-hatch GUC to 'on'.
-- Anything that deletes from these tables without going through one of these two
-- functions gets rejected by the trigger above.
CREATE OR REPLACE FUNCTION public.prune_security_audit_log(cutoff_ts timestamptz)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
DECLARE
    deleted_count bigint;
BEGIN
    PERFORM set_config('datapond.audit_retention_delete', 'on', true);
    DELETE FROM public.security_audit_log WHERE occurred_at < cutoff_ts;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    PERFORM set_config('datapond.audit_retention_delete', 'off', true);
    RETURN deleted_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.prune_auth_audit_log(cutoff_ts timestamptz)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
DECLARE
    deleted_count bigint;
BEGIN
    PERFORM set_config('datapond.audit_retention_delete', 'on', true);
    DELETE FROM public.auth_audit_log WHERE created_at < cutoff_ts;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    PERFORM set_config('datapond.audit_retention_delete', 'off', true);
    RETURN deleted_count;
END;
$$;
