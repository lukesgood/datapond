"""collection membership — sharing a collection with named people

`ai_collections.owner_id` plus "owner NULL means everyone" is the whole access model
today. There is no row anywhere that means "this one other person may read this
collection" — the only way to hand someone a collection is to make them the owner or
make it public. This adds the table that row lives in.

Schema only. Nothing reads `ai_collection_members` yet — enforcement (checking it on
list/read/search/ingest/delete) is a separate change, so a row in this table
authorizes nobody until that lands.

Additive only: one new table and its index. Nothing existing is touched, so there is
no contract to break and no expand/contract step to follow.

Revision ID: 0003_collection_members
Revises: 0002_system_events
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0003_collection_members"
down_revision: Union[str, None] = "0002_system_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # Additive, so this one is reversible: dropping the table loses only the grants
    # the feature itself recorded, not anything another revision depends on.
    run_sql(
        op.get_bind(),
        "DROP TABLE IF EXISTS public.ai_collection_members;"
    )
