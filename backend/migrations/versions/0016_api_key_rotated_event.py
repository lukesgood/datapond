"""Key rotation has an audit event type.

Revision ID: 0016_api_key_rotated_event
Revises: 0015_collection_sensitivity
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0016_api_key_rotated_event"
down_revision: Union[str, None] = "0015_collection_sensitivity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value, and rows may already carry it. Leaving it
    # is harmless: the previous release never writes it.
    pass
