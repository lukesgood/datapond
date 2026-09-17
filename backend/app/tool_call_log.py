"""One row per data-tool call — success, degraded or error.

security_audit records authorization decisions and skips allows on read permissions so
the read paths pay nothing. This module records a different fact — a tool returned data
to a caller — with the columns that fact needs: which collection or tables, how many
hits, which sources were cited, how much PII was masked. It is written after the guard
ran, so nothing raw lands here, and like security_audit it never raises into the caller.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator, List, Optional

from app.chat.actions import REGISTRY

logger = logging.getLogger(__name__)

# The four rich-route tools, plus every action id in the registry — the MCP dispatcher
# writes a fallback row (app/mcp/server.py) for any of the other 40 actions whose
# executor never reaches an /ai/* route, and build_row must accept its id or that row
# silently disappears into logger.error instead of the append-only table. The DB's
# CHECK constraint (migration 0009) is the looser, permanent bound; Python stays
# stricter and enumerates rather than pattern-matching it.
# The name a refused call asked for is not a tool: it may not exist, or may be one
# this caller may not see. The row carries this sentinel and keeps the requested
# name in request_masked, so the log says "asked for something it could not have"
# without inventing a tool. Matches the DB's tool pattern (0009).
UNKNOWN_TOOL = "mcp.unknown_tool"
TOOLS = ("ai.search", "ai.rag", "ai.sql", "query.execute", UNKNOWN_TOOL) + tuple(REGISTRY)
RESOURCE_KINDS = ("collection", "tables", "none")
# refused: turned away before it ran — unknown or unpermitted name, a write, bad
# arguments, or an action this deployment does not run (migration 0010).
OUTCOMES = ("ok", "degraded", "error", "refused")
_MASKED_LIMIT = 512

_via: contextvars.ContextVar[str] = contextvars.ContextVar("tool_call_via", default="api")

# Set once per HTTP request by AuthMiddleware.dispatch (main.py) so every tool_call_log
# row from that request — including ones written from chat executors, which call the
# public search/rag wrappers with no Request object — gets a client address without
# changing any wrapper's signature.
_client_address: contextvars.ContextVar[Optional[str]] = \
    contextvars.ContextVar("tool_call_client_address", default=None)

_calls: contextvars.ContextVar[Optional[List[int]]] = \
    contextvars.ContextVar("tool_call_count", default=None)


@contextmanager
def counting() -> Iterator[Callable[[], int]]:
    """Count the rows `record` writes inside this block.

    The MCP dispatcher writes its own row only when the inner path wrote none, so a
    data tool keeps the rich row its route builds — collection, hit count, cited
    sources, masked count — and a diagnostic tool still leaves a trace. Only a
    successful insert counts: a lost row must not suppress the fallback, or the call
    would disappear from the log altogether.

    Blocks nest by shadowing, not by accumulating: a `record` call made inside a nested
    `counting()` block is counted by that inner block only, and never reaches the outer
    one. A dispatcher that opened its own `counting()` block around a call into another
    `counting()`-wrapped path must not read 0 from the outer counter and write a
    duplicate fallback row for a call the inner block already logged.
    """
    counter = [0]
    token = _calls.set(counter)
    try:
        yield lambda: counter[0]
    finally:
        _calls.reset(token)


def current_via() -> str:
    return _via.get()


@contextmanager
def via(value: str) -> Iterator[None]:
    token = _via.set(value)
    try:
        yield
    finally:
        _via.reset(token)


def set_client_address(addr: Optional[str]):
    """Set the current request's client address. Returns a token for
    `_client_address.reset(token)` — call that when the request ends."""
    return _client_address.set(addr)


def current_client_address() -> Optional[str]:
    return _client_address.get()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def masked_for_log(text: str) -> str:
    """Text as it may be stored: pii_ko masking applied regardless of PII_GUARDRAIL_MODE.
    The guardrail mode decides what the caller gets; the log never gets anything raw."""
    from app.guardrails import pii_ko
    return pii_ko.mask(text or "")


def table_names(sql: str) -> List[str]:
    """Distinct dotted table names as written in `sql`, sorted; [] if unparseable."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql)
    except Exception:
        return []
    names = set()
    for t in tree.find_all(exp.Table):
        parts = [p for p in (t.catalog, t.db, t.name) if p]
        if parts:
            names.add(".".join(parts))
    return sorted(names)


