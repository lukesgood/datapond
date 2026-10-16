-- The model spend cap an operator set for a caller, shared by every backend pod.
--
-- The cap itself is enforced by the model gateway, which also holds it; DataPond checks
-- it again before each model call (app/ai_budget.assert_within_cap) because the
-- gateway judges spend it writes asynchronously. That check cached the gateway's answer
-- per pod, so with two pods a cap set through one was not seen by the other for up to
-- its cache lifetime (seen live 2026-10-16: HTTP 200 at a cap of 0). Every pod reads
-- this row instead, on every call.
--
-- user_id is users.id as text (a service account is a user). Clearing a cap deletes
-- the row: the gateway's cap applies again, including a deployment default
-- (litellm_settings.max_end_user_budget_id). Grants arrive through 0012's ALTER DEFAULT
-- PRIVILEGES for datapond_app.
CREATE TABLE IF NOT EXISTS public.ai_budget_caps (
    user_id     text PRIMARY KEY,
    max_budget  double precision NOT NULL CHECK (max_budget >= 0),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
