"""Governance actions: which row filters and column masks apply, and to whom.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
from typing import Callable, Dict, Optional

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class PolicyQuery(_Strict):
    table: Optional[str] = None


async def explain_policy(params: dict, user: dict) -> dict:
    from app.rls import loader as rls_loader
    policies = await rls_loader.load_policies()
    masks = await rls_loader.load_masks()
    if params.get("table"):
        wanted = params["table"].lower()
        policies = [p for p in policies if wanted in f"{p.schema}.{p.table}".lower()]
        masks = [m for m in masks if wanted in f"{m.schema}.{m.table}".lower()]
    return {
        "row_filters": [{"table": f"{p.schema}.{p.table}", "filter": p.filter_expression,
                         "roles": sorted(p.role_map)} for p in policies[:25]],
        "column_masks": [{"table": f"{m.schema}.{m.table}", "column": m.column,
                          "type": m.masking_type} for m in masks[:25]],
    }


async def policy_coverage(params: dict, user: dict) -> dict:
    from app.api.governance import rls_coverage
    return {"coverage": await rls_coverage(user=user)}


async def summary_stats(params: dict, user: dict) -> dict:
    """`get_governance_stats` is synchronous and takes a Session. get_db_context is the
    context manager that exists for callers outside a request; without it the Depends
    default arrives as `db` and fails inside SQLAlchemy."""
    from app.api.governance import get_governance_stats
    from app.database.connection import get_db_context
    with get_db_context() as db:
        return {"stats": get_governance_stats(db=db)}


async def pii_summary(params: dict, user: dict) -> dict:
    """PII findings as counts by table and by category.

    `_scan_pii_tables()` returns None when no scan could run — no Trino, which is the
    Portable Core default — and None is not an empty result. Reporting "no PII found"
    for a scan that never happened is the one answer here that would be actively
    misleading, so it is reported as not scanned.

    The scan is schema-level: an entry carries a column name and a detected type, never
    a value. This drops the column names too, which are not needed to answer "where is
    our exposure" at the level a summary answers it.
    """
    from app.api.governance import _scan_pii_tables

    scanned = _scan_pii_tables()
    if scanned is None:
        # No count keys here at all — not zero, not null. A model summarising this
        # sees whichever fields exist; "tables_with_pii": 0 reads exactly like a
        # clean scan once the prose is dropped, which is the one misreading this
        # action exists to prevent. Only "scanned": False and the shape itself (no
        # by_table, no by_type, no counts) can carry that distinction.
        return {
            "scanned": False,
            "not_checked": ["No PII scan could run on this deployment — the scan needs "
                            "the Trino query engine. This is not a clean result."],
        }

    by_type: dict = {}
    by_table = []
    columns = 0
    for entry in scanned:
        cols = list(getattr(entry, "pii_columns", []) or [])
        columns += len(cols)
        by_table.append({"table": getattr(entry, "table", ""), "columns": len(cols)})
        for col in cols:
            kind = str(getattr(col, "type", "") or "unknown")
            by_type[kind] = by_type.get(kind, 0) + 1

    return {
        "scanned": True,
        "tables_with_pii": len(by_table),
        "columns_with_pii": columns,
        "by_type": by_type,
        "by_table": sorted(by_table, key=lambda r: r["columns"], reverse=True),
        "not_checked": [],
    }


ACTIONS = (
    Action("governance.explain_policy", "Explain policy",
           "Which row filters and column masks apply, and to whom.",
           ("/governance",), "governance:read", ActionKind.READ, PolicyQuery),
    Action("governance.policy_coverage", "Policy coverage",
           "Which tables have a row-level policy and which have none.",
           ("*",), "governance:read", ActionKind.READ, _Strict),
    Action("governance.summary_stats", "Governance summary",
           "Counts of policies, masked columns and covered tables.",
           ("*",), "governance:read", ActionKind.READ, _Strict),
    Action("governance.pii_summary", "PII summary",
           "Where PII was detected, as counts by table and category. Reports "
           "'not scanned' rather than 'clean' when no scan could run.",
           ("*",), "governance:read", ActionKind.READ, _Strict),
)

EXECUTORS: Dict[str, Callable] = {
    "governance.explain_policy": explain_policy,
    "governance.policy_coverage": policy_coverage,
    "governance.summary_stats": summary_stats,
    "governance.pii_summary": pii_summary,
}

RESOLVERS: Dict[str, Callable] = {
    "governance.explain_policy": _r("app.rls.loader", "load_policies"),
    "governance.policy_coverage": _r("app.api.governance", "rls_coverage"),
    "governance.summary_stats": _r("app.api.governance", "get_governance_stats"),
    "governance.pii_summary": _r("app.api.governance", "_scan_pii_tables"),
}

PREVIEWERS: Dict[str, Callable] = {}
