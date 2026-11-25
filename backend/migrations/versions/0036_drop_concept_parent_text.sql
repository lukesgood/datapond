-- Contract step of 0033_concept_parent_id. A concept's parent has been read and written
-- through parent_id since that release; the text column has been unused since, and every
-- release now running predates none of it (0033 went live 2026-11-23, a36eaa2). Dropping
-- it removes the second, stale place a parent could be read from.
ALTER TABLE public.ontology_concepts DROP COLUMN IF EXISTS parent;
