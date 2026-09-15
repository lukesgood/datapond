"""Readable names for the user ids that audit and spend views would otherwise show raw.

A row in query_history, the audit stream, or the LiteLLM spend logs carries a user id.
Shown as is, an operator reads `c67dae27-cc01-...` and has to go and look the account
up. This turns ids into what a person recognises: a service account's username (its
display_name is a free-text description), otherwise the display name, the username, or
the email.

Best effort by design. An id with no users row, or a lookup that fails, simply has no
label, and the caller keeps showing the id — a missing name must never hide a row.
"""
import logging
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_LABEL = ("CASE WHEN auth_method::text = 'service' THEN username "
          "ELSE COALESCE(NULLIF(display_name, ''), username, email) END")


def _distinct(ids: Iterable[Optional[str]]) -> List[str]:
    return sorted({str(i) for i in ids if i})


def labels_sync(db, ids: Iterable[Optional[str]]) -> Dict[str, str]:
    """{user id: label} through a SQLAlchemy session. Never raises."""
    wanted = _distinct(ids)
    if not wanted:
        return {}
    try:
        rows = db.execute(
            text(f"SELECT id::text AS id, {_LABEL} AS label FROM users WHERE id::text = ANY(:ids)"),
            {"ids": wanted}).fetchall()
    except Exception as e:
        logger.warning("user labels unavailable: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return {}
    return {str(r.id): r.label for r in rows if r.label}


async def labels_async(conn, ids: Iterable[Optional[str]]) -> Dict[str, str]:
    """{user id: label} through an asyncpg connection. Never raises."""
    wanted = _distinct(ids)
    if not wanted:
        return {}
    try:
        rows = await conn.fetch(
            f"SELECT id::text AS id, {_LABEL} AS label FROM users WHERE id::text = ANY($1::text[])",
            wanted)
    except Exception as e:
        logger.warning("user labels unavailable: %s", e)
        return {}
    return {str(r["id"]): r["label"] for r in rows if r["label"]}
