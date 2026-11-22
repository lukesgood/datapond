"""Concept actions: which columns a business word is (app/semantic/concept_context.py).

Read only. An agent asked about "플래티넘 고객" can look up that the word is the segment
customers WHERE tier = 'platinum' and that 고객 joins on customers.id = orders.customer_id,
as an administrator approved them, instead of guessing from column names. Bindings on
catalogs the caller may not use are left out.
"""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class ConceptList(_Strict):
    pass


class ConceptName(_Strict):
    concept: str = Field(description="A concept's name or one of its terms, as concept_list returns them (e.g. 고객, customer).")


async def list_concepts(params: dict, user: dict) -> dict:
    from app.semantic import concept_context
    return {"concepts": await concept_context.list_visible(user)}


async def describe_concept(params: dict, user: dict) -> dict:
    from app.semantic import concept_context
    return await concept_context.describe_visible(user, params["concept"])


ACTIONS = (
    Action("concept.list", "List business concepts",
           "Business words (고객, 주문, 플래티넘 고객 …) with their aliases and how many approved "
           "column bindings each has. Call it when a question uses a business word you would "
           "otherwise map to a column by guessing.",
           ("*",), "catalog:read", ActionKind.READ, ConceptList, capability="ontology"),
    Action("concept.describe", "Describe business concept",
           "One concept's approved bindings: its key columns (join on these), attributes, and "
           "segment conditions (apply exactly), plus narrower concepts.",
           ("*",), "catalog:read", ActionKind.READ, ConceptName, capability="ontology"),
)

EXECUTORS: Dict[str, Callable] = {
    "concept.list": list_concepts,
    "concept.describe": describe_concept,
}

RESOLVERS: Dict[str, Callable] = {
    "concept.list": _r("app.semantic.concept_context", "list_visible"),
    "concept.describe": _r("app.semantic.concept_context", "describe_visible"),
}

PREVIEWERS: Dict[str, Callable] = {}
