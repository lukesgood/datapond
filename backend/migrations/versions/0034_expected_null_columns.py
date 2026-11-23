"""Sync jobs: columns whose high null rate is expected (see the .sql).

Revision ID: 0034_expected_null_columns
Revises: 0033_concept_parent_id
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0034_expected_null_columns"
down_revision: Union[str, None] = "0033_concept_parent_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("ALTER TABLE public.connector_sync_jobs DROP COLUMN IF EXISTS expected_null_columns")
