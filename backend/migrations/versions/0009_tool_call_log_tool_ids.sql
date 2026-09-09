-- 0008 constrained `tool` to the four data tools it knew about. The MCP server
-- (docs/superpowers/specs/2026-09-09-mcp-read-server-design.md) logs one row per tool
-- call, and for the twenty-three actions whose executors do not reach an /ai/* route it
-- writes a fallback row carrying the action id: catalog.find_tables, spend.summarize.
--
-- The constraint is rewritten, not removed. An unconstrained column would let a typo
-- become a permanent row in a table with an append-only trigger and no UPDATE — there
-- is no correcting it afterwards. The pattern admits any registered action id shape
-- (lowercase words either side of one dot) and still rejects free text, an empty
-- string, and anything with whitespace.
--
-- The old constraint is located by definition rather than by name: 0008 declared it
-- inline on the column, so PostgreSQL auto-named it, and dropping a guessed name would
-- silently succeed while leaving the real constraint in place.
DO $$
DECLARE
    old_name text;
BEGIN
    SELECT conname INTO old_name
      FROM pg_constraint
     WHERE conrelid = 'public.tool_call_log'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%tool%ai.search%';
    IF old_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.tool_call_log DROP CONSTRAINT %I', old_name);
    END IF;
END $$;

-- NOT VALID: the new predicate is a strict superset of the one it replaces, so no
-- existing row can violate it — validating that by scanning the table gains nothing
-- and would hold ACCESS EXCLUSIVE on tool_call_log for the length of the scan. Future
-- inserts are still checked; only that redundant initial scan is skipped.
ALTER TABLE public.tool_call_log
    ADD CONSTRAINT tool_call_log_tool_check
    CHECK (tool IN ('ai.search', 'ai.rag', 'ai.sql', 'query.execute')
           OR tool ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$')
    NOT VALID;
