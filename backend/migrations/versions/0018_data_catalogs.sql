-- A registry of the data catalogs DataPond reads.
--
-- One catalog used to be implied by env (ICEBERG_CATALOG_BACKEND + QUERY_ENGINE) and a
-- pyiceberg singleton. A customer with several — Glue catalogs across accounts, several
-- Polaris catalogs, an Iceberg REST catalog — had nowhere to say so, and the Polaris
-- reader merged every catalog it could see into one list. Each catalog is now a row.
--
-- name            what DataPond calls it; also the name SQL uses for it (the default is
--                 `AwsDataCatalog` on Athena and `iceberg` on Trino — exactly the value
--                 rls_policies.catalog_name already holds, so stored policies match)
-- engine_catalog  the catalog the query engine knows it as (Trino catalog / Athena data
--                 catalog)
-- config          non-secret settings (warehouse, uri, region, catalog id)
-- secret_ref      where a credential lives, never the credential itself
--
-- The backend seeds the default row from env on first start (app/catalog_registry.py);
-- until then an empty table means "the env default", which is today's behaviour.
-- Grants arrive through 0012's ALTER DEFAULT PRIVILEGES for datapond_app.
CREATE TABLE IF NOT EXISTS public.data_catalogs (
    name            text PRIMARY KEY CHECK (name ~ '^[A-Za-z0-9_]+$'),
    kind            text NOT NULL CHECK (kind IN ('glue', 'iceberg_rest', 'polaris')),
    engine_catalog  text NOT NULL CHECK (engine_catalog ~ '^[A-Za-z0-9_]+$'),
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,
    secret_ref      text NULL,
    is_default      boolean NOT NULL DEFAULT false,
    enabled         boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- At most one default: two-part SQL names resolve against it, and two defaults would
-- make `sales.orders` mean whichever row a query happened to read first.
CREATE UNIQUE INDEX IF NOT EXISTS data_catalogs_one_default
    ON public.data_catalogs ((true)) WHERE is_default;
