-- Columns a person marked "mostly empty is expected" (orders.shipped_at before shipping):
-- the quality check still records their null rate but no longer warns. Expand-only.
ALTER TABLE public.connector_sync_jobs ADD COLUMN IF NOT EXISTS expected_null_columns jsonb;
