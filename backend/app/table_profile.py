"""A table's profile from its own statistics, without scanning it.

`SHOW STATS` gives the row count and, per column, the null fraction, an estimate of
distinct values and (for numbers and dates) the lowest and highest value; on Iceberg
these come from the table's metadata and manifests, so a profile of a million rows costs
what a profile of ten does, and describes the whole table rather than a 100-row sample.
`$snapshots` gives when data arrived and how. Both were checked on the live reference
on 2026-11-23.

Statistics are table-wide, so they answer to the same rules as a query:
- a caller whose rows are filtered by a row policy gets no table-wide figures (they
  would count rows the caller cannot see) — only the column list and the reason;
- a column a mask hides from the caller, or bound to a PII concept, shows its null
  fraction and distinct count but never its lowest and highest value;
- default-deny or a refused table is refused here too.
"""
import logging
from typing import Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)


def parse_stats(rows: Iterable[list]) -> dict:
    """SHOW STATS rows → {rows, columns: [{name, nulls, distinct, low, high}]}. The last
    row (column_name NULL) carries the row count."""
    out, total = [], None
    for r in rows:
        name, _size, distinct, nulls, row_count, low, high = (list(r) + [None] * 7)[:7]
        if name is None:
            total = row_count
            continue
        out.append({"name": name, "nulls": nulls, "distinct": distinct, "low": low, "high": high})
    return {"rows": int(total) if total is not None else None, "columns": out}


def redact(profile: dict, hidden: Set[str]) -> dict:
    """Drop lowest/highest values for `hidden` columns (masked or PII)."""
    cols = []
    for c in profile["columns"]:
        if c["name"].lower() in hidden:
            c = dict(c, low=None, high=None, hidden=True)
        cols.append(c)
    return dict(profile, columns=cols)


def parse_snapshots(rows: Iterable[list]) -> List[dict]:
    out = []
    for committed_at, operation, summary in rows:
        summary = summary or {}
        out.append({"at": committed_at.isoformat() if hasattr(committed_at, "isoformat") else str(committed_at),
                    "operation": operation,
                    "added_records": _int(summary.get("added-records")),
                    "total_records": _int(summary.get("total-records"))})
    return out


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def governance(user: dict, catalog: str, namespace: str, table: str) -> dict:
    """{restricted: bool, masked: set[column]} for `SELECT * FROM` the table as this
    caller, through the same enforcement as /queries/execute. Raises PermissionError
    when the table is refused."""
    from app.api import queries
    if not (queries.RLS_ENABLED and queries._RLS_IMPORTS_OK):
        return {"restricted": False, "masked": set()}
    from app.rls import loader
    from app.rls.engine import RlsDenied, enforce
    ctx = await loader.load_user_context(user)
    policies = await loader.load_policies()
    masks = await loader.load_masks()
    try:
        res = enforce(f'SELECT * FROM "{catalog}"."{namespace}"."{table}"', ctx, policies, masks)
    except RlsDenied as d:
        raise PermissionError(d.message)
    by_id = {str(m.id): m for m in masks}
    return {"restricted": bool(res.applied_policy_ids),
            "masked": {by_id[i].column.lower() for i in res.applied_mask_ids if i in by_id}}


async def pii_columns(catalog: str, namespace: str, table: str) -> Set[str]:
    """Columns of this table bound (approved) to a PII concept."""
    try:
        from app.api.connectors import get_db_pool
        from app.api.ontology import load_concepts, ontology_enabled
        from app.semantic import concept_store
        if not ontology_enabled():
            return set()
        pool = await get_db_pool()
        pii = {c["name"] for c in await load_concepts(pool) if c.get("pii")}
        key = (catalog.lower(), namespace.lower(), table.lower())
        return {b["column"] for b in await concept_store.list_bindings(pool, ("approved",))
                if b["concept"] in pii and b["role"] != "filter"
                and (b["catalog"], b["namespace"], b["table"]) == key}
    except Exception as e:
        logger.info("[profile] PII bindings unavailable: %s", e)
        return set()


def read(catalog: str, namespace: str, table: str, iceberg: bool) -> dict:
    """Statistics and (Iceberg only) the last 10 snapshots, with the service identity."""
    from app.api.trino_util import trino_conn
    cur = trino_conn(timeout=30).cursor()
    cur.execute(f'SHOW STATS FOR "{catalog}"."{namespace}"."{table}"')
    out = parse_stats(cur.fetchall())
    out["snapshots"] = []
    if iceberg:
        try:
            cur.execute(f'SELECT committed_at, operation, summary FROM "{catalog}"."{namespace}"."{table}$snapshots" '
                        "ORDER BY committed_at DESC LIMIT 10")
            out["snapshots"] = parse_snapshots(cur.fetchall())
        except Exception as e:
            logger.info("[profile] snapshots of %s.%s.%s: %s", catalog, namespace, table, e)
    return out
