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


ACTIONS = (
    Action("governance.explain_policy", "Explain policy",
           "Which row filters and column masks apply, and to whom.",
           ("/governance",), "governance:read", ActionKind.READ, PolicyQuery),
)

EXECUTORS: Dict[str, Callable] = {
    "governance.explain_policy": explain_policy,
}

RESOLVERS: Dict[str, Callable] = {
    "governance.explain_policy": _r("app.rls.loader", "load_policies"),
}

PREVIEWERS: Dict[str, Callable] = {}
