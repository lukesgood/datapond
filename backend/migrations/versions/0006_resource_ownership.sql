-- A source can belong to someone, and be shared.
-- Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (D1)
--
-- `ai_collections`, `dashboards`, `query_history` and `rls_policies` all carry an
-- owner. `connector_connections` and `saved_transforms` do not, so the data-source
-- side of this product is shared by everyone: anyone holding `connector:write` can
-- edit or delete a connector someone else created, because there is no column that
-- says whose it is. This adds one, plus the two membership tables D2's enforcement
-- will read.

-- owner_id is nullable, and it must stay that way. Every connector_connections row
-- that exists today was created before this column did, so there is nothing to
-- backfill it with — a NOT NULL version of this column would have to either fail
-- the migration outright or force every existing connector onto a made-up owner. The
-- second option is worse than the first: the moment D2 starts checking ownership, a
-- forced owner is a connector that just became invisible to every other user who
-- could see it a moment ago. NULL means "visible to everyone", the same meaning it
-- already has on ai_collections.owner_id — so leaving every existing row NULL is
-- what keeps every existing deployment's connectors visible after this migration
-- runs, not a gap to close later.
--
-- ON DELETE SET NULL, not CASCADE: deleting the person who happened to register a
-- connector must not delete the connector — a team's data source can easily outlive
-- the one account that created it. SET NULL drops the ownership, which is exactly
-- the state ("visible to everyone") this column is designed to fall back to; CASCADE
-- would delete the row, and with it every credential and sync history the team's
-- pipelines depend on.
ALTER TABLE public.connector_connections
    ADD COLUMN IF NOT EXISTS owner_id uuid
        REFERENCES public.users (id) ON DELETE SET NULL;

-- Same column, same reasoning, same table shape as connector_connections above:
-- every saved_transforms row that exists today has no owner, and must keep meaning
-- "visible to everyone" rather than being forced onto one.
ALTER TABLE public.saved_transforms
    ADD COLUMN IF NOT EXISTS owner_id uuid
        REFERENCES public.users (id) ON DELETE SET NULL;

-- Naming a connector's members, mirroring ai_collection_members (0003) exactly: the
-- only way to hand someone else a connector today is to make them the owner or leave
-- it public. This is the row that means "this one other person may reach it" without
-- either.
CREATE TABLE IF NOT EXISTS public.connector_members (
    -- The connector being shared. CASCADE: once the connector is gone there is
    -- nothing left for this row to be a grant to.
    connection_id uuid NOT NULL
        REFERENCES public.connector_connections (id) ON DELETE CASCADE,
    -- The person granted access. CASCADE in the other direction too: a deleted user
    -- cannot still hold a grant, and a later account reusing the same email must not
    -- silently inherit it.
    user_id       uuid NOT NULL
        REFERENCES public.users (id) ON DELETE CASCADE,
    -- Two roles, not a bitmask: D2 only needs "can read" and "can write", and a CHECK
    -- that only knows two literal values catches a typo at migration time instead of
    -- a silent no-match when D2 queries it.
    role          text NOT NULL CHECK (role IN ('reader', 'editor')),
    -- Who made the grant. SET NULL rather than CASCADE: the grant should survive the
    -- granter's own account being deleted — a reader should not lose access because
    -- the admin who added them left.
    granted_by    uuid REFERENCES public.users (id) ON DELETE SET NULL,
    granted_at    timestamptz NOT NULL DEFAULT now(),
    -- One grant per (connector, user): granting the same person twice should change
    -- their role, not create a second row for D2's enforcement query to reconcile.
    PRIMARY KEY (connection_id, user_id)
);

-- The query D2 runs on every list/read/test-connection/sync/schedule/edit/delete is
-- "which connectors may this user reach" — a lookup keyed on user_id, the opposite
-- direction from the primary key above. Without this index that lookup is a
-- sequential scan of every grant ever made, on every request that touches a
-- connector.
CREATE INDEX IF NOT EXISTS idx_connector_members_user_id
    ON public.connector_members USING btree (user_id);

-- Naming a transform's members. Same shape, same reasoning as connector_members
-- above — a saved transform is a data-producing pipeline definition, not analysis
-- output, so it belongs with connectors in this migration rather than with
-- ai_collection_members.
CREATE TABLE IF NOT EXISTS public.transform_members (
    transform_id uuid NOT NULL
        REFERENCES public.saved_transforms (id) ON DELETE CASCADE,
    user_id      uuid NOT NULL
        REFERENCES public.users (id) ON DELETE CASCADE,
    role         text NOT NULL CHECK (role IN ('reader', 'editor')),
    granted_by   uuid REFERENCES public.users (id) ON DELETE SET NULL,
    granted_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (transform_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_transform_members_user_id
    ON public.transform_members USING btree (user_id);
