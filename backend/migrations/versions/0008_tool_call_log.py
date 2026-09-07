"""tool call log — one row per successful data-tool call.

Revision ID: 0008_tool_call_log
Revises: 0007_seed_roles
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0008_tool_call_log"
down_revision: Union[str, None] = "0007_seed_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    run_sql(
        op.get_bind(),
        "DROP FUNCTION IF EXISTS public.prune_tool_call_log(timestamptz); "
        "DROP TABLE IF EXISTS public.tool_call_log;",
    )
