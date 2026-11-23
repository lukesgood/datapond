"""Concept parent by id, not by name (see the .sql).

Revision ID: 0033_concept_parent_id
Revises: 0032_concept_feedback
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0033_concept_parent_id"
down_revision: Union[str, None] = "0032_concept_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("UPDATE public.ontology_concepts c SET parent = p.name FROM public.ontology_concepts p "
               "WHERE p.id = c.parent_id")
    op.execute("DROP INDEX IF EXISTS public.ontology_concepts_parent")
    op.execute("ALTER TABLE public.ontology_concepts DROP COLUMN IF EXISTS parent_id")
