"""Owner/mirror links between catalogs, and the catalog a sync writes into (see the .sql).

Revision ID: 0028_catalog_table_links
Revises: 0027_catalog_kind_trino_source
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0028_catalog_table_links"
down_revision: Union[str, None] = "0027_catalog_kind_trino_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.catalog_table_links")
    op.execute("ALTER TABLE public.connector_sync_jobs DROP COLUMN IF EXISTS target_catalog")
