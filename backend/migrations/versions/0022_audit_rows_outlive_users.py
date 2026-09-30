"""Audit rows keep the id they were written with; deleting a user no longer touches them.

Revision ID: 0022_audit_rows_outlive_users
Revises: 0021_catalog_grants
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0022_audit_rows_outlive_users"
down_revision: Union[str, None] = "0021_catalog_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Not restored: once an account has been deleted, its audit rows name an id that
    # no longer exists, and re-adding the constraint would fail (or, NOT VALID, would
    # break the next delete again). The previous release never relied on it.
    pass
