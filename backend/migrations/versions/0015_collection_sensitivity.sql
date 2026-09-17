-- One label that decides both how hard a collection is masked and where its content
-- may be sent.
--
-- Three mechanisms governed this separately and could disagree: the collection ACL
-- (who reads it), ai_collections.pii_mode (how hard it is masked, 0011), and
-- AI_EGRESS_POLICY (whether any content may leave, deployment-wide). An operator who
-- marked a collection `block` still had its text embedded by a cloud provider, because
-- egress was a property of the deployment and masking was a property of the collection.
--
-- sensitivity is the collection-level statement of what the data IS; app/sensitivity.py
-- derives both consequences from it. NULL means "unlabelled" — every existing row —
-- and derives nothing, so this migration changes no behaviour on its own.
--
-- It only ever tightens. A `public` label cannot loosen a deployment that masks or a
-- deployment that is local-only, for the same reason pii_ko resolves the strictest mode:
-- a per-row value that could weaken a deployment-wide guarantee is not a guarantee.
ALTER TABLE public.ai_collections ADD COLUMN IF NOT EXISTS sensitivity text;

-- NOT VALID: every existing row is NULL, so there is nothing to scan, and a typo in a
-- future UPDATE is still refused. An unrecognised label would otherwise derive nothing
-- and silently behave as unlabelled — the opposite of what an operator setting it meant.
ALTER TABLE public.ai_collections
    ADD CONSTRAINT ai_collections_sensitivity_check
    CHECK (sensitivity IS NULL OR sensitivity IN
           ('public', 'internal', 'confidential', 'restricted')) NOT VALID;
