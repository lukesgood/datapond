-- Who may use a data catalog (multi-catalog P3, app/catalog_access.py).
--
-- A catalog with no rows here is open to every caller that passes today's checks —
-- a deployment that never grants anything behaves exactly as before. A catalog with
-- one row or more is visible and queryable only to the users and roles named here,
-- plus signed-in administrators.
--
-- principal_kind  'user' — principal is users.id as text (a service account is a user)
--                 'role' — principal is a role name (app/permissions.py ASSIGNABLE_ROLES)
--
-- Removing a catalog removes its grants: a later catalog of the same name must not
-- inherit them. Grants arrive through 0012's ALTER DEFAULT PRIVILEGES for datapond_app.
CREATE TABLE IF NOT EXISTS public.catalog_grants (
    catalog_name    text NOT NULL REFERENCES public.data_catalogs(name) ON DELETE CASCADE,
    principal_kind  text NOT NULL CHECK (principal_kind IN ('user', 'role')),
    principal       text NOT NULL,
    created_by      uuid NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog_name, principal_kind, principal)
);

-- Replacing a catalog's grants (PUT /api/catalogs/{name}/grants) writes an auth audit
-- row; audit_event_type is an enum and that insert is best-effort, so without this
-- value the change would leave no trace. ADD VALUE is additive, as in 0020.
ALTER TYPE public.audit_event_type ADD VALUE IF NOT EXISTS 'catalog_grants_changed';
