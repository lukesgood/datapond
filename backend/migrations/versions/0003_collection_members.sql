-- Naming a collection's members, so "shared with" can mean three people instead of
-- everyone or nobody.
-- Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (A2)

CREATE TABLE IF NOT EXISTS public.ai_collection_members (
    -- The collection being shared. CASCADE, not RESTRICT: once the collection is
    -- gone there is nothing left for this row to be permission to, so leaving it
    -- behind would just be a grant to a name that no longer resolves.
    collection_id uuid NOT NULL
        REFERENCES public.ai_collections (id) ON DELETE CASCADE,
    -- The person granted access. Same CASCADE reasoning in the other direction: a
    -- deleted user cannot still hold a grant, and re-registering the same email
    -- later must not silently inherit the old account's access.
    user_id       uuid NOT NULL
        REFERENCES public.users (id) ON DELETE CASCADE,
    -- Two roles, not a permissions bitmask, because A3 only needs to answer two
    -- questions ("can read", "can write") and a CHECK that only knows two literal
    -- values catches a typo at migration time instead of a silent no-match at query
    -- time.
    role          text NOT NULL CHECK (role IN ('reader', 'editor')),
    -- Who made the grant, kept for the audit trail a shared collection needs the
    -- moment access stops being all-or-nothing. SET NULL rather than CASCADE: the
    -- grant this row represents should survive the granter's own account being
    -- deleted — losing a reader's access because the admin who added them left is
    -- not the behavior anyone wants.
    granted_by    uuid REFERENCES public.users (id) ON DELETE SET NULL,
    granted_at    timestamptz NOT NULL DEFAULT now(),
    -- One grant per (collection, user): granting the same person twice should
    -- change their role, not create a second row for A3's enforcement query to
    -- reconcile. A composite primary key gets this for free and needs no separate
    -- unique index.
    PRIMARY KEY (collection_id, user_id)
);

-- The query A3 runs on every list/read/search/ingest/delete is "which collections may
-- this user reach", i.e. a lookup keyed on user_id — the opposite direction from the
-- primary key above, which is only useful once collection_id is already known. Without
-- this index that lookup is a sequential scan of every grant ever made, on every
-- request that touches a collection.
CREATE INDEX IF NOT EXISTS idx_ai_collection_members_user_id
    ON public.ai_collection_members USING btree (user_id);
