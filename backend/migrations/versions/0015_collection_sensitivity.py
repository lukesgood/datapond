"""A collection carries a sensitivity label that governs masking and egress together.

Revision ID: 0015_collection_sensitivity
Revises: 0014_tool_call_log_injection
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0015_collection_sensitivity"
down_revision: Union[str, None] = "0014_tool_call_log_injection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The constraint goes; the column stays. Dropping a column a previous release may
    # still select is what app/migration_rules.py refuses outright.
    run_sql(
        op.get_bind(),
        "ALTER TABLE public.ai_collections "
        "DROP CONSTRAINT IF EXISTS ai_collections_sensitivity_check;",
    )
