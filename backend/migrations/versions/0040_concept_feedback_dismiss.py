"""Concept feedback: source "feedback" for segments, and dismissed suggestions (see the .sql).

Revision ID: 0040_concept_feedback_dismiss
Revises: 0039_drop_pipeline_drafts
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0040_concept_feedback_dismiss"
down_revision: Union[str, None] = "0039_drop_pipeline_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.concept_feedback_dismissals")