def build_row(*, actor: dict, tool: str, resource_kind: str, resource: List[str],
              request_text: str, hit_count: int = 0,
              citation_sources: Optional[List[str]] = None, pii_masked: int = 0,
              outcome: str = "ok", duration_ms: Optional[int] = None,
              client_address: Optional[str] = None, via: Optional[str] = None,
              response_text: Optional[str] = None, injection_flags: int = 0,
              now: Optional[datetime] = None) -> dict:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}")
    if resource_kind not in RESOURCE_KINDS:
        raise ValueError(f"unknown resource_kind {resource_kind!r}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    actor = actor or {}
    text = request_text or ""
    # None stays None: "this call recorded no response" and "the response was empty"
    # are different facts, and a row from before 0013 must read as the former.
    response = masked_for_log(response_text) if response_text is not None else None
    return {
        "occurred_at": now or utcnow(),
        "actor_id": actor.get("id"),
        "actor_username": actor.get("username") or "",
        "actor_kind": "service" if actor.get("auth_method") == "service" else "human",
        "tool": tool,
        "resource_kind": resource_kind,
        "resource": list(resource or []),
        "request_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "request_masked": text[:_MASKED_LIMIT],
        "hit_count": int(hit_count or 0),
        "citation_sources": sorted(set(citation_sources or [])),
        "pii_masked": int(pii_masked or 0),
        "outcome": outcome,
        "duration_ms": duration_ms,
        "client_address": client_address if client_address is not None else current_client_address(),
        "via": via or current_via(),
        # Hash the masked text in full, then store a truncated excerpt: the digest stays
        # comparable across rows whose excerpt was cut, and neither is ever raw.
        "response_hash": (hashlib.sha256(response.encode("utf-8")).hexdigest()
                          if response is not None else None),
        "response_masked": response[:_MASKED_LIMIT] if response is not None else None,
        "injection_flags": int(injection_flags or 0),
    }


_INSERT = """
INSERT INTO public.tool_call_log
    (occurred_at, actor_id, actor_username, actor_kind, tool, resource_kind, resource,
     request_hash, request_masked, hit_count, citation_sources, pii_masked, outcome,
     duration_ms, client_address, via, response_hash, response_masked, injection_flags)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18,
        $19)
"""


async def record(*, actor: dict, tool: str, resource_kind: str, resource: List[str],
                 request_text: str, hit_count: int = 0,
                 citation_sources: Optional[List[str]] = None, pii_masked: int = 0,
                 outcome: str = "ok", duration_ms: Optional[int] = None,
                 client_address: Optional[str] = None, via: Optional[str] = None,
                 response_text: Optional[str] = None, injection_flags: int = 0) -> None:
    """Write one row. Never raises into the caller — a failed audit write is logged."""
    try:
        row = build_row(actor=actor, tool=tool, resource_kind=resource_kind,
                        resource=resource, request_text=request_text,
                        hit_count=hit_count, citation_sources=citation_sources,
                        pii_masked=pii_masked, outcome=outcome, duration_ms=duration_ms,
                        client_address=client_address, via=via,
                        response_text=response_text, injection_flags=injection_flags)
        # Lazy import, same reason as security_audit: app.api.connectors imports
        # app.api.auth at module load and this module is imported by route modules.
        from app.api.connectors import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire(timeout=2) as conn:
            await conn.execute(
                _INSERT, row["occurred_at"], row["actor_id"], row["actor_username"],
                row["actor_kind"], row["tool"], row["resource_kind"], row["resource"],
                row["request_hash"], row["request_masked"], row["hit_count"],
                row["citation_sources"], row["pii_masked"], row["outcome"],
                row["duration_ms"], row["client_address"], row["via"],
                row["response_hash"], row["response_masked"], row["injection_flags"],
            )
        counter = _calls.get()
        if counter is not None:
            counter[0] += 1
    except Exception:
        logger.error("tool_call_log: failed to record tool=%s actor=%s — this call is "
                     "not in the tool call log", tool, (actor or {}).get("username"),
                     exc_info=True)
