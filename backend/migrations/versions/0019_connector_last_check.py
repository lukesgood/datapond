"""A source's status records when it was last checked, and what the check said.

Revision ID: 0019_connector_last_check
Revises: 0018_data_catalogs
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0019_connector_last_check"
down_revision: Union[str, None] = "0018_data_catalogs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The columns stay: a previous release never selects them, and dropping a column
    # a newer release may still read is what app/migration_rules.py refuses.
    pass
