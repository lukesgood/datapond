"""Governance actions: which row filters and column masks apply, and to whom.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
import inspect
from typing import Any, Callable, Dict, List, Literal, Optional

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r
from app.chat.dependents import Dependents


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
    table_name). Two parts default the catalog to the same runtime default the RLS
    engine itself resolves against — `app.rls.engine._default_catalog()`
    (RLS_DEFAULT_CATALOG or TRINO_CATALOG, else "iceberg") — and the same value
    `rls_coverage` computes inline at `app/api/governance.py:698`. On this project's
    AWS Single-Node Reference, Helm sets RLS_DEFAULT_CATALOG=AwsDataCatalog; a
    literal "iceberg" here would store a policy the engine's own lookup can never
    match, so this must not diverge from either of those two places."""
    from app.rls.engine import _default_catalog
    parts = [p for p in str(table).split(".") if p]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return _default_catalog(), parts[0], parts[1]
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


# ── Deleting a policy: destructive, and the point is what it exposes ───────────
# Deleting a row filter is not "a row disappears from a policy table" — it is "these
# roles can now see rows they cannot see today", and column masking's analogue is
# "this column stops being masked, and here is whether PII was ever found in it".
# `dependents_delete_rls_policy` / `dependents_delete_masking_policy` below compute
# that sentence. Every read they do is wrapped in its own try/except: a dependents
# list that could not be computed goes into `not_checked` with a reason, never
# silently into an empty `items` — an empty list reads as "nothing depends on this",
# which is the one claim this feature must never make about a store it could not
# read.
#
# `_policy_by_id` / `_policies_for_table` / `_mask_policy_by_id` are thin readers
# over the exact source `/governance/rls/coverage` already reads —
# `app.rls.loader.load_policies()` / `load_masks()` — not a second lookup invented
# for this task. That loader only returns *enabled* policies (see its docstring),
# same set the coverage endpoint and `explain_policy` above already work from.


class PolicyDeleteParams(_Strict):
    policy_id: str


async def _maybe_await(value: Any) -> Any:
    """`_policy_by_id` and friends are real `async def`s, but tests replace them
    with plain synchronous callables — same shape as `gate._maybe_await`, which
    exists for the identical reason: `dependents` callables may or may not be
    coroutines, and the caller should not have to know which."""
    if inspect.isawaitable(value):
        return await value
    return value


def _key(catalog: str, schema: str, table: str) -> str:
    """Same key `app.rls.coverage._key` / `app.rls.engine._policy_key` use — lower
    the qualified name before comparing. Comparing raw `schema.table` (no catalog,
    original case) conflates two different tables: a same-named table in another
    catalog reads as still covered when it is not, and a policy differing only in
    case reads as gone when the engine still applies it."""
    return f"{catalog}.{schema}.{table}".lower()


async def _policy_by_id(policy_id: str) -> Optional[dict]:
    from app.rls import loader as rls_loader
    for p in await rls_loader.load_policies():
        if str(p.id) == str(policy_id):
            return {"id": p.id, "table": f"{p.catalog}.{p.schema}.{p.table}",
                    "table_key": _key(p.catalog, p.schema, p.table),
                    "roles": [r for r, exempt in p.role_map.items() if not exempt]}
    return None


async def _policies_for_table(table_key: str) -> List[dict]:
    """Every enabled RLS policy whose qualified, lowercased key equals `table_key`
    (from `_key`) — the deleted one included, callers filter it out by id."""
    from app.rls import loader as rls_loader
    key = (table_key or "").lower()
    return [{"id": p.id, "roles": [r for r, exempt in p.role_map.items() if not exempt]}
            for p in await rls_loader.load_policies()
            if _key(p.catalog, p.schema, p.table) == key]


async def _mask_policy_by_id(policy_id: str) -> Optional[dict]:
    from app.rls import loader as rls_loader
    for m in await rls_loader.load_masks():
        if str(m.id) == str(policy_id):
            return {"id": m.id, "table": f"{m.catalog}.{m.schema}.{m.table}",
                    "table_key": _key(m.catalog, m.schema, m.table),
                    # The PII scan (app.api.governance._scan_pii_tables) keys its
                    # results as "schema.table" with no catalog — kept alongside the
                    # qualified key above so the PII lookup below can match it
                    # without conflating this reader's own catalog-qualified key.
                    "schema_table": f"{m.schema}.{m.table}",
                    "column": m.column, "rule": m.masking_type,
                    "roles": [r for r, exempt in m.role_map.items() if not exempt]}
    return None


async def _masks_for_column(table_key: str, column: str) -> List[dict]:
    """Every enabled masking policy on this exact (table_key, column) — the deleted
    one included, callers filter it out by id. The RLS twin of `_policies_for_table`:
    a mask does not stop applying just because one policy naming it was deleted."""
    from app.rls import loader as rls_loader
    key = (table_key or "").lower()
    return [{"id": m.id, "roles": [r for r, exempt in m.role_map.items() if not exempt]}
            for m in await rls_loader.load_masks()
            if _key(m.catalog, m.schema, m.table) == key and m.column == column]


