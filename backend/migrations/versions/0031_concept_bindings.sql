-- Concept bindings (app/semantic/concepts.py, app/api/concepts.py).
--
-- A concept in ontology_concepts ("고객") says nothing about where it lives. A binding
-- says it is this column: a key (customers.id, orders.customer_id), an attribute, or a
-- segment defined by a filter over one table (VIP 고객 = customers.tier = 'VIP').
-- Bindings are proposed (from column names and query-history joins, or by an author)
-- and approved by an administrator, like semantic_joins. A rejected or retired row is
-- kept so the same suggestion is not offered again.
-- catalog is the engine name, as SQL types it; namespace/table/column are lower case.
CREATE TABLE IF NOT EXISTS public.concept_bindings (
    id                serial PRIMARY KEY,
    concept_id        uuid NOT NULL REFERENCES public.ontology_concepts(id) ON DELETE CASCADE,
    catalog           text NOT NULL,
    namespace         text NOT NULL,
    table_name        text NOT NULL,
    column_name       text NOT NULL,
    role              text NOT NULL CHECK (role IN ('key', 'attribute', 'filter')),
    filter_sql        text NULL,
    status            text NOT NULL DEFAULT 'proposed'
                      CHECK (status IN ('proposed', 'approved', 'rejected', 'retired')),
    source            text NOT NULL
                      CHECK (source IN ('naming', 'comment', 'history', 'manual', 'openmetadata')),
    evidence          text NOT NULL DEFAULT '',
    proposed_by       uuid,
    proposed_by_name  text,
    decided_by        uuid,
    decided_by_name   text,
    decided_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK ((role = 'filter') = (filter_sql IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS concept_bindings_one
    ON public.concept_bindings (concept_id, catalog, namespace, table_name, column_name, role,
                                COALESCE(filter_sql, ''));
CREATE INDEX IF NOT EXISTS concept_bindings_table
    ON public.concept_bindings (catalog, namespace, table_name);
