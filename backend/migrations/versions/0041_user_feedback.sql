-- Problem reports and feature requests filed from the console (Assistant panel footer,
-- app/api/feedback.py). Expand only: a new table the previous release never reads.
CREATE TABLE IF NOT EXISTS public.user_feedback (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL CHECK (kind IN ('bug', 'feature')),
    title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    body            text NOT NULL DEFAULT '' CHECK (length(body) <= 5000),
    page            text CHECK (length(page) <= 500),
    app_version     text CHECK (length(app_version) <= 64),
    user_agent      text CHECK (length(user_agent) <= 300),
    created_by      uuid REFERENCES public.users(id) ON DELETE SET NULL,
    created_by_name text,
    status          text NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'planned', 'done', 'dismissed')),
    admin_note      text CHECK (length(admin_note) <= 2000),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_feedback_status_created
    ON public.user_feedback (status, created_at DESC);
CREATE INDEX IF NOT EXISTS user_feedback_created_by
    ON public.user_feedback (created_by, created_at DESC);
