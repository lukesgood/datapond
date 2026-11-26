-- Concept feedback follow-ups (app/semantic/concept_feedback.py). Expand only.
--
-- 1. A segment made from a feedback suggestion records source 'feedback', not
--    'history' (query history is a different suggester). Widening the CHECK is safe
--    while the previous release runs: it never writes the new value.
DO $$
DECLARE c text;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'public.concept_bindings'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%source%'
    LOOP
        EXECUTE format('ALTER TABLE public.concept_bindings DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
ALTER TABLE public.concept_bindings ADD CONSTRAINT concept_bindings_source_check
    CHECK (source IN ('naming', 'comment', 'history', 'manual', 'openmetadata', 'feedback'));

-- 2. Suggestions a person dismissed: not offered again until restored. Keyed by the
--    suggestion itself (a word; table.column=value; a join message).
CREATE TABLE IF NOT EXISTS public.concept_feedback_dismissals (
    kind              text NOT NULL CHECK (kind IN ('word', 'value', 'join')),
    key               text NOT NULL CHECK (length(key) BETWEEN 1 AND 600),
    dismissed_by      uuid,
    dismissed_by_name text,
    dismissed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, key)
);
