-- Audit event types for pausing and resuming a source (POST /api/connectors/{id}/pause and
-- /resume, 2.7). ADD VALUE is additive and safe for either release.
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'connector_paused';
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'connector_resumed';
