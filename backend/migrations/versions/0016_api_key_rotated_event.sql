-- Key rotation writes an auth audit row of its own. audit_event_type is an enum, and
-- record_auth_event swallows a failed insert (auditing must not fail the request), so
-- without this value every rotation would leave no trace at all — silently.
--
-- ADD VALUE is additive: the previous release never writes it and reads rows by
-- column, so it runs against either release.
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'api_key_rotated';
