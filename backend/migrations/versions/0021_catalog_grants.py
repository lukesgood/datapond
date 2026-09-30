"""Per-caller catalog access: who may use a data catalog.

Revision ID: 0021_catalog_grants
Revises: 0020_catalog_audit_events
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0021_catalog_grants"
down_revision: Union[str, None] = "0020_catalog_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The table stays: the previous release never reads it, and dropping grants an
    # administrator wrote would silently reopen every restricted catalog on the next
    # upgrade. The enum value cannot be dropped and is equally harmless.
    pass