async def dependents_delete_rls_policy(params: dict, user: dict) -> dict:
    d = Dependents("governance.delete_rls_policy")
    policy_id = str(params.get("policy_id") or "")

    try:
        policy = await _maybe_await(_policy_by_id(policy_id))
    except Exception as e:
        d.skipped(f"Could not read the RLS policy store to look up {policy_id!r}: {e}")
        return d.done()
    if not policy:
        d.skipped(f"No RLS policy {policy_id!r} was found in the policy store — "
                  f"what depends on it could not be determined.")
        return d.done()

    table = policy.get("table") or "(unknown table)"
    table_key = policy.get("table_key") or table.lower()
    roles = [r for r in (policy.get("roles") or []) if r]
    who = ", ".join(roles) if roles else "no roles were assigned to this policy"

    # Known from the first read alone, emitted before the second read is even
    # attempted — a failure below (the coverage check) must not discard the
    # identity of the policy actually being deleted.
    d.item("rls_policy", table, f"This row filter on {table} currently covers {who}.")

    try:
        others = [p for p in (await _maybe_await(_policies_for_table(table_key)) or [])
                  if str(p.get("id")) != policy_id]
    except Exception as e:
        d.skipped(f"Could not check whether another policy still covers {table}: {e}")
        return d.done()

    if others:
        remaining_roles = sorted({r for p in others for r in (p.get("roles") or [])})
        names = ", ".join(str(p.get("id")) for p in others)
        d.item("rls_policy", table,
               f"{table} stays row-filtered — {names} still applies"
               + (f" (to {', '.join(remaining_roles)})" if remaining_roles else "")
               + ".")
        exposed = [r for r in roles if r not in remaining_roles]
        for role in exposed:
            d.item("role", role,
                   f"{role} will see rows in {table} that are filtered out today — "
                   f"no remaining policy on this table covers that role.")
    else:
        d.item("table", table,
               f"{table} loses its only row filter — {who} will see every row in "
               f"{table}; the table becomes unfiltered, with no row filtering left.")
    return d.done()


async def dependents_delete_masking_policy(params: dict, user: dict) -> dict:
    d = Dependents("governance.delete_masking_policy")
    policy_id = str(params.get("policy_id") or "")

    try:
        policy = await _maybe_await(_mask_policy_by_id(policy_id))
    except Exception as e:
        d.skipped(f"Could not read the masking policy store to look up {policy_id!r}: {e}")
        return d.done()
    if not policy:
        d.skipped(f"No masking policy {policy_id!r} was found in the policy store — "
                  f"what depends on it could not be determined.")
        return d.done()

    table = policy.get("table") or "(unknown table)"
    table_key = policy.get("table_key") or table.lower()
    schema_table = policy.get("schema_table") or table
    column = policy.get("column") or "(unknown column)"
    rule = policy.get("rule") or "masking"
    roles = [r for r in (policy.get("roles") or []) if r]
    who = ", ".join(roles) if roles else "no roles were assigned to this policy"

    # Known from the first read alone, emitted before the second read is even
    # attempted — a failure below (the coverage check) must not discard the
    # identity of the policy actually being deleted.
    d.item("mask_policy", f"{table}.{column}",
           f"This mask on {table}.{column} ({rule}) currently applies to {who}.")

    try:
        others = [m for m in (await _maybe_await(_masks_for_column(table_key, column)) or [])
                  if str(m.get("id")) != policy_id]
    except Exception as e:
        d.skipped(f"Could not check whether another masking policy still covers "
                  f"{table}.{column}: {e}")
        return d.done()

    if others:
        # Another policy still masks this exact column — deleting this one does not
        # expose the real values, the way it would if it were the only one. Same
        # split RLS uses above: who stays covered, who is newly exposed.
        remaining_roles = sorted({r for m in others for r in (m.get("roles") or [])})
        names = ", ".join(str(m.get("id")) for m in others)
        d.item("mask_policy", f"{table}.{column}",
               f"{table}.{column} stays masked — {names} still applies"
               + (f" (to {', '.join(remaining_roles)})" if remaining_roles else "")
               + ".")
        exposed = [r for r in roles if r not in remaining_roles]
        for role in exposed:
            d.item("role", role,
                   f"{role} will see the real value of {table}.{column} — no "
                   f"remaining masking policy on this column covers that role.")
        return d.done()

    # This was the only masking policy on this column — it really does stop being
    # masked, so it is worth saying whether PII was ever found there.
    pii_note = ""
    try:
        import asyncio

        from app.api.governance import _scan_pii_tables
        scanned = await asyncio.to_thread(_scan_pii_tables)
    except Exception as e:
        d.skipped(f"The PII scan for {schema_table}.{column} failed to run: {e}")
    else:
        if scanned is None:
            d.skipped(f"No PII scan could run on this deployment — the scan needs "
                      f"the Trino query engine or Glue catalog access — so whether "
                      f"{schema_table}.{column} carries PII could not be checked.")
        else:
            # `_scan_pii_tables` only appends a table when it has at least one PII
            # hit (app/api/governance.py:396-408) — a clean table and a table that
            # was never looked at (truncated at PII_SCAN_MAX_TABLES, or its columns
            # could not be read) are both simply absent from `scanned`. Absent is
            # not evidence of clean, so it is reported as unchecked, never as "no
            # PII here" — the same None-vs-[] distinction this module documents at
            # `pii_summary` above.
            entry = next((e for e in scanned
                          if getattr(e, "table", None) == schema_table), None)
            if entry is None:
                d.skipped(f"{schema_table} was not recorded in the last PII scan — "
                          f"that means either it is clean or it was never scanned, "
                          f"and the two cannot be told apart, so whether {column} "
                          f"carries PII is not checked.")
            else:
                pii_cols = {c.column for c in getattr(entry, "pii_columns", [])}
                pii_note = (" — the last PII scan found PII in this column"
                            if column in pii_cols else
                            " — the last PII scan found no PII in this column")

    d.item("column", f"{table}.{column}",
           f"{table}.{column} stops being masked ({rule}) — {who} (and anyone else "
           f"who can query {table}) will see the real values{pii_note}.")
    return d.done()


