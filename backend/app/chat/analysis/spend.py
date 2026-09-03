"""Spend actions: model usage and cost over a period.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
from datetime import date, timedelta
from typing import Callable, Dict, Optional

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class SpendQuery(_Strict):
    days: int = 30


class SpendWindow(_Strict):
    days: int = Field(default=7, ge=1, le=90)


async def summarize_spend(params: dict, user: dict) -> dict:
    from app.api.ai_backends import spend_summary
    return {"spend": await spend_summary()}


# `spend.summarize` answers "what did we spend". `diagnose_change` answers "why did it
# change" — specifically whether the total moved because of volume (more calls) or unit
# price (a costlier model), which a single window cannot tell apart. Actor attribution
# stays at exactly the level `spend.summarize` already returns; this action widens no
# privacy boundary.

# Below this the movement is noise: a few pennies on a small account is a large
# percentage and no story at all.
_MATERIAL_USD = 1.0
_MATERIAL_FRACTION = 0.15


# `spend_report` returns {"start_date", "end_date", "report": [...]}, and the list under
# "report" is LiteLLM's own payload passed through untouched — its item shape is not
# defined anywhere in this repo and cannot be verified from it. So read it defensively
# and say so when the fields are not there: a total computed from rows whose spend field
# was named something else is zero, and zero reported as fact is worse than "not checked".
def _totals(report: dict) -> tuple:
    rows = (report or {}).get("report") or []
    spend = sum(float(r.get("spend") or 0) for r in rows if isinstance(r, dict))
    requests = sum(int(r.get("requests") or 0) for r in rows if isinstance(r, dict))
    recognised = any(isinstance(r, dict) and "spend" in r for r in rows)
    return spend, requests, rows, recognised


# `spend_report` does not raise on a gateway error — on a non-2xx response it returns
# {"report": [], "detail": "...", "status_code": ...} rather than the exception path.
# That makes an empty report ambiguous: "nothing was spent" and "the gateway could not
# be asked" both look like an empty list, and they call for different answers — one is
# a fact, the other is a reason we don't have one. A "detail" key alongside an empty
# report is treated as the fetch having failed, never as zero spend.
#
# "detail" itself is `_short(r.text, 200)` — the raw LiteLLM response body — and is
# never surfaced here. On an auth failure that body can echo part of an API key, and
# this action is reachable by anyone with `spend:read`, not just an admin (the
# Settings → AI page that does show `detail` is admin-only). Report the failure and
# its HTTP status instead.
def _gateway_error(report: dict) -> Optional[str]:
    if isinstance(report, dict) and not report.get("report") and "detail" in report:
        status = report.get("status_code")
        return f"gateway returned HTTP {status}" if status else "gateway returned an error"
    return None


async def diagnose_change(params: dict, user: dict) -> dict:
    """Did spend change, and was it volume or unit price?"""
    from app.api.ai_backends import spend_report
    from app.chat.diagnosis import Diagnosis

    days = params["days"]
    today = date.today()
    cur_start, cur_end = today - timedelta(days=days), today
    prev_start, prev_end = cur_start - timedelta(days=days), cur_start

    current = await spend_report(start_date=cur_start.isoformat(),
                                 end_date=cur_end.isoformat())
    previous = await spend_report(start_date=prev_start.isoformat(),
                                  end_date=prev_end.isoformat())

    d = Diagnosis(f"model spend over the last {days} days against the {days} before")

    cur_err = _gateway_error(current)
    if cur_err:
        d.skipped("Spend not checked: the gateway reported an error for the recent "
                  f"window: {cur_err}")
        return d.done()

    cur_spend, cur_calls, cur_rows, cur_ok = _totals(current)
    prev_spend, prev_calls, _, prev_ok = _totals(previous)

    if cur_rows and not cur_ok:
        d.skipped("Spend not checked: the gateway returned rows this build does not "
                  "recognise — no field named 'spend' on any of them.")
        return d.done()

    d.fact("current_total", round(cur_spend, 4))
    d.fact("previous_total", round(prev_spend, 4))
    d.fact("current_requests", cur_calls)
    d.fact("previous_requests", prev_calls)
    d.fact("by_model", sorted(
        ({"model": r.get("model"), "spend": round(float(r.get("spend") or 0), 4),
          "requests": int(r.get("requests") or 0)} for r in cur_rows),
        key=lambda r: r["spend"], reverse=True)[:10])

    prev_err = _gateway_error(previous)
    if prev_err:
        d.skipped("Change not checked: the gateway reported an error for the earlier "
                  f"window: {prev_err}")
        return d.done()

    if prev_spend <= 0:
        d.skipped("Change not checked: the earlier window has no spend, so there is "
                  "nothing to compare against.")
        return d.done()

    delta = cur_spend - prev_spend
    fraction = delta / prev_spend
    if abs(delta) < _MATERIAL_USD or abs(fraction) < _MATERIAL_FRACTION:
        d.signal("ok", "Spend is broadly flat against the previous window.",
                 delta_usd=round(delta, 4), delta_fraction=round(fraction, 3))
        return d.done()

    cur_unit = cur_spend / cur_calls if cur_calls else 0.0
    prev_unit = prev_spend / prev_calls if prev_calls else 0.0
    call_growth = (cur_calls - prev_calls) / prev_calls if prev_calls else None
    unit_growth = (cur_unit - prev_unit) / prev_unit if prev_unit else None

    direction = "rose" if delta > 0 else "fell"
    if call_growth is not None and abs(call_growth) >= abs(fraction) * 0.6:
        d.signal("warn" if delta > 0 else "ok",
                 f"Spend {direction} mostly on volume — the number of calls moved with it.",
                 delta_usd=round(delta, 4), call_growth=round(call_growth, 3))
    elif unit_growth is not None and abs(unit_growth) >= abs(fraction) * 0.6:
        d.signal("warn" if delta > 0 else "ok",
                 f"Spend {direction} mostly on cost per call, not volume — the model "
                 f"mix changed.",
                 delta_usd=round(delta, 4), unit_growth=round(unit_growth, 3),
                 current_cost_per_call=round(cur_unit, 6),
                 previous_cost_per_call=round(prev_unit, 6))
    else:
        d.signal("warn" if delta > 0 else "ok",
                 f"Spend {direction}, with volume and cost per call both moving.",
                 delta_usd=round(delta, 4))
    return d.done()


ACTIONS = (
    Action("spend.summarize", "Summarise spend",
           "Model usage and cost over a period.",
           ("/ai", "/settings"), "spend:read", ActionKind.READ, SpendQuery),
    Action("spend.diagnose_change", "Diagnose spend change",
           "Whether model spend changed against the previous period of the same "
           "length, and whether the cause was call volume or cost per call.",
           ("*",), "spend:read", ActionKind.READ, SpendWindow),
)

EXECUTORS: Dict[str, Callable] = {
    "spend.summarize": summarize_spend,
    "spend.diagnose_change": diagnose_change,
}

RESOLVERS: Dict[str, Callable] = {
    "spend.summarize": _r("app.api.ai_backends", "spend_summary"),
    "spend.diagnose_change": _r("app.api.ai_backends", "spend_report"),
}

PREVIEWERS: Dict[str, Callable] = {}
