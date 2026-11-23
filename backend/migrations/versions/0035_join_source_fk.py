"""An approved join may come from a source foreign key (see the .sql).

Revision ID: 0035_join_source_fk
Revises: 0034_expected_null_columns
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0035_join_source_fk"
down_revision: Union[str, None] = "0034_expected_null_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("UPDATE public.semantic_joins SET source = 'manual' WHERE source = 'fk'")
    op.execute("ALTER TABLE public.semantic_joins DROP CONSTRAINT IF EXISTS semantic_joins_source_check")
    op.execute("ALTER TABLE public.semantic_joins ADD CONSTRAINT semantic_joins_source_check "
               "CHECK (source IN ('history', 'naming', 'manual'))")
