"""The restricted login role the SQL sample sources connect through.

Revision ID: 0026_sample_db_role
Revises: 0025_glue_engine_catalog_trino

Until Phase 2 the two sample connectors (e-commerce, finance) carried the application's
own PostgreSQL credentials, so a sample source was a path to every table the backend
can reach. They are now Trino catalogs, and Trino connects as `datapond_sample`, a role
that may only SELECT from the sample databases (the grants are issued per database when
a sample is created — app/api/connectors.py grant_sample_role). This migration creates
the role, or rotates its password when the chart's SAMPLE_DB_PASSWORD changed.

Env-dependent and data-only, like 0025: the statement is built here and run through the
shared `run_sql` helper (raw cursor, no parameters). Without SAMPLE_DB_PASSWORD the role
is not provisioned and the sample routes refuse with a 409 that names the setting.
Downgrade is a no-op: the role may own grants on sample databases, and dropping it
would fail or strand them.
"""
import logging
import os
import re
from typing import Optional, Sequence, Union

from alembic import op

from app.migrations import run_sql

revision: str = "0026_sample_db_role"
down_revision: Union[str, None] = "0025_glue_engine_catalog_trino"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger("alembic.runtime.migration")

ROLE = "datapond_sample"
_PASSWORD = re.compile(r"^[A-Za-z0-9]{16,64}$")


def sample_password(env=os.environ) -> Optional[str]:
    """SAMPLE_DB_PASSWORD, or None when unset. Interpolated into SQL, so only the chart's
    alphabet (randAlphaNum, 16–64 characters) is accepted — anything else is refused."""
    value = (env.get("SAMPLE_DB_PASSWORD") or "").strip()
    if not value:
        return None
    if not _PASSWORD.match(value):
        raise ValueError("SAMPLE_DB_PASSWORD must be 16–64 letters and digits "
                         "(the chart generates it with randAlphaNum 32)")
    return value


def upgrade_statement(password: str) -> str:
    return ("DO $$ BEGIN "
            f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN "
            f"ALTER ROLE {ROLE} WITH LOGIN PASSWORD '{password}'; "
            f"ELSE CREATE ROLE {ROLE} LOGIN PASSWORD '{password}'; "
            "END IF; END $$;")


def upgrade() -> None:
    password = sample_password()
    if password is None:
        log.warning("[0026] SAMPLE_DB_PASSWORD unset; %s not provisioned "
                    "(sample SQL sources will refuse until it is set)", ROLE)
        return
    run_sql(op.get_bind(), upgrade_statement(password))


def downgrade() -> None:
    # The role may own grants on sample databases; dropping it is an operator's call.
    return None
