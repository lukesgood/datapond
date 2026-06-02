"""
RLS Layer 2 — Trino file-based access control generator (see docs/RLS_DESIGN.md).

Produces a Trino `rules.json` (file-based system access control) from the same
rls_policies / column_masking_policies that drive the backend engine. This closes
the gap where a user connects to Trino directly (BI/JDBC), bypassing the backend.

Key idea: at GENERATION time the backend knows every user's roles + attributes,
so it reuses the engine's policy-resolution + attribute-binding to emit one
*concrete* per-(user, table) rule with the filter already bound to literals — no
runtime callback / mapping table needed. Regenerate whenever users/attributes/
policies change (policy CRUD triggers it; a manual export endpoint also exists).

Output schema (Trino file-based access control):
  {
    "catalogs": [{"allow": "all"}],
    "tables": [
      {"user": "^alice$", "catalog": "iceberg", "schema": "sales", "table": "orders",
       "privileges": ["SELECT"], "filter": "region = 'us-east'",
       "columns": [{"name": "email", "mask": "regexp_replace(...)"}]},
      ...
      {"catalog": ".*", "schema": ".*", "table": ".*", "privileges": []}   # default_deny
    ]
  }
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence

from .engine import (
    UserContext, RlsPolicy, MaskPolicy,
    applicable_policies, combined_filter, mask_expression, _mask_applies,
)


def _user_regex(username: str) -> str:
    return "^" + re.escape(username) + "$"


def _policy_key(p) -> str:
    return f"{p.catalog}.{p.schema}.{p.table}".lower()


def generate_rules(
    users: Sequence[UserContext],
    policies: Sequence[RlsPolicy],
    masks: Sequence[MaskPolicy] = (),
    *,
    default_deny: bool = True,
    admin_bypass: bool = False,
    read_privileges: Sequence[str] = ("SELECT",),
) -> Dict:
    """
    Build a Trino file-based access control config dict.

    - One combined rule per (user, policy-bearing table): SELECT + bound filter + masks.
    - admin_bypass: admins get a top allow-all rule (matches RLS_ADMIN_BYPASS).
    - default_deny: a final catch-all rule grants no privileges, so any table without
      an explicit allow rule above is denied (whitelist posture).
    """
    # index policies/masks by table
    pol_by_table: Dict[str, List[RlsPolicy]] = {}
    for p in policies:
        pol_by_table.setdefault(_policy_key(p), []).append(p)
    mask_by_table: Dict[str, List[MaskPolicy]] = {}
    for m in masks:
        if m.enabled:
            mask_by_table.setdefault(_policy_key(m), []).append(m)

    table_rules: List[Dict] = []

    # 1) admin allow-all (only when bypass enabled)
    if admin_bypass:
        admins = [u.username for u in users if u.is_admin]
        if admins:
            table_rules.append({
                "user": "^(" + "|".join(re.escape(a) for a in admins) + ")$",
                "catalog": ".*", "schema": ".*", "table": ".*",
                "privileges": list({*read_privileges, "INSERT", "DELETE", "UPDATE", "OWNERSHIP"}),
            })

    # 2) per (user, table) filter + mask rules
    for user in users:
        if user.is_admin and admin_bypass:
            continue
        for key, tbl_policies in sorted(pol_by_table.items()):
            catalog, schema, table = key.split(".")
            eff = applicable_policies(tbl_policies, user)
            filt = combined_filter(eff, user)
            tbl_masks = [m for m in mask_by_table.get(key, []) if _mask_applies(m, user)]

            # A registered table with no effective filter/mask for this user is still
            # allowed (user is exempt) — emit a plain SELECT allow so default_deny
            # doesn't block them.
            rule: Dict = {
                "user": _user_regex(user.username),
                "catalog": catalog, "schema": schema, "table": table,
                "privileges": list(read_privileges),
            }
            if filt:
                rule["filter"] = filt
            if tbl_masks:
                rule["columns"] = [
                    {"name": m.column, "mask": mask_expression(m.column, m)} for m in tbl_masks
                ]
            table_rules.append(rule)

    # 3) default_deny catch-all (whitelist): no privileges => deny
    if default_deny:
        table_rules.append({
            "catalog": ".*", "schema": ".*", "table": ".*", "privileges": [],
        })

    return {
        # Catalog visibility is allowed; row/column enforcement happens at table rules.
        "catalogs": [{"allow": "all"}],
        "schemas": [{"user": ".*", "schema": ".*", "owner": False}],
        "tables": table_rules,
    }


def rules_summary(rules: Dict) -> Dict:
    """Small stats blob for the export endpoint / audit."""
    tables = rules.get("tables", [])
    return {
        "table_rules": len(tables),
        "with_filter": sum(1 for t in tables if t.get("filter")),
        "with_masks": sum(1 for t in tables if t.get("columns")),
        "default_deny": any(t.get("privileges") == [] and t.get("catalog") == ".*" for t in tables),
    }
