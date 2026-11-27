"""Problem reports and feature requests filed from the console (see the .sql).

Revision ID: 0041_user_feedback
Revises: 0040_concept_feedback_dismiss
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0041_user_feedback"
down_revision: Union[str, None] = "0040_concept_feedback_dismiss"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.user_feedback")
