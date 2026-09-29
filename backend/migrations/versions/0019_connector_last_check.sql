-- When a source's status was last established, and what established it.
--
-- `status` was written once, from the connection test at creation, and never again:
-- a source whose password changed, or whose stored credentials could no longer be
-- decrypted, stayed "active" through every failed sync. Status now follows each real
-- contact with the source (a sync that reads it, an explicit check, a config save),
-- and these say when that was and what it said. NULL on existing rows means "never
-- checked since this column existed", which is the truth.
ALTER TABLE public.connector_connections
    ADD COLUMN IF NOT EXISTS last_checked_at timestamptz;
ALTER TABLE public.connector_connections
    ADD COLUMN IF NOT EXISTS last_check_message text;
