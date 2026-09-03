"""Spend actions: model usage and cost over a period.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
from typing import Callable, Dict

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class SpendQuery(_Strict):
    days: int = 30


async def summarize_spend(params: dict, user: dict) -> dict:
    from app.api.ai_backends import spend_summary
    return {"spend": await spend_summary()}


ACTIONS = (
    Action("spend.summarize", "Summarise spend",
           "Model usage and cost over a period.",
           ("/ai", "/settings"), "spend:read", ActionKind.READ, SpendQuery),
)

EXECUTORS: Dict[str, Callable] = {
    "spend.summarize": summarize_spend,
}

RESOLVERS: Dict[str, Callable] = {
    "spend.summarize": _r("app.api.ai_backends", "spend_summary"),
}

PREVIEWERS: Dict[str, Callable] = {}
