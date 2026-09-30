-- An audit row must not depend on the row it describes still existing.
--
-- These foreign keys were ON DELETE SET NULL, so deleting a user asked Postgres to
-- UPDATE the audit rows that named it — which the append-only trigger (0012) refuses.
-- Every account that had ever called a tool, been authorised or signed in could not
-- be deleted. Each row keeps the id and the name (actor_username / user_email) it was
-- written with; nothing reads these columns as a live join that needs the constraint.
--
-- Names are PostgreSQL's defaults for the inline REFERENCES in 0004/0008 and the
-- explicit names in the baseline. IF EXISTS keeps a re-run harmless.
ALTER TABLE public.tool_call_log DROP CONSTRAINT IF EXISTS tool_call_log_actor_id_fkey;
ALTER TABLE public.security_audit_log DROP CONSTRAINT IF EXISTS security_audit_log_actor_id_fkey;
ALTER TABLE public.auth_audit_log DROP CONSTRAINT IF EXISTS auth_audit_log_user_id_fkey;
ALTER TABLE public.auth_audit_log DROP CONSTRAINT IF EXISTS auth_audit_log_target_user_id_fkey;
