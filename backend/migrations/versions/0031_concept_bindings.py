"""Concept bindings: which column a business concept is (see the .sql).

Revision ID: 0031_concept_bindings
Revises: 0030_connector_pause_audit
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0031_concept_bindings"
down_revision: Union[str, None] = "0030_connector_pause_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.concept_bindings")
