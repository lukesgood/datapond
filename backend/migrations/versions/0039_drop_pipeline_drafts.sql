-- The declarative pipeline builder was removed in 2.7 (release 2.7.0-3093865, which
-- shipped at 0038 and no longer reads public.pipelines). Its drafts table is dropped
-- only when empty: a deployment that still holds drafts keeps the table and its rows
-- for the operator to export or drop by hand.
DO $$
BEGIN
    IF to_regclass('public.pipelines') IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM public.pipelines) THEN
            DROP TABLE public.pipelines;
        ELSE
            RAISE NOTICE 'public.pipelines still holds builder drafts; left in place';
        END IF;
    END IF;
END $$;
