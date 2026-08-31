"""audit tables append-only in the database, not by convention

`security_audit_log` (0004) and `auth_audit_log` (0001_baseline) were append-only only
by convention: nothing in the application chose to update or delete them, and nothing
in PostgreSQL stopped it. An audit trail the application can rewrite is not evidence —
an attacker who reaches the application reaches the record of what they did.

This revision:
  - REVOKEs UPDATE on both tables from CURRENT_USER (the role that runs this
    migration, which is the same role the application connects as — see
    `migrations/env.py`). UPDATE is never legitimate on an audit row.
  - Adds a BEFORE UPDATE OR DELETE trigger, `reject_audit_log_mutation()`, that
    raises on every UPDATE and on every DELETE except one gated by a GUC only the
    retention path sets.
  - Adds `prune_security_audit_log(cutoff_ts)` / `prune_auth_audit_log(cutoff_ts)`,
    the sanctioned deletion path task B4 (retention) is expected to call.

See the header comment in `0005_audit_append_only.sql` for the honest limit of what
this does and does not prevent: the connecting role owns both tables (it created
them), so an owner can always re-grant itself a revoked privilege and cannot be
stripped of the right to drop the trigger. This closes the ordinary-application-code
gap; it is not a WORM guarantee against a caller with arbitrary SQL as this same
role. `Contract-of` is not needed here: `app/migration_rules.py`'s violation list is
DROP TABLE / DROP COLUMN / RENAME / SET NOT NULL, and this migration's REVOKE, GRANT,
CREATE TRIGGER and CREATE FUNCTION statements are additive to the schema — no reader
of an earlier revision depends on being able to update or delete these two tables.

Revision ID: 0005_audit_append_only
Revises: 0004_security_audit_log
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0005_audit_append_only"
down_revision: Union[str, None] = "0004_security_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP TRIGGER IF EXISTS security_audit_log_append_only ON public.security_audit_log;
        DROP TRIGGER IF EXISTS auth_audit_log_append_only ON public.auth_audit_log;
        DROP FUNCTION IF EXISTS public.reject_audit_log_mutation();
        DROP FUNCTION IF EXISTS public.prune_security_audit_log(timestamptz);
        DROP FUNCTION IF EXISTS public.prune_auth_audit_log(timestamptz);
        GRANT UPDATE ON TABLE public.security_audit_log, public.auth_audit_log TO CURRENT_USER;
        """
    )
