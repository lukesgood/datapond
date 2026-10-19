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

And one check of our own, before the call (`assert_within_cap`). The gateway judges
"spend > cap" on spend it has already written, writes spend asynchronously and caches
the customer row, so a caller capped a moment ago, or capped at 0 before its first
call, gets one more answer (seen live 2026-10-13). DataPond asks the gateway for the
caller's spend and cap first — cached a few seconds, forgotten when an operator
changes the cap — and refuses when spend >= cap. A cap of 0 is therefore "no calls",
at once. The gateway's check stays as the backstop for what this one cannot see.

"Forgotten when an operator changes the cap" held only in the pod that served the
change: with two backend pods the other kept its cached "no cap" (seen live
2026-10-16, HTTP 200 at a cap of 0). So the cap an operator sets through DataPond is
also kept in Postgres (`ai_budget_caps`, migration 0024) and read on every call; only
the spend is cached. No row means DataPond never set one, and the gateway's cap applies.
"""
import logging
import time
from typing import Dict, Optional, Tuple

import httpx
from fastapi import HTTPException

from app import tool_call_log
from app.api.ai_backends import _gateway, _headers

logger = logging.getLogger(__name__)

# The gateway has two wordings for the same cap, from two code paths:
#   "ExceededBudget: End User=<id> over budget. Spend=..., Budget=..."   (auth_error, 401)
#   "Budget has been exceeded! EndUser=<id> Current cost: ..., Max budget: ..." (budget_exceeded, 400)
_MARKERS = ("exceededbudget", "over budget", "budget has been exceeded", "budget_exceeded")


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

    Returns rather than raises so the call site keeps its own control flow; every
    call site today raises it (search, rag, embed, sql), so the caller sees 402 and the
    audit log one `refused` row — `_logged` does not add an `error` row for a 402.
    """
    await tool_call_log.record(
        actor=actor or {}, tool=tool, resource_kind="none", resource=[],
        request_text=tool_call_log.masked_for_log(request_text or ""),
        outcome="refused")
    logger.warning("[ai_budget] refused: %s over its model spend budget", (actor or {}).get("username"))
    return budget_error(body)


# ── The check before the call ─────────────────────────────────────────────────

CACHE_TTL_SECONDS = 15.0
# caller id → (expires_at, max_budget or None, spend). An entry is also kept for a
# caller the gateway does not know (no cap, no spend), so each caller costs one lookup
# per TTL, not one per call.
_cache: Dict[str, Tuple[float, Optional[float], float]] = {}


def forget_cached(user_id: Optional[str] = None) -> None:
    """Drop one caller's cached figures (an operator changed its cap), or all of them."""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


async def _figures(user_id: str) -> Optional[Tuple[Optional[float], float]]:
    """(max_budget, spend) for a caller, from the gateway; None when it cannot say."""
    now = time.monotonic()
    hit = _cache.get(user_id)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    try:
        url, key = _gateway()
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{url}/customer/info", headers=_headers(key),
                            params={"end_user_id": user_id})
    except Exception as e:
        logger.warning("[ai_budget] cap check skipped, gateway unreachable: %s", str(e)[:120])
        return None
    if r.status_code == 404:
        figures: Tuple[Optional[float], float] = (None, 0.0)
    elif r.status_code >= 400:
        logger.warning("[ai_budget] cap check skipped, gateway answered HTTP %s", r.status_code)
        return None
    else:
        row = r.json()
        budget = row.get("litellm_budget_table") or {}
        cap = row.get("max_budget", budget.get("max_budget"))
        figures = (float(cap) if cap is not None else None, float(row.get("spend") or 0.0))
    _cache[user_id] = (now + CACHE_TTL_SECONDS, figures[0], figures[1])
    return figures


# _shared_cap's answer when DataPond holds no cap for the caller.
NO_SHARED_CAP = object()


async def _shared_cap(user_id: str):
    """The cap set through DataPond, as every pod sees it, or NO_SHARED_CAP."""
    from app.api.connectors import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as c:
        cap = await c.fetchval("SELECT max_budget FROM ai_budget_caps WHERE user_id = $1", user_id)
    return NO_SHARED_CAP if cap is None else float(cap)


async def shared_caps() -> Dict[str, float]:
    """Every cap set through DataPond, by caller id: what the console shows as the cap.

    The gateway keeps no cap of 0 (it reports none), so its own figure is not the one
    enforced here; a display must overlay these on it.
    """
    from app.api.connectors import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT user_id, max_budget FROM ai_budget_caps")
    return {str(r["user_id"]): float(r["max_budget"]) for r in rows}


async def store_shared_cap(user_id: str, cap: Optional[float]) -> None:
    """Record the cap an operator set; None (cleared) removes it."""
    from app.api.connectors import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as c:
        if cap is None:
            await c.execute("DELETE FROM ai_budget_caps WHERE user_id = $1", user_id)
        else:
            await c.execute(
                "INSERT INTO ai_budget_caps (user_id, max_budget) VALUES ($1, $2) "
                "ON CONFLICT (user_id) DO UPDATE SET max_budget = EXCLUDED.max_budget, "
                "updated_at = now()", user_id, float(cap))


async def assert_within_cap(*, actor: dict, tool: str, request_text: str) -> None:
    """Raise the 402 (and write the `refused` row) when the caller has spent its cap.

    Nothing to check without a caller id, and nothing refused when the gateway cannot
    be asked: the model call that follows will meet the gateway's own check anyway.
    """
    user_id = (actor or {}).get("id")
    if not user_id:
        return
    try:
        shared = await _shared_cap(str(user_id))
    except Exception as e:
        logger.warning("[ai_budget] shared cap unreadable, using the gateway's: %s", str(e)[:120])
        shared = NO_SHARED_CAP
    if shared is not NO_SHARED_CAP and shared <= 0:
        # No spend can be under a cap of 0: no need to ask the gateway.
        raise await refuse_over_budget(
            actor=actor, tool=tool, request_text=request_text,
            body="Budget=0 (checked before the call).")
    figures = await _figures(str(user_id))
    if figures is None:
        return
    cap, spend = figures
    if shared is not NO_SHARED_CAP:
        cap = shared
    if cap is not None and spend >= cap:
        raise await refuse_over_budget(
            actor=actor, tool=tool, request_text=request_text,
            body=f"Spend={spend:g}, Budget={cap:g} (checked before the call).")
