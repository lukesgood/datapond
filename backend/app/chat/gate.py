"""The confirmation gate between a proposal and a change.

Design §5. The model proposes; a human approves; the server executes what it
previewed. Each of those is a separate step with its own record, because the value of
a confirmation is entirely in what it is confirming.

Two properties this module exists to hold:

**The approved artifact is the executed artifact.** Approval carries an invocation id,
never parameters. The server runs the parameters it stored and previewed, so a client
cannot approve one thing and submit another — which is what would make the preview
decorative rather than binding.

**Permission is checked at both ends.** `actions_for` keeps an action out of the
model's vocabulary, and this module checks again at proposal *and* at approval. Time
passes between those two, and a role can change inside it.

Storage is behind `InvocationStore` so the gate is testable without a database. The
gate is the part that must be right, and it is right or wrong independently of
Postgres.
"""
import logging
from typing import Any, Awaitable, Callable, Optional, Protocol

from app.chat.actions import (
    Action,
    ActionKind,
    InvalidParams,
    UnknownAction,
    actions_for,
    resolve,
    validate_params,
)
from app.permissions import permissions_for

logger = logging.getLogger(__name__)


class ActionRefused(Exception):
    """The gate declined. Carries a reason meant for the user, not the model."""


class InvocationStore(Protocol):
    async def create(self, **fields) -> dict: ...
    async def get(self, invocation_id: str) -> Optional[dict]: ...
    async def update(self, invocation_id: str, **fields) -> dict: ...
    async def record_audit(self, event: str, user_id: Optional[str],
                           user_email: Optional[str], details: dict) -> None: ...


def _held_permissions(user: dict) -> set:
    """A service-account key carries its own set (role narrowed by scopes); a person
    is judged by role. Same rule as require_permission, so the gate and the API agree."""
    granted = user.get("permissions")
    return set(granted) if granted is not None else set(permissions_for(user.get("role")))


def _require_owner(invocation: dict, user: dict) -> None:
    """Only the person the action was offered to may resolve it.

    Otherwise a colleague holding the same role could confirm a change someone else
    was asked about, and the audit trail would name the wrong approver — which is the
    one thing the trail exists to get right.
    """
    if invocation.get("user_id") and invocation["user_id"] != user.get("id"):
        raise ActionRefused("That request belongs to a different conversation.")


async def _audit(store: InvocationStore, event: str, user: dict, **details) -> None:
    # The human is always the actor. An audit log that attributes a change to "the
    # assistant" has lost the only fact worth recording.
    try:
        # user_email as well as user_id: the audit viewer renders the former, and a
        # trail that says "someone executed this" answers nothing.
        await store.record_audit(event, user.get("id"), user.get("username"),
                                 {"via": "chat", **details})
    except Exception as e:  # bookkeeping must not fail the request
        logger.warning(f"[chat] audit write failed for {event}: {e}")


async def _maybe_await(result: Any) -> Any:
    if isinstance(result, Awaitable):
        return await result
    return result


async def _authorize(action: Action, user: dict, page: str, store: InvocationStore,
                     stage: str) -> None:
    if action.permission not in _held_permissions(user):
        await _audit(store, "chat_action_refused", user,
                     action=action.id, stage=stage, reason="permission",
                     required=action.permission)
        raise ActionRefused(
            f"'{action.permission}' permission required to {action.label.lower()}.")


async def propose(
    action_id: Any,
    params: Any,
    *,
    user: dict,
    page: str,
    store: InvocationStore,
    executor: Optional[Callable] = None,
    previewer: Optional[Callable] = None,
    conversation_id: Optional[str] = None,
    request_text: Optional[str] = None,
) -> dict:
    """Validate a proposal and either run it (read) or park it for approval (write).

    `executor`/`previewer` are injected rather than read off the Action so this module
    stays free of every subsystem the actions touch, and so tests can exercise the gate
    without a catalog, an engine, or a model.
    """
    try:
        action = resolve(action_id)
    except UnknownAction as e:
        await _audit(store, "chat_action_refused", user,
                     action=str(action_id)[:120], stage="propose", reason="unknown_action")
        raise ActionRefused("That is not something I can do here.") from e

    await _authorize(action, user, page, store, stage="propose")

    try:
        clean = validate_params(action, params)
    except InvalidParams as e:
        await _audit(store, "chat_action_refused", user,
                     action=action.id, stage="propose", reason="invalid_params")
        raise ActionRefused(str(e)) from e

    preview = None
    if action.kind is not ActionKind.READ and previewer is not None:
        # Computed server-side by the same code path that will execute. A summary the
        # model wrote of its own intent is a second chance to be wrong the same way.
        preview = await _maybe_await(previewer(clean, user))

    invocation = await store.create(
        action_id=action.id, params=clean, preview=preview, page=page,
        conversation_id=conversation_id, user_id=user.get("id"), status="proposed",
        # The message that asked for this — the only transcript kept, and only
        # because a change needs a reason on record. See design §9.
        request_text=(request_text or "")[:2000] or None,
    )
    await _audit(store, "chat_action_proposed", user, action=action.id,
                 invocation=invocation["id"], kind=action.kind.value)

    if action.kind is ActionKind.READ:
        return await _execute(invocation, action, user, store, executor)
    return invocation


async def approve(invocation_id: str, *, user: dict, store: InvocationStore,
                  executor: Optional[Callable] = None) -> dict:
    """Run a proposed invocation. Takes an id — never parameters."""
    invocation = await store.get(invocation_id)
    if not invocation:
        raise ActionRefused("That request is no longer available.")
    if invocation.get("status") != "proposed":
        raise ActionRefused(
            f"Already {invocation.get('status')}; a request can only be approved once.")

    _require_owner(invocation, user)
    action = resolve(invocation["action_id"])
    await _authorize(action, user, invocation.get("page", "*"), store, stage="approve")

    await _audit(store, "chat_action_approved", user,
                 action=action.id, invocation=invocation_id)
    await store.update(invocation_id, status="approved", approved_by=user.get("id"))
    return await _execute(invocation, action, user, store, executor)


async def reject(invocation_id: str, *, user: dict, store: InvocationStore) -> dict:
    invocation = await store.get(invocation_id)
    if not invocation:
        raise ActionRefused("That request is no longer available.")
    if invocation.get("status") != "proposed":
        raise ActionRefused(f"Already {invocation.get('status')}.")
    _require_owner(invocation, user)
    await _audit(store, "chat_action_rejected", user,
                 action=invocation["action_id"], invocation=invocation_id)
    return await store.update(invocation_id, status="rejected")


async def _execute(invocation: dict, action: Action, user: dict,
                   store: InvocationStore, executor: Optional[Callable]) -> dict:
    if executor is None:
        await store.update(invocation["id"], status="failed",
                           error="No executor registered for this action")
        raise ActionRefused(f"{action.label} is not available in this deployment.")
    try:
        # The stored parameters, not anything the client sent with the approval.
        result = await _maybe_await(executor(invocation["params"], user))
    except Exception as e:
        logger.warning(f"[chat] {action.id} failed: {e}")
        await store.update(invocation["id"], status="failed", error=str(e)[:500])
        await _audit(store, "chat_action_failed", user,
                     action=action.id, invocation=invocation["id"], error=str(e)[:200])
        raise ActionRefused(f"{action.label} failed: {e}") from e

    updated = await store.update(invocation["id"], status="executed", result=result)
    await _audit(store, "chat_action_executed", user,
                 action=action.id, invocation=invocation["id"])
    return updated
