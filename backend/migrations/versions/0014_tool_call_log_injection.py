"""The tool call log counts instruction-shaped text found in retrieved content.

Revision ID: 0014_tool_call_log_injection
Revises: 0013_tool_call_log_response
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0014_tool_call_log_injection"
down_revision: Union[str, None] = "0013_tool_call_log_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Dropping a column a previous release may still select is what
    # app/migration_rules.py refuses outright; a defaulted integer costs nothing to keep.
    pass
