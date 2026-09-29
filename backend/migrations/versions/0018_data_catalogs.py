"""A registry of the data catalogs DataPond reads, instead of one implied by env.

Revision ID: 0018_data_catalogs
Revises: 0017_chunk_access
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0018_data_catalogs"
down_revision: Union[str, None] = "0017_chunk_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The table stays: dropping one a previous release may still read is what
    # app/migration_rules.py refuses, and an unused registry changes nothing — an empty
    # table means "the env default", which is exactly what the previous release did.
    pass
