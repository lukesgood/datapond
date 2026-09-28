"""A collection can narrow retrieval to the chunks a caller's attributes match.

Revision ID: 0017_chunk_access
Revises: 0016_api_key_rotated_event
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0017_chunk_access"
down_revision: Union[str, None] = "0016_api_key_rotated_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Both columns stay: dropping a column a previous release may still select is
    # what app/migration_rules.py refuses outright, and both are inert when unused.
    pass
