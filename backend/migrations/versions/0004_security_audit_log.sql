-- The audit trail an authorization decision writes, whether or not the caller wants
-- one written. `query_history` is the closest thing this product had before this —
-- and `save_history=false` lets the caller turn that one off. A denial had no
-- equivalent anywhere: a 403 left no trace, so a credential probing the API for what
-- it can and cannot reach was invisible.
-- Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (B2)

CREATE TABLE IF NOT EXISTS public.security_audit_log (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- SET NULL, not CASCADE: a deleted account's own past denials/allows are exactly
    -- the kind of row an investigation needs *after* the account is gone. The
    -- username below is kept alongside so the row still reads once the id no longer
    -- resolves to anyone.
    actor_id        uuid REFERENCES public.users (id) ON DELETE SET NULL,
    actor_username  text NOT NULL DEFAULT '',
    -- The permission (or role, for the handful of gates that are still role-based —
    -- require_admin's callers write 'role:admin' here) the route required. Free text
    -- rather than a foreign key into app/permissions.py's vocabulary: that set is
    -- allowed to change shape without a migration, and a historical row naming a
    -- permission that no longer exists is still the true record of what was checked
    -- at the time.
    permission      text NOT NULL,
    route           text NOT NULL DEFAULT '',
    method          text NOT NULL DEFAULT '',
    -- Exactly two values. A CHECK here is the second half of the same rule
    -- app/security_audit.py's build_row() enforces in Python — belt and suspenders,
    -- because the table also outlives whatever process wrote to it.
    outcome         text NOT NULL CHECK (outcome IN ('allowed', 'denied')),
    reason          text NOT NULL DEFAULT '',
    -- Nullable: not every caller of record() has a real client (an internal
    -- automation principal, a unit test), and a NULL here is honest about that where
    -- a placeholder string would not be.
    client_address  text,
    occurred_at     timestamptz NOT NULL DEFAULT now()
);

-- "What did this actor do" — an investigation starts from a person or a service
-- account, not from a permission name.
CREATE INDEX IF NOT EXISTS idx_security_audit_log_actor
    ON public.security_audit_log USING btree (actor_id, occurred_at DESC);

-- "What was denied recently" — the operational question this table exists to answer
-- day to day. A partial index: only 'denied' rows are ever queried this way, and
-- indexing every 'allowed' row too (most of the table, since privileged allows are
-- recorded as well) would cost writes for a scan pattern that never asks about them.
CREATE INDEX IF NOT EXISTS idx_security_audit_log_denied_recent
    ON public.security_audit_log USING btree (occurred_at DESC)
    WHERE outcome = 'denied';
