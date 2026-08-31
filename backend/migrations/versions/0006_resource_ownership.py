"""a source can belong to someone, and be shared

`ai_collections`, `dashboards`, `query_history` and `rls_policies` all carry an
owner. `connector_connections` and `saved_transforms` carry none — so the analysis
side of this product is per-user and the data-source side is shared by everyone. If
one person connects their S3 bucket and another connects their Postgres, each sees
the other's connector and — holding `connector:write` — can edit or delete it. That
is what stops several people running their own scenarios today, not the shared
catalog: the missing owner.

Schema only, following A2 (0003_collection_members) exactly. Nothing here reads
`owner_id`, `connector_members` or `transform_members` yet — enforcement is D2, a
separate change, so a row in either member table authorizes nobody until that lands.

`owner_id` is nullable on both tables and must stay that way: every connector and
transform that exists today has no owner, and NULL already means "visible to
everyone" for `ai_collections.owner_id`. A NOT NULL version of this column has
nothing to backfill existing rows with — it would have to either fail the migration
or force an owner onto every row that exists today, which is an outage the moment D2
starts checking ownership: every existing source would go invisible to everyone but
its forced owner. See the header comment in `0006_resource_ownership.sql` for the
full reasoning, including why `ON DELETE SET NULL` rather than CASCADE.

Additive only: two new columns, two new tables, two new indexes. Nothing existing is
touched, so there is no contract to break and no `Contract-of` line needed —
`app/migration_rules.py`'s violations are DROP TABLE / DROP COLUMN / RENAME / SET NOT
NULL, and none of those appear here.

Revision ID: 0006_resource_ownership
Revises: 0005_audit_append_only
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0006_resource_ownership"
down_revision: Union[str, None] = "0005_audit_append_only"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade() -> None:
    # Additive, so this reverses cleanly: dropping the tables loses only the grants
    # this feature itself recorded, and dropping the columns loses only ownership
    # this feature itself assigned. Nothing else depends on either.
    op.get_bind().exec_driver_sql(
        """
        DROP TABLE IF EXISTS public.transform_members;
        DROP TABLE IF EXISTS public.connector_members;
        ALTER TABLE public.saved_transforms DROP COLUMN IF EXISTS owner_id;
        ALTER TABLE public.connector_connections DROP COLUMN IF EXISTS owner_id;
        """
    )
