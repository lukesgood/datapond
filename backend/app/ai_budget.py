"""Per-caller spend caps, enforced at the gateway and named honestly to the caller.

DataPond stamps every model call with the caller's id (`user` in the payload, see
ai_context.actor_payload), which LiteLLM records as the end user — a "customer". A
customer can carry a max_budget, and the gateway then refuses calls once that caller
has spent it. That is the whole enforcement mechanism: no spend lookup per request,
and no way for a caller to talk past it, because the cap lives where the money is
counted.

What this module adds on top is the part a gateway cannot do for us. LiteLLM answers
an over-budget call with an *auth* error — "type": "auth_error", code 401 — which an
agent cannot tell apart from a bad key, and which our call sites wrapped again as 502
"Embedding failed". Here it becomes 402 with the gateway's own numbers, and one
`refused` row in the tool call log, so the refusal is both actionable and audited.
"""
import logging
from typing import Optional

from fastapi import HTTPException

from app import tool_call_log

logger = logging.getLogger(__name__)

# The gateway's message: "ExceededBudget: End User=<id> over budget. Spend=..., Budget=..."
_MARKERS = ("exceededbudget", "over budget")


def is_budget_refusal(status_code: int, body: Optional[str]) -> bool:
    """True when a gateway error is a spend cap, not a credential or model problem.

    Matched on the message, not the status: the proxy returns 401/auth_error for this,
    the same shape it uses for a rejected key, so the status alone cannot separate
    "this caller has spent its allowance" from "this key is wrong".
    """
    if status_code < 400 or not body:
        return False
    text = body.lower()
    return any(marker in text for marker in _MARKERS)


def budget_error(body: Optional[str]) -> HTTPException:
    """402 with the gateway's own spend and budget figures, trimmed."""
    detail = (body or "").strip()
    return HTTPException(
        status_code=402,
        detail=("This caller has reached its model spend budget. " + detail[:300]).strip(),
    )


async def refuse_over_budget(*, actor: dict, tool: str, request_text: str,
                             body: Optional[str]) -> HTTPException:
    """Record the refusal, then hand back the 402 for the caller to raise.

    Returns rather than raises so the call site keeps its own control flow — the RAG
    path degrades to search results instead of failing the request, and still audits.
    """
    await tool_call_log.record(
        actor=actor or {}, tool=tool, resource_kind="none", resource=[],
        request_text=tool_call_log.masked_for_log(request_text or ""),
        outcome="refused")
    logger.warning("[ai_budget] refused: %s over its model spend budget", (actor or {}).get("username"))
    return budget_error(body)
