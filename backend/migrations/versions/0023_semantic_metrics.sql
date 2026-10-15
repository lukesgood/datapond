-- Governed metric definitions (docs/superpowers/specs/2026-10-15-sql-semantic-layer-design.md).
--
-- A version is what an audit citation `metric:<name>@v<N>` names, so it must reproduce
-- the same SQL for as long as that row exists. Hence: versions are append-only, and a
-- dimension's join condition is copied into the version rather than referenced.
--
-- Append-only here is the same strength as the audit tables (0005): it stops the
-- application's normal code paths. The role that owns the table can still disable the
-- trigger. Never describe it as tamper-proof.
--
-- No foreign keys to users: like the audit tables after 0022, a version keeps the id
-- and the name it was written with, and deleting a user must not need to update it.

CREATE TABLE IF NOT EXISTS public.semantic_metrics (
    id               serial PRIMARY KEY,
    name             text NOT NULL UNIQUE CHECK (name ~ '^[a-z][a-z0-9_]{0,62}$'),
    label            text NOT NULL,
    description      text NOT NULL DEFAULT '',
    synonyms         text[] NOT NULL DEFAULT '{}',
    owner_id         uuid,
    owner_name       text,
    status           text NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'approved', 'retired')),
    current_version  integer,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.semantic_metric_versions (
    metric_id         integer NOT NULL REFERENCES public.semantic_metrics(id),
    version           integer NOT NULL CHECK (version >= 1),
    catalog           text NOT NULL,
    base_table        text NOT NULL,
    measure           text NOT NULL,
    filters           text,
    time_column       text,
    grains            text[] NOT NULL DEFAULT '{}',
    max_period_days   integer NOT NULL DEFAULT 366 CHECK (max_period_days BETWEEN 1 AND 3660),
    dimensions        jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by        uuid,
    created_by_name   text,
    change_note       text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    approved_by       uuid,
    approved_by_name  text,
    approved_at       timestamptz,
    PRIMARY KEY (metric_id, version)
);

CREATE TABLE IF NOT EXISTS public.semantic_joins (
    id                serial PRIMARY KEY,
    catalog           text NOT NULL,
    from_table        text NOT NULL,
    to_table          text NOT NULL,
    on_columns        jsonb NOT NULL,
    source            text NOT NULL CHECK (source IN ('history', 'naming', 'manual')),
    approved_by       uuid,
    approved_by_name  text,
    approved_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (catalog, from_table, to_table, on_columns)
);

-- The one permitted UPDATE: approving an unapproved version, changing nothing else.
CREATE OR REPLACE FUNCTION public.reject_metric_version_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.approved_at IS NULL AND NEW.approved_at IS NOT NULL
       AND (to_jsonb(NEW) - 'approved_by' - 'approved_by_name' - 'approved_at')
         = (to_jsonb(OLD) - 'approved_by' - 'approved_by_name' - 'approved_at') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'metric_version_append_only: % on %.% is not permitted; write a new version',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

DROP TRIGGER IF EXISTS semantic_metric_versions_append_only ON public.semantic_metric_versions;
CREATE TRIGGER semantic_metric_versions_append_only
    BEFORE UPDATE OR DELETE ON public.semantic_metric_versions
    FOR EACH ROW EXECUTE FUNCTION public.reject_metric_version_mutation();
