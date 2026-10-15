"""Semantic layer: governed metric definitions, their versions, approved joins.

Revision ID: 0023_semantic_metrics
Revises: 0022_audit_rows_outlive_users
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0023_semantic_metrics"
down_revision: Union[str, None] = "0022_audit_rows_outlive_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Not dropped: a version is what an audit row's `metric:<name>@v<N>` points at.
    # Dropping the tables would leave every such citation unresolvable.
    pass
