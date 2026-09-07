-- backend/migrations/versions/0008_tool_call_log.sql
-- One row per successful data-tool call: who, which tool, which collection or tables,
-- what came back. security_audit_log records authorization *decisions* and deliberately
-- skips allows on read permissions; this table records the other fact — that a tool
-- returned data — with the columns that fact needs. Design:
-- docs/superpowers/specs/2026-09-07-positioning-gap-closure-design.md §2.
--
-- request_masked / request_hash are derived from text AFTER the pii_ko guard ran.
-- Nothing raw is written here.
CREATE TABLE IF NOT EXISTS public.tool_call_log (
    id               bigserial PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT now(),
    actor_id         uuid REFERENCES public.users (id) ON DELETE SET NULL,
    actor_username   text NOT NULL DEFAULT '',
    actor_kind       text NOT NULL CHECK (actor_kind IN ('human', 'service')),
    tool             text NOT NULL CHECK (tool IN ('ai.search', 'ai.rag', 'ai.sql', 'query.execute')),
    resource_kind    text NOT NULL CHECK (resource_kind IN ('collection', 'tables', 'none')),
    resource         text[] NOT NULL DEFAULT '{}',
    request_hash     text NOT NULL,
    request_masked   text,
    hit_count        integer NOT NULL DEFAULT 0,
    citation_sources text[] NOT NULL DEFAULT '{}',
    pii_masked       integer NOT NULL DEFAULT 0,
    outcome          text NOT NULL CHECK (outcome IN ('ok', 'degraded', 'error')),
    duration_ms      integer,
    client_address   text,
    via              text NOT NULL DEFAULT 'api'
);
CREATE INDEX IF NOT EXISTS idx_tool_call_log_actor
    ON public.tool_call_log USING btree (actor_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_call_log_time
    ON public.tool_call_log USING btree (occurred_at DESC);

-- Same append-only contract as 0005, same honesty note: the application role owns this
-- table, so this stops ordinary code paths, not a caller running arbitrary SQL as the
-- owner. reject_audit_log_mutation() already exists from 0005 and is reused unchanged.
REVOKE UPDATE ON TABLE public.tool_call_log FROM CURRENT_USER;

DROP TRIGGER IF EXISTS tool_call_log_append_only ON public.tool_call_log;
CREATE TRIGGER tool_call_log_append_only
    BEFORE UPDATE OR DELETE ON public.tool_call_log
    FOR EACH ROW EXECUTE FUNCTION public.reject_audit_log_mutation();

-- The only sanctioned delete path; app/audit_retention.py calls it and nothing else.
CREATE OR REPLACE FUNCTION public.prune_tool_call_log(cutoff_ts timestamptz)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
DECLARE
    deleted_count bigint;
BEGIN
    PERFORM set_config('datapond.audit_retention_delete', 'on', true);
    DELETE FROM public.tool_call_log WHERE occurred_at < cutoff_ts;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    PERFORM set_config('datapond.audit_retention_delete', 'off', true);
    RETURN deleted_count;
END;
$$;
