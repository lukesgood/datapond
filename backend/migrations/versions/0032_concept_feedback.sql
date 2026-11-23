-- One row per /ai/sql generation while concepts are on: the question (PII-masked, as the
-- tool-call log stores it), the concepts it matched, joins that equated keys of two
-- different concepts (found in the first statement, and left after the repair round),
-- and the literal conditions of the final statement. Read only in aggregate, by
-- governance readers, to suggest concepts, aliases and segments (Semantic model ›
-- Concepts). Rows older than 90 days are removed as new ones arrive.
CREATE TABLE IF NOT EXISTS public.concept_feedback (
    id               bigserial PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT now(),
    actor_id         uuid REFERENCES public.users (id) ON DELETE SET NULL,
    question_masked  text NOT NULL,
    concepts         text[] NOT NULL DEFAULT '{}',
    conflicts        text[] NOT NULL DEFAULT '{}',
    conflicts_left   text[] NOT NULL DEFAULT '{}',
    literals         jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_concept_feedback_time
    ON public.concept_feedback USING btree (occurred_at DESC);
