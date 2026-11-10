-- data_catalogs.kind admits the Phase 2 kind.
--
-- 0018 created the registry with CHECK (kind IN ('glue', 'iceberg_rest', 'polaris')).
-- 2.5 registers every Trino-backed connection as a row of kind 'trino_source'
-- (app/connectors/source_catalog.register); the first CI run of 2.5 hit the check:
-- new row for relation "data_catalogs" violates check constraint "data_catalogs_kind_check".
-- The list below is app.catalog_registry.KINDS, pinned by a test.
ALTER TABLE public.data_catalogs DROP CONSTRAINT IF EXISTS data_catalogs_kind_check;
ALTER TABLE public.data_catalogs
    ADD CONSTRAINT data_catalogs_kind_check
    CHECK (kind IN ('glue', 'iceberg_rest', 'polaris', 'trino_source'));
