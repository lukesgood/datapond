-- Scheduled source syncs run in the backend (app/sync_scheduler.py), not as Airflow DAGs.
-- Expand only: three nullable columns, nothing read by an older release.
--   schedule_set_by       who saved the schedule; the run is made as them (owner when null)
--   schedule_anchor_at    when the scheduler last ran it, or when it was saved
--   schedule_last_status  the outcome of the last scheduled run
ALTER TABLE public.connector_connections
    ADD COLUMN IF NOT EXISTS schedule_set_by uuid REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS schedule_anchor_at timestamptz,
    ADD COLUMN IF NOT EXISTS schedule_last_status text;

-- A schedule that already exists starts from now: nothing it "missed" runs on upgrade.
UPDATE public.connector_connections
   SET schedule_anchor_at = now()
 WHERE schedule IS NOT NULL AND schedule <> '' AND schedule_anchor_at IS NULL;
