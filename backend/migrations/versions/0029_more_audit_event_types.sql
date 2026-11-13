-- Audit event types written since 2.6 that the enum lacked. The audit insert is
-- best-effort, so these rows were dropped silently (caught live 2026-11-13; pinned by
-- tests/test_audit_event_types.py). ADD VALUE is additive and safe for either release.
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'catalog_exported';
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'catalog_mirror_diverged';
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'sync_target_recreated';
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'sync_jobs_pruned';
