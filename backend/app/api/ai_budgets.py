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
