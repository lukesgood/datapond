"""The tool call log records what came back, not only what was asked.

Revision ID: 0013_tool_call_log_response
Revises: 0012_audit_worm_role
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0013_tool_call_log_response"
down_revision: Union[str, None] = "0012_audit_worm_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Nothing to undo. Dropping a column a previous release may still select is what
    # app/migration_rules.py refuses outright, and two NULL columns nothing reads cost
    # nothing to leave in place.
    pass
