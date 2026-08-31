-- The roles the product authorises from, in the database that stores policy bindings.
-- Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (review)
--
-- `roles` is created empty by 0001_baseline. The two INSERT statements that ever
-- filled it live in `schema/auth.sql` and `schema/rls_migration.sql`, applied by a
-- startup bootstrap that no longer runs — migrations replaced it. So on a database
-- built from migrations the table stays empty, and the governance features keyed on
-- it fail without saying so: `GET /governance/rls/roles` returns an empty list, and
-- creating a policy for `data_scientist` runs
--   INSERT INTO rls_policy_roles (policy_id, role_id) SELECT $1, id FROM roles WHERE name = $2
-- against no rows — zero inserted, no error raised, a policy bound to nobody. With
-- RLS_DEFAULT_DENY off that policy then filters nothing at all, while the UI reports
-- it as saved.
--
-- The list is app/permissions.py's KNOWN_ROLES, which is what the API actually
-- authorises from; tests/test_role_seed_migration.py checks this file against it, so
-- a role added there without a row here fails rather than silently binding to nothing.
--
-- ON CONFLICT DO NOTHING, not DO UPDATE: an installation that predates Alembic
-- already carries these rows from schema/auth.sql, possibly with a display name an
-- administrator edited. Seeding must be a no-op on those, not a correction of them —
-- the point is that the row exists, not that its prose matches this file.
--
-- No `Contract-of` line: this inserts rows and changes no shape. app/migration_rules.py
-- fires on DROP TABLE / DROP COLUMN / RENAME / SET NOT NULL, none of which appear here.
INSERT INTO public.roles (name, display_name, description, is_system) VALUES
    ('admin',            'Administrator',     'Full platform access. Manages users, roles, settings, and every resource.', true),
    ('data_engineer',    'Data Engineer',     'Connects sources, runs syncs and transforms, and writes through the query engine.', true),
    ('ai_engineer',      'AI Engineer',       'Builds knowledge collections, ingests into them, and spends model tokens.', true),
    ('data_scientist',   'Data Scientist',    'Queries, notebooks, experiments, and knowledge collections.', true),
    ('business_analyst', 'Business Analyst',  'Reads with SELECT, saves dashboards, and browses notebooks.', true),
    ('auditor',          'Auditor',           'Read-only governance policies, audit log, and spend. Writes nothing.', true),
    ('viewer',           'Viewer',            'Reads the catalog, knowledge collections, and runs SELECT queries.', true)
ON CONFLICT (name) DO NOTHING;
