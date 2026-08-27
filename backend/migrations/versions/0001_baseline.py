"""baseline — the Portable Core schema

Executes 0001_baseline.sql, a pg_dump of the schema the application produces. Reading
it from a file rather than embedding it: 933 lines of DDL inside a Python string is
unreadable, and unreadable is how a schema definition goes wrong without anyone
noticing.

Runs only against a database with no application tables. One that already has them is
stamped at this revision — it is already here, and re-creating what exists would fail
every deployment that has ever run. app/migrations.py makes that decision.

There is no downgrade. Below a baseline is an empty database, and a migration that
drops 41 tables is not a thing to leave lying where someone can run it.

Revision ID: 0001_baseline
Revises:
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sql = (Path(__file__).with_suffix(".sql")).read_text()
    # As one script, not statement by statement: splitting on semicolons breaks the
    # $$-quoted function bodies, which is exactly what happened on the first attempt.
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    raise NotImplementedError(
        "There is no downgrade from the baseline. Dropping 41 tables is a restore, "
        "not a migration — see docs/DISASTER_RECOVERY.md."
    )
