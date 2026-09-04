"""Governance actions: which row filters and column masks apply, and to whom.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
from typing import Callable, Dict, List, Literal, Optional

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
    """Same counts as `GET /governance/stats`, minus its zero-that-isn't-zero bug: that
    route computes `pii_detections = ... if pii_tables else 0`, so "no scan could run"
    and "scanned, found nothing" both report as 0. This executor calls the same pieces
    `get_governance_stats` does directly (rather than going through that route
    function) so it can tell the two apart: when `_scan_pii_tables()` returns None,
    `pii_detections` is left out of the stats entirely and a `not_checked` note is
    added instead — the same shape `pii_summary` uses. The route itself is unchanged
    and out of scope; the Governance page still reads it as before.

    `get_db_context` is the context manager that exists for callers outside a request;
    without it the Depends default arrives as `db` and fails inside SQLAlchemy. Both
    the DB query and `_scan_pii_tables()` are synchronous — a ~10s Trino connect, or a
    sequential walk of up to 200 Glue tables with a per-table S3 GET — so the whole
    load runs via `asyncio.to_thread`, same as the real (`def`, threadpool-bound)
    route, rather than blocking this `async def` executor's event loop.
    """
    import asyncio
    from datetime import date

    from sqlalchemy import func

    from app.api.governance import _scan_pii_tables
    from app.database.connection import get_db_context
    from app.models.query import QueryHistory

    def _load() -> dict:
        with get_db_context() as db:
            today = date.today()
            queries_today = (
                db.query(func.count(QueryHistory.id))
                .filter(func.date(QueryHistory.created_at) == today)
                .scalar()
                or 0
            )
        stats: dict = {"queries_today": queries_today}
        pii_tables = _scan_pii_tables()  # None if no scan ran
        if pii_tables is None:
            stats["not_checked"] = [
                "No PII scan could run on this deployment — the scan needs the "
                "Trino query engine or Glue catalog access. This is not a clean "
                "result."]
        else:
            stats["pii_detections"] = sum(len(t.pii_columns) for t in pii_tables)
        return stats

    return {"stats": await asyncio.to_thread(_load)}


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
    import asyncio

    from app.api.governance import _scan_pii_tables

    # `_scan_pii_tables()` is synchronous and can be a ~10s Trino connect or a
    # sequential walk of up to 200 Glue tables with a per-table S3 GET (see the
    # comment near governance.py:355). This executor is `async def`, so without
    # `to_thread` that work runs on the event loop instead of a threadpool, unlike
    # the real (`def`) route.
    scanned = await asyncio.to_thread(_scan_pii_tables)
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


# ── Creating a policy: a mutate, undone by deleting it ─────────────────────────
# `RlsPolicyIn` / `MaskPolicyIn` (app/api/governance.py) are what the real handlers
# take — constructed here, never passed as dicts. Both handlers are
# `(body, user: Optional[dict] = Depends(_get_current_user))`; the Depends default
# is only meaningful when FastAPI itself resolves it; called directly, `user` must
# be passed explicitly.
#
# `applicable_policies` (app/rls/engine.py) applies a policy only to roles present
# in its role_map and not marked exempt there — an empty `roles` list means the
# policy is stored but matches nobody, not that it applies to everyone. The
# preview says that plainly rather than the (misleading, opposite) alternative.

class RlsPolicyCreateParams(_Strict):
    table: str                    # "schema.table" or "catalog.schema.table"
    expression: str                # filter_expression: rows where this is true are visible
    roles: List[str] = []          # role_names — empty means the policy matches nobody
    exempt_roles: List[str] = []   # exempt_role_names
    name: Optional[str] = None
    description: Optional[str] = None
    priority: int = 0


class MaskPolicyCreateParams(_Strict):
    table: str                    # "schema.table" or "catalog.schema.table"
    column: str                    # column_name
    masking_type: Literal[
        "full", "partial_email", "partial_ssn", "partial_phone", "hash", "null",
        "custom"] = "full"
    custom_expression: Optional[str] = None
    roles: List[str] = []          # role_names — empty means the policy matches nobody
    exempt_roles: List[str] = []   # exempt_role_names
    name: Optional[str] = None
    description: Optional[str] = None


def _split_table(table: str):
    """'schema.table' or 'catalog.schema.table' -> (catalog_name, schema_name,
    table_name). Two parts default the catalog the same way the Governance page's
    policy forms do (catalog_name defaults to "iceberg", resolved at submission to
    the runtime catalog)."""
    parts = [p for p in str(table).split(".") if p]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return "iceberg", parts[0], parts[1]
    raise ValueError(
        f"table must be 'schema.table' or 'catalog.schema.table', got {table!r}")


def _roles_summary(roles: List[str]) -> str:
    return ", ".join(roles) if roles else \
        "no roles — this policy will not apply to anyone until roles are added"


def build_rls_policy_in(params: dict):
    """The real `RlsPolicyIn` (app.api.governance), from chat params."""
    from app.api.governance import RlsPolicyIn
    catalog_name, schema_name, table_name = _split_table(params["table"])
    roles = list(params.get("roles") or [])
    name = params.get("name") or f"chat-{schema_name}-{table_name}-rls"
    return RlsPolicyIn(
        name=name,
        description=params.get("description"),
        catalog_name=catalog_name,
        schema_name=schema_name,
        table_name=table_name,
        filter_expression=params["expression"],
        enabled=True,
        priority=params.get("priority") or 0,
        role_names=roles,
        exempt_role_names=list(params.get("exempt_roles") or []),
    )


def build_mask_policy_in(params: dict):
    """The real `MaskPolicyIn` (app.api.governance), from chat params."""
    from app.api.governance import MaskPolicyIn
    catalog_name, schema_name, table_name = _split_table(params["table"])
    roles = list(params.get("roles") or [])
    name = params.get("name") or f"chat-{schema_name}-{table_name}-{params['column']}-mask"
    return MaskPolicyIn(
        name=name,
        description=params.get("description"),
        catalog_name=catalog_name,
        schema_name=schema_name,
        table_name=table_name,
        column_name=params["column"],
        masking_type=params.get("masking_type") or "full",
        custom_expression=params.get("custom_expression"),
        enabled=True,
        role_names=roles,
        exempt_role_names=list(params.get("exempt_roles") or []),
    )


async def preview_create_rls_policy(params: dict, user: dict) -> dict:
    """Which table, which roles, and what the row filter actually does."""
    catalog_name, schema_name, table_name = _split_table(params["table"])
    roles = list(params.get("roles") or [])
    exempt = list(params.get("exempt_roles") or [])
    expression = params["expression"]
    summary = (f"New row filter on {schema_name}.{table_name}: {_roles_summary(roles)} "
               f"will only see rows where {expression}.")
    if exempt:
        summary += f" Exempt from it: {', '.join(exempt)}."
    return {
        "table": params["table"],
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "table_name": table_name,
        "roles": roles,
        "exempt_roles": exempt,
        "expression": expression,
        "summary": summary,
    }


async def preview_create_masking_policy(params: dict, user: dict) -> dict:
    """Which table and column, which roles, and what the mask actually does."""
    catalog_name, schema_name, table_name = _split_table(params["table"])
    roles = list(params.get("roles") or [])
    exempt = list(params.get("exempt_roles") or [])
    masking_type = params.get("masking_type") or "full"
    column = params["column"]
    rule = (params.get("custom_expression") or "a custom expression") \
        if masking_type == "custom" else f"'{masking_type}' masking"
    summary = (f"New column mask on {schema_name}.{table_name}.{column}: "
               f"{_roles_summary(roles)} will see it replaced with {rule}.")
    if exempt:
        summary += f" Exempt from it: {', '.join(exempt)}."
    return {
        "table": params["table"],
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "table_name": table_name,
        "column": column,
        "masking_type": masking_type,
        "roles": roles,
        "exempt_roles": exempt,
        "summary": summary,
    }


async def create_rls_policy_action(params: dict, user: dict) -> dict:
    from app.api.governance import create_rls_policy
    body = build_rls_policy_in(params)
    return await create_rls_policy(body, user=user)


async def create_masking_policy_action(params: dict, user: dict) -> dict:
    from app.api.governance import create_mask_policy
    body = build_mask_policy_in(params)
    return await create_mask_policy(body, user=user)


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
    Action("governance.create_rls_policy", "Create row filter",
           "Create a row-level security policy: a filter expression applied to a "
           "table for a set of roles.",
           ("*",), "governance:write", ActionKind.MUTATE, RlsPolicyCreateParams),
    Action("governance.create_masking_policy", "Create column mask",
           "Create a column-masking policy: replace one column's values for a set "
           "of roles.",
           ("*",), "governance:write", ActionKind.MUTATE, MaskPolicyCreateParams),
)

EXECUTORS: Dict[str, Callable] = {
    "governance.explain_policy": explain_policy,
    "governance.policy_coverage": policy_coverage,
    "governance.summary_stats": summary_stats,
    "governance.pii_summary": pii_summary,
    "governance.create_rls_policy": create_rls_policy_action,
    "governance.create_masking_policy": create_masking_policy_action,
}

RESOLVERS: Dict[str, Callable] = {
    "governance.explain_policy": _r("app.rls.loader", "load_policies"),
    "governance.policy_coverage": _r("app.api.governance", "rls_coverage"),
    # Not get_governance_stats: the executor above no longer calls that route
    # function (it needed to tell None from [] where that route can't), so this
    # points at the synchronous work it actually reaches for instead.
    "governance.summary_stats": _r("app.api.governance", "_scan_pii_tables"),
    "governance.pii_summary": _r("app.api.governance", "_scan_pii_tables"),
    # Not create_masking_policy: the real handler's name is create_mask_policy.
    "governance.create_rls_policy": _r("app.api.governance", "create_rls_policy"),
    "governance.create_masking_policy": _r("app.api.governance", "create_mask_policy"),
}

PREVIEWERS: Dict[str, Callable] = {
    "governance.create_rls_policy": preview_create_rls_policy,
    "governance.create_masking_policy": preview_create_masking_policy,
}
