"""Drop the unused text parent of a concept (see the .sql).

Contract-of: 0033_concept_parent_id

Revision ID: 0036_drop_concept_parent_text
Revises: 0035_join_source_fk
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0036_drop_concept_parent_text"
down_revision: Union[str, None] = "0035_join_source_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Bring the column back, filled from parent_id, for a release that still reads it.
    op.execute("ALTER TABLE public.ontology_concepts ADD COLUMN IF NOT EXISTS parent text")
    op.execute("UPDATE public.ontology_concepts c SET parent = p.name FROM public.ontology_concepts p "
               "WHERE p.id = c.parent_id")
