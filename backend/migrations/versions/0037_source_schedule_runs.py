"""Columns for scheduled source syncs run by the backend (see the .sql).

Revision ID: 0037_source_schedule_runs
Revises: 0036_drop_concept_parent_text
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0037_source_schedule_runs"
down_revision: Union[str, None] = "0036_drop_concept_parent_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("ALTER TABLE public.connector_connections "
               "DROP COLUMN IF EXISTS schedule_last_status, "
               "DROP COLUMN IF EXISTS schedule_anchor_at, "
               "DROP COLUMN IF EXISTS schedule_set_by")
