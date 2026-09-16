-- Where the PII guardrail mode can be set, besides the deployment-wide env var.
--
-- PII_GUARDRAIL_MODE was the only control: one value for a collection of public FAQ
-- text and one holding resident registration numbers alike (POSITIONING_FIT_AUDIT
-- §2.4). These two columns let a collection, or a caller, be held to something
-- stricter. NULL means "inherit" — the deployment default applies — which is what
-- every existing row gets, so this migration changes no behaviour on its own.
--
-- Loosening is impossible by construction: app/guardrails/pii_ko.py resolves the
-- effective mode as the STRICTEST of the deployment default and whatever scope the
-- request is in, so `off` here cannot soften a deployment that masks.
ALTER TABLE public.ai_collections ADD COLUMN IF NOT EXISTS pii_mode text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS pii_mode text;

-- NOT VALID: every existing row is NULL, so there is nothing to scan, and a typo in a
-- future UPDATE is still refused. A bad value would otherwise be read as a mode nobody
-- recognises, and `strictest()` ignores unknown values — silently inheriting instead of
-- applying what an operator thought they set.
ALTER TABLE public.ai_collections
    ADD CONSTRAINT ai_collections_pii_mode_check
    CHECK (pii_mode IS NULL OR pii_mode IN ('off', 'mask', 'block')) NOT VALID;

ALTER TABLE public.users
    ADD CONSTRAINT users_pii_mode_check
    CHECK (pii_mode IS NULL OR pii_mode IN ('off', 'mask', 'block')) NOT VALID;
