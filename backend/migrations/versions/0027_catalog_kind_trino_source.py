"""data_catalogs.kind admits 'trino_source' (see the .sql).

Revision ID: 0027_catalog_kind_trino_source
Revises: 0026_sample_db_role

Downgrade is a no-op: narrowing the check back would refuse the rows 2.5 registered, and
a wider check costs older code nothing (it never writes that kind).
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0027_catalog_kind_trino_source"
down_revision: Union[str, None] = "0026_sample_db_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    pass
