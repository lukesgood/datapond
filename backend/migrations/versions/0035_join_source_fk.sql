-- The relationship graph now reads foreign keys declared in source databases
-- (app/source_keys.py). A join proposed from one records that as its source, beside
-- query history, naming and manual. Widening a CHECK is safe while the previous release
-- runs: it never writes the new value.
DO $$
DECLARE c text;
BEGIN
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'public.semantic_joins'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%source%'
    LOOP
        EXECUTE format('ALTER TABLE public.semantic_joins DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
ALTER TABLE public.semantic_joins ADD CONSTRAINT semantic_joins_source_check
    CHECK (source IN ('history', 'naming', 'manual', 'fk'));
