"""Audit activity as counts.

Deliberately not built on /governance/audit-log. That endpoint returns records, and an
action that fetched records and trimmed them would put actor names, client addresses and
route paths — which embed resource ids — into memory one careless edit away from the
model. This is a GROUP BY: the identifying columns are never selected, so there is no
path along which they reach anything.

"Who read what" stays a question for the Governance screen, which answers it to the same
people under the same permission, with no model in the middle.
"""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class AuditWindow(_Strict):
    days: int = Field(default=7, ge=1, le=90)


# Every column here is a category or a count. Adding one that is not fails
# tests/test_chat_audit_aggregate.py, which reads this statement.
_SUMMARY_SQL = """
    SELECT permission,
           outcome,
           date_trunc('day', occurred_at)::date AS day,
           count(*) AS n
      FROM public.security_audit_log
     WHERE occurred_at >= now() - ($1::int * interval '1 day')
     GROUP BY permission, outcome, day
     ORDER BY day
"""


async def activity_summary(params: dict, user: dict) -> dict:
    from app.api.auth import _get_pool

    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SUMMARY_SQL, params["days"])

    totals = {"allowed": 0, "denied": 0}
    by_permission: Dict[str, dict] = {}
    by_day: Dict[str, dict] = {}
    for row in rows:
        outcome = str(row["outcome"])
        n = int(row["n"])
        totals[outcome] = totals.get(outcome, 0) + n

        perm = by_permission.setdefault(
            str(row["permission"]), {"permission": str(row["permission"]),
                                     "allowed": 0, "denied": 0})
        perm[outcome] = perm.get(outcome, 0) + n

        day = by_day.setdefault(str(row["day"]), {"day": str(row["day"]),
                                                  "allowed": 0, "denied": 0})
        day[outcome] = day.get(outcome, 0) + n

    return {
        "days": params["days"],
        "totals": totals,
        "by_permission": sorted(by_permission.values(),
                                key=lambda r: r["denied"] + r["allowed"], reverse=True),
        "by_day": [by_day[k] for k in sorted(by_day)],
    }


ACTIONS = (
    Action("audit.activity_summary", "Audit activity summary",
           "Authorisation activity over a period as counts: allowed and denied per "
           "permission and per day. Returns no actor, address or target — those stay "
           "on the Governance screen.",
           ("*",), "audit:read", ActionKind.READ, AuditWindow),
)

EXECUTORS: Dict[str, Callable] = {"audit.activity_summary": activity_summary}
RESOLVERS: Dict[str, Callable] = {"audit.activity_summary": _r("app.api.auth", "_get_pool")}
PREVIEWERS: Dict[str, Callable] = {}
