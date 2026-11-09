"""The glue catalog's engine name is Trino's (2.4: Athena removed).

Revision ID: 0025_glue_engine_catalog_is_trino
Revises: 0024_ai_budget_caps

Until 2.4 the AWS Single-Node Reference ran Amazon Athena, which calls the Glue catalog
`AwsDataCatalog`; the registry row seeded on that deployment carries that name as both
`name` and `engine_catalog`. The engine is now the in-cluster Trino, whose catalog is
`iceberg` (TRINO_CATALOG), so only `engine_catalog` changes here. The registry `name`
stays `AwsDataCatalog` on purpose: stored metric versions, joins, chunk sources and RLS
policies carry it, `catalog_registry.resolve()` accepts either name, and
`rls.engine._policy_key` canonicalises through the registry. Nothing else is rewritten.
Idempotent: a second run matches no row.

Data-only and env-dependent, so the statement is built here and executed through the
shared `run_sql` helper (raw cursor, no parameters — see app/migrations.py); there is
no .sql companion because the target name is not a constant.
"""
import os
import re
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql

revision: str = "0025_glue_engine_catalog_is_trino"
down_revision: Union[str, None] = "0024_ai_budget_caps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def engine_catalog_name(env=os.environ) -> str:
    """What Trino calls the default catalog: TRINO_CATALOG, else `iceberg`. Interpolated
    into SQL, so it must be a bare identifier — anything else is refused, not quoted."""
    name = (env.get("TRINO_CATALOG") or "iceberg").strip() or "iceberg"
    if not _IDENT.match(name):
        raise ValueError(f"TRINO_CATALOG is not a bare identifier: {name!r}")
    return name


def upgrade_statement(name: str) -> str:
    return ("UPDATE public.data_catalogs SET engine_catalog = '" + name + "' "
            "WHERE kind = 'glue' AND engine_catalog = 'AwsDataCatalog'")


def downgrade_statement(name: str) -> str:
    return ("UPDATE public.data_catalogs SET engine_catalog = 'AwsDataCatalog' "
            "WHERE kind = 'glue' AND name = 'AwsDataCatalog' AND engine_catalog = '" + name + "'")


def upgrade() -> None:
    run_sql(op.get_bind(), upgrade_statement(engine_catalog_name()))


def downgrade() -> None:
    run_sql(op.get_bind(), downgrade_statement(engine_catalog_name()))
