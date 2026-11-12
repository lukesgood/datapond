-- One writer per table when two catalogs see the same Iceberg table (app/table_links.py).
--
-- The catalog export registers a table of one catalog in another without copying data;
-- the table then has an owner (written through) and a mirror (read-only). DataPond refuses
-- writes to a mirror and routes its reads to the owner; app/mirror_freshness.py keeps the
-- mirror's registration current and flags commits made through it from outside.
-- Names are engine catalog names, lower case.
CREATE TABLE IF NOT EXISTS public.catalog_table_links (
    mirror_catalog        text NOT NULL,
    mirror_schema         text NOT NULL,
    mirror_table          text NOT NULL,
    owner_catalog         text NOT NULL,
    owner_schema          text NOT NULL,
    owner_table           text NOT NULL,
    location              text NOT NULL,
    -- the metadata file the mirror was last registered at; a different current file that
    -- is also not the owner's means someone committed through the mirror
    mirror_metadata_file  text NOT NULL,
    status                text NOT NULL DEFAULT 'fresh'
                          CHECK (status IN ('fresh', 'stale', 'diverged', 'error')),
    detail                text NULL,
    checked_at            timestamptz NULL,
    refreshed_at          timestamptz NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mirror_catalog, mirror_schema, mirror_table),
    CHECK ((mirror_catalog, mirror_schema, mirror_table) <> (owner_catalog, owner_schema, owner_table))
);

-- The catalog a sync job writes into; NULL = the engine's default catalog (as before).
ALTER TABLE public.connector_sync_jobs
    ADD COLUMN IF NOT EXISTS target_catalog text NULL;