async def preview_delete_rls_policy(params: dict, user: dict) -> dict:
    """What is being deleted, read fresh right before the card is shown — the
    dependents callable answers "what breaks"; this answers "what is this".
    """
    policy_id = str(params.get("policy_id") or "")
    try:
        policy = await _maybe_await(_policy_by_id(policy_id))
    except Exception as e:
        return {"policy_id": policy_id,
                "summary": f"Delete RLS policy {policy_id!r} — its table and roles "
                          f"could not be read to confirm this: {e}"}
    if not policy:
        return {"policy_id": policy_id,
                "summary": f"Delete RLS policy {policy_id!r} — no such policy was "
                          f"found in the policy store."}
    table = policy.get("table") or "(unknown table)"
    roles = policy.get("roles") or []
    return {"policy_id": policy_id, "table": table, "roles": roles,
            "summary": f"Delete the row filter on {table} covering "
                      f"{', '.join(roles) if roles else 'no roles'}."}


async def preview_delete_masking_policy(params: dict, user: dict) -> dict:
    """What is being deleted, read fresh right before the card is shown."""
    policy_id = str(params.get("policy_id") or "")
    try:
        policy = await _maybe_await(_mask_policy_by_id(policy_id))
    except Exception as e:
        return {"policy_id": policy_id,
                "summary": f"Delete masking policy {policy_id!r} — its table and "
                          f"column could not be read to confirm this: {e}"}
    if not policy:
        return {"policy_id": policy_id,
                "summary": f"Delete masking policy {policy_id!r} — no such policy "
                          f"was found in the policy store."}
    table = policy.get("table") or "(unknown table)"
    column = policy.get("column") or "(unknown column)"
    return {"policy_id": policy_id, "table": table, "column": column,
            "summary": f"Delete the column mask on {table}.{column}."}


async def delete_rls_policy_action(params: dict, user: dict) -> dict:
    from app.api.governance import delete_rls_policy
    return await delete_rls_policy(params["policy_id"], user=user)


async def delete_masking_policy_action(params: dict, user: dict) -> dict:
    from app.api.governance import delete_mask_policy
    return await delete_mask_policy(params["policy_id"], user=user)


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
    Action("governance.delete_rls_policy", "Delete row filter",
           "Delete a row-level security policy. Every role it covered can then see "
           "rows on that table it filtered out, unless another policy still applies.",
           ("*",), "governance:write", ActionKind.DESTRUCTIVE, PolicyDeleteParams,
           target_field="policy_id"),
    Action("governance.delete_masking_policy", "Delete column mask",
           "Delete a column-masking policy. That column stops being masked for "
           "everyone who can query the table.",
           ("*",), "governance:write", ActionKind.DESTRUCTIVE, PolicyDeleteParams,
           target_field="policy_id"),
)

EXECUTORS: Dict[str, Callable] = {
    "governance.explain_policy": explain_policy,
    "governance.policy_coverage": policy_coverage,
    "governance.summary_stats": summary_stats,
    "governance.pii_summary": pii_summary,
    "governance.create_rls_policy": create_rls_policy_action,
    "governance.create_masking_policy": create_masking_policy_action,
    "governance.delete_rls_policy": delete_rls_policy_action,
    "governance.delete_masking_policy": delete_masking_policy_action,
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
    "governance.delete_rls_policy": _r("app.api.governance", "delete_rls_policy"),
    # Not delete_masking_policy: the real handler's name is delete_mask_policy.
    "governance.delete_masking_policy": _r("app.api.governance", "delete_mask_policy"),
}

PREVIEWERS: Dict[str, Callable] = {
    "governance.create_rls_policy": preview_create_rls_policy,
    "governance.create_masking_policy": preview_create_masking_policy,
    "governance.delete_rls_policy": preview_delete_rls_policy,
    "governance.delete_masking_policy": preview_delete_masking_policy,
}

DEPENDENTS: Dict[str, Callable] = {
    "governance.delete_rls_policy": dependents_delete_rls_policy,
    "governance.delete_masking_policy": dependents_delete_masking_policy,
}
