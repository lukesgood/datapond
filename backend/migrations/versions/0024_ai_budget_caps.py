"""Per-caller model spend caps shared by every backend pod (see the .sql).

Revision ID: 0024_ai_budget_caps
Revises: 0023_semantic_metrics
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0024_ai_budget_caps"
down_revision: Union[str, None] = "0023_semantic_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.ai_budget_caps")
