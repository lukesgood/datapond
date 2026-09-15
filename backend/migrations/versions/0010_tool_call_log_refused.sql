-- A refused tool call is the one an auditor most wants to see: a key that asked for
-- something it may not have. The MCP server answered those without writing a row —
-- `_unknown()` returns before any logging — so "which caller tried what and was turned
-- away" was empty while successes and errors were recorded.
--
-- 0008 declared the outcome constraint inline on the column, so PostgreSQL auto-named
-- it; it is located by definition rather than by a guessed name, the way 0009 located
-- the tool constraint. Dropping a name that does not exist succeeds silently and would
-- leave the real constraint in place.
DO $$
DECLARE
    old_name text;
BEGIN
    SELECT conname INTO old_name
      FROM pg_constraint
     WHERE conrelid = 'public.tool_call_log'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%outcome%degraded%';
    IF old_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.tool_call_log DROP CONSTRAINT %I', old_name);
    END IF;
END $$;

-- NOT VALID: the new predicate is a strict superset of the one it replaces, so no
-- existing row can violate it. Validating it would scan the table under ACCESS
-- EXCLUSIVE for nothing; future inserts are still checked.
ALTER TABLE public.tool_call_log
    ADD CONSTRAINT tool_call_log_outcome_check
    CHECK (outcome IN ('ok', 'degraded', 'error', 'refused'))
    NOT VALID;
