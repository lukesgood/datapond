-- How much instruction-shaped text the retrieved content carried.
--
-- Document content reaches agents through MCP tools and a model's context through RAG,
-- so an ingested document can address the caller's model directly. app/guardrails/
-- injection.py finds the shapes that do this; nothing masks or blocks them, because
-- legitimate documents quote the same phrases and mangling them would corrupt real
-- answers.
--
-- Recording the count is what makes it actionable: an operator can see which collection
-- began producing instruction-shaped text, and when. NOT NULL DEFAULT 0 because "no
-- findings" and "this row predates the check" are both honestly zero here — unlike a
-- response body, a count of nothing is the same fact either way.
ALTER TABLE public.tool_call_log
    ADD COLUMN IF NOT EXISTS injection_flags integer NOT NULL DEFAULT 0;
