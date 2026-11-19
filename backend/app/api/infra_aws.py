"""Infrastructure › AWS and Cost: the resources this deployment runs on, what they
cost, and the two settings the console may change (Aurora's capacity range and the
node's start/stop schedule). See app/aws_infra.py and app/aws_cost.py.

Admin only. Off unless AWS_INFRA_ENABLED (values-prod-single.yaml turns it on),
and the routes 404 when it is off, so a non-AWS profile has no such surface.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import aws_cost, aws_infra
from app.api.auth import require_admin, require_permission
from app.api.connectors import get_db_pool

logger = logging.getLogger(__name__)
router = APIRouter()

BUDGET_KEY = "infra.monthly_budget_usd"
EXPECTED_STARTS_KEY = "infra.expected_starts"


def _on() -> None:
    if not aws_infra.enabled():
        raise HTTPException(404, "AWS infrastructure view is not enabled on this deployment.")


async def _setting(key: str):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval("SELECT value FROM system_settings WHERE key = $1", key)
    try:
        return json.loads(v) if v is not None else None
    except ValueError:
        return None


async def _save_setting(key: str, value) -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, NOW())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            key, json.dumps(value))


def _aws_error(e: Exception) -> HTTPException:
    code = getattr(e, "response", {}).get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
    msg = getattr(e, "response", {}).get("Error", {}).get("Message", "") if hasattr(e, "response") else str(e)
    if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
        return HTTPException(403, f"The node role may not make this change yet ({code}). "
                                  "Apply the IAM in terraform/iam.tf (InfraManage).")
    return HTTPException(502, f"AWS refused the change: {msg or e}")


@router.get("/infra/aws", dependencies=[Depends(require_admin)])
async def infra_aws(refresh: bool = False):
    _on()
    snap = await asyncio.to_thread(aws_infra.snapshot, refresh)
    return {k: v for k, v in snap.items() if k != "usage"}


async def _ai_spend() -> List[tuple]:
    """(time, usd) per model call this month, from the gateway's spend log."""
    from app.api.ai_backends import _gateway, _headers
    try:
        url, key = _gateway()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{url}/spend/logs", headers=_headers(key))
        logs = r.json() if r.status_code < 400 else []
    except Exception as e:
        logger.info("infra cost: AI spend unavailable: %s", e)
        return []
    out = []
    for entry in logs if isinstance(logs, list) else []:
        try:
            ts = datetime.fromisoformat(str(entry.get("startTime")).replace("Z", "+00:00"))
            out.append((ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc), float(entry.get("spend") or 0)))
        except (TypeError, ValueError):
            continue
    return out


@router.get("/infra/cost", dependencies=[Depends(require_admin)])
async def infra_cost(refresh: bool = False):
    _on()
    snap, ai, actual, budget = await asyncio.gather(
        asyncio.to_thread(aws_infra.snapshot, refresh), _ai_spend(),
        asyncio.to_thread(aws_infra.actual_costs), _setting(BUDGET_KEY))
    usage = dict(snap.get("usage") or {}, ai_spend=ai)
    est = aws_cost.estimate(usage, datetime.now(timezone.utc))
    state = aws_cost.budget_state(est["total"]["forecast"], budget)
    _last_budget["state"] = ({"forecast": est["total"]["forecast"], "budget": budget, "pct": state["pct"]}
                             if state and state["over"] else None)
    return {**est, "actual": actual, "budget": state,
            "budget_usd": budget, "missing": snap.get("missing") or [], "read_at": snap.get("read_at"),
            "aurora": snap.get("aurora"), "node": {k: snap.get("node", {}).get(k) for k in
                                                   ("instance_type", "lifecycle", "hourly_price", "on_demand_hourly")},
            "schedule": snap.get("schedule")}


class Capacity(BaseModel):
    min_acu: float
    max_acu: float


@router.put("/infra/aurora-capacity", dependencies=[Depends(require_permission("settings:write"))])
async def put_aurora_capacity(body: Capacity):
    _on()
    try:
        return await asyncio.to_thread(aws_infra.set_aurora_capacity, body.min_acu, body.max_acu)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _aws_error(e)


class Schedule(BaseModel):
    days: List[str]
    start: str
    stop: str
    enabled: bool = True


def _expected_starts(days: List[str], start: str, tz: str) -> str:
    """The system-events spec (`MON-FRI 07:30 Asia/Seoul`) for a schedule, so a
    scheduled boot is still read as expected after the console moved it."""
    return f"{aws_cost.build_cron(days, start).split(' ')[4]} {start} {tz}"


@router.put("/infra/schedule", dependencies=[Depends(require_permission("settings:write"))])
async def put_schedule(body: Schedule):
    _on()
    days = [d.upper() for d in body.days]
    try:
        result = await asyncio.to_thread(aws_infra.set_schedule, days, body.start, body.stop, body.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise _aws_error(e)
    tz = ((aws_infra.cached_snapshot() or {}).get("schedule") or {}).get("tz") or "Asia/Seoul"
    spec = _expected_starts(days, body.start, tz) if body.enabled else ""
    await _save_setting(EXPECTED_STARTS_KEY, spec)
    os.environ["SYSTEM_EVENTS_EXPECTED_STARTS"] = spec
    return result


class Budget(BaseModel):
    usd: Optional[float] = None


@router.put("/infra/budget", dependencies=[Depends(require_permission("settings:write"))])
async def put_budget(body: Budget):
    _on()
    if body.usd is not None and not (0 < body.usd <= 1_000_000):
        raise HTTPException(400, "A monthly budget is a positive number of US dollars.")
    await _save_setting(BUDGET_KEY, body.usd)
    return {"budget_usd": body.usd}


async def restore_expected_starts(pool) -> None:
    """At startup: a schedule moved from the console outlives the pod."""
    try:
        async with pool.acquire() as conn:
            v = await conn.fetchval("SELECT value FROM system_settings WHERE key = $1", EXPECTED_STARTS_KEY)
        if v is not None:
            os.environ["SYSTEM_EVENTS_EXPECTED_STARTS"] = json.loads(v) or ""
    except Exception as e:
        logger.info("infra: expected starts not restored: %s", e)


_last_budget: dict = {}


def over_budget() -> Optional[dict]:
    """For Overview: the forecast passed the budget at the last Cost tab read. No AWS
    call — Overview must stay fast — so it is as fresh as that read."""
    return _last_budget.get("state")
