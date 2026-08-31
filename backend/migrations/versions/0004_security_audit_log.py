"""security audit log — a record of authorization decisions the caller cannot switch off

`query_history` is the closest thing this product had to an audit trail, and
`QueryExecuteRequest.save_history=false` lets the caller turn it off for their own
query. Authorization denials had no equivalent anywhere: a 403 left no trace, so a
credential probing the API for what it can and cannot reach was invisible. This adds
the table `app/security_audit.py` writes to — every `require_permission` denial, and
every allow of a write-shaped permission.

Additive only: one new table and its two indexes. Nothing existing is touched, so
there is no contract to break and no expand/contract step to follow.

Revision ID: 0004_security_audit_log
Revises: 0003_collection_members
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0004_security_audit_log"
down_revision: Union[str, None] = "0003_collection_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade() -> None:
    # Additive, so this one is reversible: dropping the table loses only the audit
    # rows the feature itself recorded, not anything another revision depends on.
    op.get_bind().exec_driver_sql(
        "DROP TABLE IF EXISTS public.security_audit_log;"
    )
