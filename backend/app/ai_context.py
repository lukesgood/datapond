"""
Per-request AI actor context — attributes LLM gateway spend/usage to the calling
DataPond user (multi-tenant cost governance).

LiteLLM logs the OpenAI `user` field as `end_user` in spend_logs and accepts a
`metadata` object. By stamping every chat/embed payload with the authenticated
user we get per-user spend out of the gateway (queryable via /global/spend, the
usage dashboard, or /customer/info) instead of one undifferentiated total.

Implemented with a ContextVar set once per request (by the route) so deep call
sites (_embed, rag chat, _call_litellm) don't need the user threaded through.
ContextVars propagate into asyncio.to_thread (copy_context), so sync gateway calls
see it too.
"""
from __future__ import annotations

import contextvars
from typing import Optional

_actor: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("ai_actor", default=None)


def set_actor(user: Optional[dict]) -> None:
    """Record the current request's user as the AI spend actor. No-op if user is None."""
    if not user:
        return
    uid = str(user.get("id") or user.get("username") or "anonymous")
    _actor.set({"id": uid, "name": user.get("username") or uid})


def actor_payload(app: str) -> dict:
    """Fields to merge into a LiteLLM chat/embed payload for attribution.

    Two channels, because they behave differently at the gateway.

    `user` becomes `end_user` in spend_logs. It is the only per-caller attribution
    that survives, which is why a route forgetting `set_actor` produces no
    attribution rather than a weaker one.

    The feature name goes in `metadata.tags`, landing in `request_tags`. It used to
    be sent as `metadata.app` — but LiteLLM replaces `metadata` in spend_logs with
    its own object (status, max_retries, cost_breakdown, …), so the client's value
    was silently discarded. Thirty-two consecutive live rows carried no feature tag
    at all. `request_tags` is preserved; the live rows show LiteLLM's own User-Agent
    entries sitting in it.

    A consequence worth stating: any code reading `metadata.user_id` back out of a
    spend log is unreachable. It was there as a fallback and could never fire.
    """
    a = _actor.get()
    tags = {"tags": [f"app:{app}"]}
    if not a:
        # Background work (the re-embedding scheduler) has no user. Its cost still
        # has to land somewhere nameable.
        return {"metadata": tags}
    return {"user": a["id"], "metadata": {**tags, "user_id": a["id"], "username": a["name"]}}
