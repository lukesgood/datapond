"""Security audit log: the trail an authorization *denial* writes, whether or not the
caller wants it written.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (B2)

`query_history` is the closest thing this product had to an audit trail, and
`QueryExecuteRequest.save_history=false` lets the caller turn it off for their own
query — recording is the caller's choice. Authorization *denials* had no equivalent
record anywhere: a 403 left no trace, so a credential probing the API for exactly what
it can and cannot reach — the thing an audit log exists to catch — was invisible. This
module is the writer `require_permission`'s guard (`app/api/auth.py`) calls on every
denial, and `record()` takes no argument that turns the write off. There is no
`save_history`-shaped parameter on it, and none should be added; see
`tests/test_security_audit.py::test_record_has_no_parameter_that_suppresses_the_write`.

**Decision: allows are recorded only for privileged (write-shaped) permissions.**
Recording every allow would make this a log of every authenticated request, most of
which are reads. `app/permissions.py` already draws this line for the permission
matrix itself — "writing is what gets withheld, reading stays broad" — and this module
reuses it: a permission ending `:write`, plus `user:manage` and `service:manage`
(account and infrastructure control, privileged even though the string does not end in
`:write`), is audited on both allow and deny. Everything else — every `:read`
permission, `query:run`, `ai:generate` — is audited only on denial. That keeps this
module's per-request cost at zero for the read paths that make up most of the traffic:
no pool acquisition, no INSERT, nothing beyond the `is_privileged` string check already
being paid for by `require_permission` itself. Requests that do earn a row on allow
already imply a database write of their own (a connector, a policy, a user, a
setting), so the extra INSERT here is marginal next to it, not a new class of cost.

Pure logic (`build_row`, `is_privileged`) is tested without a database in
`tests/test_security_audit.py`. `record()` is the one impure edge, and it must never
raise into the request path: a database blip while auditing a request must not turn a
request that was correctly allowed — or correctly denied — into an unrelated 500. It
logs at ERROR and swallows instead.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("security_audit")

# There are exactly two outcomes to a permission check. A third value here would be a
# bug in the caller, not new information, and letting it through silently would give
# the audit log a state nothing that reads it expects.
OUTCOMES = frozenset({"allowed", "denied"})

# Named explicitly because neither ends in ":write" but both are exactly as
# privileged: `user:manage` is account takeover, `service:manage` is infrastructure
# control. See the module docstring for the rest of the reasoning.
_ALSO_PRIVILEGED = frozenset({"user:manage", "service:manage"})


def is_privileged(permission: str) -> bool:
    """Whether an *allowed* use of `permission` is worth a row of its own.

    Denials are always recorded regardless of this function's answer — it only
    decides whether a successful, permitted use is interesting enough to also write
    one. See the module docstring for why the line sits where it does.
    """
    permission = permission or ""
    return permission.endswith(":write") or permission in _ALSO_PRIVILEGED


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_row(*, actor: dict, permission: str, route: str, method: str,
              outcome: str, reason: str, client_address: Optional[str] = None,
              now: Optional[datetime] = None) -> dict:
    """One authorization decision as the row `record()` writes.

    Pure and total: every column `security_audit_log` has is filled from an argument
    here, never left for the database to default silently. A missing or malformed
    `actor` (a service-account principal, a claims dict some future caller gets
    wrong) degrades to an empty id/username rather than raising — the row is still
    worth having even when it cannot say who. An unrecognised `outcome` is different:
    there are exactly two outcomes to a permission check, so a third is a
    programming error in the caller and raises rather than writing a value nothing
    downstream expects.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
    actor = actor or {}
    return {
        "actor_id": actor.get("id"),
        "actor_username": actor.get("username") or "",
        "permission": permission,
        "route": route or "",
        "method": (method or "").upper(),
        "outcome": outcome,
        "reason": reason or "",
        "client_address": client_address,
        "occurred_at": now or utcnow(),
    }


_INSERT = """
INSERT INTO security_audit_log
    (actor_id, actor_username, permission, route, method, outcome, reason,
     client_address, occurred_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""


async def record(*, actor: dict, permission: str, route: str, method: str,
                  outcome: str, reason: str, client_address: Optional[str] = None) -> None:
    """Write one authorization decision. Never raises into the request path.

    Called from inside the authorization layer itself, which means it runs on every
    gated request that is denied (and on allows of privileged permissions — see the
    module docstring). A write that failed loudly here — a pool exhausted, a network
    blip to the database — would turn a request that was correctly denied, or
    correctly allowed, into an unrelated 500. The caller gets the outcome its
    permissions earned either way; only the audit row is at risk, and losing one to a
    transient error is a smaller cost than an outage caused by the thing meant to be
    recording it.

    There is deliberately no parameter here a caller could set to skip the write —
    that is the entire point of this module; see the module docstring.
    """
    try:
        row = build_row(actor=actor, permission=permission, route=route, method=method,
                         outcome=outcome, reason=reason, client_address=client_address)
        # Lazy import: app.api.connectors imports app.api.auth at module load time,
        # and app.api.auth calls into this module, so importing connectors here at
        # module scope would be a cycle. migrations.py takes the same shape for the
        # same reason.
        from app.api.connectors import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                _INSERT, row["actor_id"], row["actor_username"], row["permission"],
                row["route"], row["method"], row["outcome"], row["reason"],
                row["client_address"], row["occurred_at"],
            )
    except Exception:
        logger.error(
            "security_audit: failed to record permission=%s outcome=%s method=%s "
            "route=%s actor=%s — this decision is not in the audit log",
            permission, outcome, method, route,
            (actor or {}).get("username"), exc_info=True,
        )
