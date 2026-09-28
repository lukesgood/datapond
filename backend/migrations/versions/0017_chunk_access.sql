-- A collection can narrow retrieval to the chunks a caller's attributes match.
--
-- The collection ACL decides whether a caller may search a collection; inside it every
-- chunk was equally visible. chunk_access holds one rule, {"metadata_key": ...,
-- "user_attribute": ...}: a chunk is retrieved only when metadata[metadata_key] is one
-- of the caller's users.attributes[user_attribute] values. See app/chunk_access.py.
-- NULL — every existing row — means no rule, so this changes no behaviour on its own.
ALTER TABLE public.ai_collections ADD COLUMN IF NOT EXISTS chunk_access jsonb;

-- How many of the nearest chunks the rule kept from this caller. Recorded, never
-- returned: the caller must not learn about documents it may not see, but an operator
-- must be able to see that a rule is doing work. Zero is honest for older rows — no
-- rule existed to withhold anything.
ALTER TABLE public.tool_call_log
    ADD COLUMN IF NOT EXISTS chunks_withheld integer NOT NULL DEFAULT 0;
