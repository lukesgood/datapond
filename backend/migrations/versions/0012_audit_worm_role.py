"""A non-owning application role, so the audit tables are append-only in fact.

Revision ID: 0012_audit_worm_role
Revises: 0011_pii_mode_scopes
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0012_audit_worm_role"
down_revision: Union[str, None] = "0011_pii_mode_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    # The role is left in place: dropping it would fail the moment anything is still
    # connected as it, and on a deployment that has cut over, dropping it is an
    # outage. Only the default privileges are undone, so a later migration's tables
    # stop being granted automatically.
    run_sql(
        op.get_bind(),
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM datapond_app; "
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM datapond_app;",
    )
