"""tool_call_log.tool admits action ids, for the MCP server's fallback rows.

Revision ID: 0009_tool_call_log_tool_ids
Revises: 0008_tool_call_log
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0009_tool_call_log_tool_ids"
down_revision: Union[str, None] = "0008_tool_call_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    run_sql(
        op.get_bind(),
        "ALTER TABLE public.tool_call_log "
        "DROP CONSTRAINT IF EXISTS tool_call_log_tool_check;",
    )
