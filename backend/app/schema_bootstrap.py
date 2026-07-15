"""
Base schema bootstrap — applies backend/schema/auth.sql and queries.sql on a
fresh database so a clean install (incl. air-gap) comes up with the core auth and
query tables (users / roles / sessions / ldap_configs / dashboards / query_history …).

These two files are first-run bootstrap DDL, not re-runnable migrations: they contain
`CREATE TYPE … AS ENUM`, plain `CREATE INDEX`, and seed `INSERT`s that are not
idempotent. Rather than rewrite 700+ lines to be re-entrant, we guard on a sentinel
table — if it already exists the database is already bootstrapped and we skip. This
makes startup a no-op on existing installs (e.g. the live cluster) and a one-time
bootstrap on an empty DB, with no error spam.

Ordering matters: auth.sql (creates `users`) must run before rls_migration.sql, which
ALTERs `users` and references it. main.py calls ensure_base_schema() before
ensure_rls_schema(). Best-effort — never raises, so a DB hiccup can't block startup.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"

# (sql file, sentinel table) — if the sentinel exists, the file was already applied.
_BOOTSTRAP = [
    ("auth.sql", "users"),
    ("queries.sql", "dashboards"),
    ("connectors.sql", "connector_connections"),
]


async def _apply_if_absent(pool, filename: str, sentinel: str) -> bool:
    """Apply schema/<filename> only when <sentinel> table is absent. Never raises."""
    path = _SCHEMA_DIR / filename
    try:
        async with pool.acquire() as conn:
            if await conn.fetchval("SELECT to_regclass($1)", sentinel) is not None:
                logger.debug(f"[schema] {filename} skipped — '{sentinel}' already present")
                return False
            sql = path.read_text()
            await conn.execute(sql)
        logger.info(f"[schema] {filename} applied (fresh DB bootstrap)")
        return True
    except FileNotFoundError:
        logger.warning(f"[schema] {filename} not found at {path}")
        return False
    except Exception as e:
        logger.warning(f"[schema] {filename} bootstrap skipped: {e}")
        return False


async def ensure_base_schema(pool) -> None:
    """Bootstrap core auth + query schema on a fresh DB. Best-effort, idempotent."""
    for filename, sentinel in _BOOTSTRAP:
        await _apply_if_absent(pool, filename, sentinel)
