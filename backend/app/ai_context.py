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
    """Fields to merge into a LiteLLM chat/embed payload for per-user attribution.
    `app` tags the feature (ai_sql / ai_rag / ai_embed) for breakdowns."""
    a = _actor.get()
    if not a:
        return {"metadata": {"app": app}}
    return {"user": a["id"], "metadata": {"app": app, "user_id": a["id"], "username": a["name"]}}
