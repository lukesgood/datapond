"""
RLS schema migration runner (P0) — applies backend/schema/rls_migration.sql.

Idempotent: safe to run on every startup. Best-effort — logs and continues on
failure so a DB hiccup never blocks app startup. See docs/RLS_DESIGN.md.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).resolve().parents[2] / "schema" / "rls_migration.sql"


async def ensure_rls_schema(pool) -> bool:
    """
    Apply the RLS migration using an existing asyncpg pool. Returns True on success.
    Never raises.
    """
    try:
        sql = _SQL_PATH.read_text()
    except Exception as e:
        logger.warning(f"[rls] migration SQL not found ({_SQL_PATH}): {e}")
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(sql)
        logger.info("[rls] schema migration applied (rls_policies / masking / attributes)")
        return True
    except Exception as e:
        logger.warning(f"[rls] schema migration skipped: {e}")
        return False
