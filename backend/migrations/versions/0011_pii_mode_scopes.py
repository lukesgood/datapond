"""A collection or a caller can be held to a stricter PII guardrail mode.

Revision ID: 0011_pii_mode_scopes
Revises: 0010_tool_call_log_refused
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0011_pii_mode_scopes"
down_revision: Union[str, None] = "0010_tool_call_log_refused"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The constraints go; the columns stay. Dropping a column the previous release may
    # still select is the one thing app/migration_rules.py refuses outright, and a NULL
    # column nothing reads costs nothing to leave behind.
    run_sql(
        op.get_bind(),
        "ALTER TABLE public.ai_collections DROP CONSTRAINT IF EXISTS ai_collections_pii_mode_check; "
        "ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_pii_mode_check;",
    )
