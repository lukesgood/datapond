-- A concept's parent was its name in a text column: renaming a concept silently cut
-- every narrower concept loose, and a parent could name a concept that did not exist.
-- The parent is now a reference to the concept's id; deleting a parent leaves its
-- children without one. A text parent that names no concept has nothing to point at
-- and stays unset (none on the live reference, checked 2026-11-23).
--
-- Expand only: the text column stays, unused from this release on, because the
-- previous release still reads and writes it while pods roll over. A later revision
-- drops it with `Contract-of: 0033_concept_parent_id`.
ALTER TABLE public.ontology_concepts
    ADD COLUMN IF NOT EXISTS parent_id uuid REFERENCES public.ontology_concepts (id) ON DELETE SET NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'ontology_concepts'
                 AND column_name = 'parent') THEN
        UPDATE public.ontology_concepts c SET parent_id = p.id
          FROM public.ontology_concepts p
         WHERE c.parent_id IS NULL AND c.parent IS NOT NULL
           AND p.name = c.parent AND p.id <> c.id;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ontology_concepts_parent ON public.ontology_concepts (parent_id);
