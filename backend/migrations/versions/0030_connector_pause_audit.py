"""Audit event types for pausing and resuming a source (see the .sql).

Revision ID: 0030_connector_pause_audit
Revises: 0029_more_audit_event_types
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0030_connector_pause_audit"
down_revision: Union[str, None] = "0029_more_audit_event_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value, and rows may already carry it. Leaving it
    # is harmless: the previous release never writes it.
    pass
