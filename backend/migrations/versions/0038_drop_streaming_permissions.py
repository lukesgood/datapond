"""Drop the legacy 'streaming' permission rows (see the .sql).

Revision ID: 0038_drop_streaming_permissions
Revises: 0037_source_schedule_runs
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0038_drop_streaming_permissions"
down_revision: Union[str, None] = "0037_source_schedule_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The module is gone; the rows are not restored.
    pass
