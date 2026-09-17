-- What the caller actually received, alongside what they asked for.
--
-- tool_call_log recorded the request (hashed and masked), how many hits came back, and
-- which sources were cited — but nothing about the response itself. For a deployment
-- under personal-data obligations the first question an audit asks is "what did this
-- caller receive", and the table could not answer it.
--
-- Both columns are nullable and nothing backfills them: every existing row keeps NULL,
-- which reads correctly as "this call predates response recording" rather than as an
-- empty response. Only calls that produce generated text populate them today.
--
-- response_masked is masked and truncated the same way request_masked is; the log never
-- stores raw text. response_hash is the digest of the masked response in full, so two
-- rows can be compared even where the stored excerpt was cut.
ALTER TABLE public.tool_call_log ADD COLUMN IF NOT EXISTS response_hash text;
ALTER TABLE public.tool_call_log ADD COLUMN IF NOT EXISTS response_masked text;
