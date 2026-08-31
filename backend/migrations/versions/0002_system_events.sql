-- Durable record of infrastructure state changes.
-- Design: docs/superpowers/specs/2026-08-27-system-event-history-design.md

CREATE TABLE IF NOT EXISTS public.system_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- One repeating condition is one row. This is what makes the collector's polling
    -- idempotent: re-reading the same window lands on the row already here.
    dedup_key   text NOT NULL UNIQUE,
    kind        text NOT NULL,
    severity    text NOT NULL,
    source      text NOT NULL,
    object      text NOT NULL DEFAULT '',
    message     text NOT NULL DEFAULT '',
    details     jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now(),
    occurrences integer NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_system_events_last_seen
    ON public.system_events USING btree (last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_system_events_severity
    ON public.system_events USING btree (severity, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_system_events_kind
    ON public.system_events USING btree (kind, last_seen DESC);

-- What the collector observed last tick, so detection survives its own restart.
-- Node reboot is the reason this is a table and not a variable: the backend restarts
-- when the node does, and an in-memory previous boot time would be gone exactly when
-- it was needed.
CREATE TABLE IF NOT EXISTS public.system_event_state (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
