"""Drop the retired pipeline builder's drafts table when empty (see the .sql).

Contract-of: 0038_drop_streaming_permissions

The release deployed at 0038 (2.7.0-3093865) removed every reader of
public.pipelines, so the previous release no longer reads it.

Revision ID: 0039_drop_pipeline_drafts
Revises: 0038_drop_streaming_permissions
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql_file

revision: str = "0039_drop_pipeline_drafts"
down_revision: Union[str, None] = "0038_drop_streaming_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The builder is gone; the table is not recreated.
    pass
