"""system events — durable infrastructure event history

Kubernetes Events expire after an hour and are reachable only through pods that still
exist, so the pod worth asking about is the one that cannot be asked about. This adds
the table that outlives both.

Additive only: two new tables and their indexes. Nothing existing is touched, so there
is no contract to break and no expand/contract step to follow.

Revision ID: 0002_system_events
Revises: 0001_baseline
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0002_system_events"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade() -> None:
    # Additive, so this one is reversible: dropping the tables loses only the history
    # the feature itself collected.
    op.get_bind().exec_driver_sql(
        "DROP TABLE IF EXISTS public.system_event_state; "
        "DROP TABLE IF EXISTS public.system_events;"
    )
