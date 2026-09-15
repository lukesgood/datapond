"""tool_call_log.outcome admits 'refused', for calls turned away before they ran.

Revision ID: 0010_tool_call_log_refused
Revises: 0009_tool_call_log_tool_ids
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0010_tool_call_log_refused"
down_revision: Union[str, None] = "0009_tool_call_log_tool_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Not an inverse: it drops the widened constraint and leaves the column
    # unconstrained rather than restoring the three-value one. Once this revision has
    # been live, refused rows may already exist, and tool_call_log is append-only with
    # no UPDATE or DELETE — restoring the narrower constraint would either fail or
    # leave rows violating it with no way to correct them. Same reasoning as 0009.
    run_sql(
        op.get_bind(),
        "ALTER TABLE public.tool_call_log "
        "DROP CONSTRAINT IF EXISTS tool_call_log_outcome_check;",
    )
