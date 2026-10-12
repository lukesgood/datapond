"""Per-caller model spend budgets: read them, set them, clear them.

The cap itself lives at the LiteLLM gateway as a customer budget, keyed by the same
caller id DataPond already sends with every model call. This router is the operator's
way to manage those caps without handing anyone the gateway's master key, and to see
what each caller has spent against its own cap.
"""
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.ai_backends import _gateway, _headers
from app.api.auth import require_admin, require_permission

logger = logging.getLogger(__name__)
router = APIRouter()


class BudgetPut(BaseModel):
    # None clears the cap: the caller goes back to whatever default the deployment set
    # (litellm_settings.max_end_user_budget_id), or to no cap at all.
    max_budget: Optional[float] = Field(default=None, ge=0)


def _customer(row: dict) -> dict:
    budget = row.get("litellm_budget_table") or {}
    return {
        "user_id": row.get("user_id"),
        "alias": row.get("alias"),
        "spend": round(float(row.get("spend") or 0), 6),
        "max_budget": row.get("max_budget", budget.get("max_budget")),
        "blocked": bool(row.get("blocked")),
    }


async def forget_caller(user_id: str) -> bool:
    """Remove a caller's customer row — cap and all — when its account is deleted.

    Best effort: the account is gone from DataPond whether or not the gateway answers,
    so a gateway that is down must not keep a credential alive. False means the row
    may still be there; the operator can see it under Settings → Budgets. A 404 is
    the state we want — the gateway has no such customer — and is True.
    """
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{url}/customer/delete", headers=_headers(key),
                             json={"user_ids": [user_id]})
    except Exception as e:
        logger.warning("[ai_budgets] could not remove gateway customer %s: %s", user_id, e)
        return False
    if r.status_code == 404:
        return True
    if r.status_code >= 400:
        logger.warning("[ai_budgets] gateway kept customer %s (HTTP %s)", user_id, r.status_code)
        return False
    return True


# Accounts DataPond deleted, by id, from its own audit log: the sweep below touches
# nothing at the gateway that DataPond did not itself remove.
_RECENTLY_DELETED_SQL = (
    "SELECT DISTINCT details->>'service_account' AS id FROM auth_audit_log "
    "WHERE event_type = 'user_deleted' AND details ? 'service_account' "
    "AND created_at > now() - make_interval(days => $1)"
)


async def forget_deleted_callers(conn, *, days: int = 7) -> int:
    """Re-send the gateway delete for every account removed in the last `days` days.

    The gateway writes spend asynchronously and creates the customer row as a side
    effect, so the delete sent at account deletion can be undone seconds later by the
    account's own last call. Run from the audit retention tick on its connection,
    under its single-leader lock; a row that is already gone answers 404 and counts as
    done. Returns how many are now gone.
    """
    rows = await conn.fetch(_RECENTLY_DELETED_SQL, days)
    gone = 0
    for row in rows:
        user_id = row["id"]
        if user_id and await forget_caller(str(user_id)):
            gone += 1
    return gone


@router.get("/settings/ai/budgets", dependencies=[Depends(require_permission("spend:read"))])
async def list_budgets():
    """Every caller the gateway knows, with its cap and what it has spent against it.

    `unavailable` rather than an empty list when the gateway cannot be read: a caller
    with no cap and a gateway that did not answer look identical otherwise, and one of
    those means "nothing is enforced".
    """
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/customer/list", headers=_headers(key))
        if r.status_code >= 400:
            return {"customers": [], "unavailable": f"gateway returned HTTP {r.status_code}"}
        rows = r.json()
        rows = rows if isinstance(rows, list) else rows.get("customers", [])
    except Exception as e:
        logger.warning("[ai_budgets] list failed: %s", e)
        return {"customers": [], "unavailable": "gateway could not be reached"}
    return {"customers": [_customer(row) for row in rows if isinstance(row, dict)]}


@router.get("/settings/ai/budgets/{user_id}",
            dependencies=[Depends(require_permission("spend:read"))])
async def get_budget(user_id: str):
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{url}/customer/info", headers=_headers(key),
                            params={"end_user_id": user_id})
    except Exception as e:
        raise HTTPException(502, f"Cannot reach the model gateway: {str(e)[:160]}")
    if r.status_code == 404:
        return {"user_id": user_id, "max_budget": None, "spend": 0.0, "blocked": False}
    if r.status_code >= 400:
        raise HTTPException(502, f"Gateway returned HTTP {r.status_code}")
    return _customer(r.json())


@router.put("/settings/ai/budgets/{user_id}", dependencies=[Depends(require_admin)])
async def set_budget(user_id: str, body: BudgetPut):
    """Set or clear one caller's cap.

    /customer/new for a caller the gateway has not seen, /customer/update for one it
    has. Tried in that order because a caller usually gets its budget before its first
    call — and update on an unknown customer is an error, while new on a known one is.
    """
    url, key = _gateway()
    payload = {"user_id": user_id, "max_budget": body.max_budget}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{url}/customer/new", headers=_headers(key), json=payload)
            if r.status_code >= 400:
                r = await c.post(f"{url}/customer/update", headers=_headers(key), json=payload)
    except Exception as e:
        raise HTTPException(502, f"Cannot reach the model gateway: {str(e)[:160]}")
    if r.status_code >= 400:
        # The body can echo part of the master key on an auth failure — status only.
        raise HTTPException(502, f"Gateway refused the budget change (HTTP {r.status_code})")
    return {"user_id": user_id, "max_budget": body.max_budget}
