"""Who may run which action.

Extracted from gate._authorize, which interleaved this decision with the chat panel's
audit writes. The decision belongs to every surface that offers actions; the recording
does not — the panel writes chat_action_refused, the MCP server writes a tool_call_log
row and returns a protocol error. So this module raises and returns, and knows nothing
about stores, audit events or HTTP.
"""
from typing import Set

from app.chat.actions import Action
from app.component_guard import capability_on
from app.permissions import permissions_for


class NotPermitted(Exception):
    """The caller does not hold the action's permission."""

    def __init__(self, action: Action):
        self.action = action
        self.required = action.permission
        super().__init__(
            f"'{action.permission}' permission required to {action.label.lower()}.")


class CapabilityOff(Exception):
    """The action needs a component this deployment does not run."""

    def __init__(self, action: Action):
        self.action = action
        self.required = action.capability
        super().__init__(
            f"{action.label} needs a component this deployment does not run.")


def held_permissions(user: dict) -> Set[str]:
    """A service-account key carries its own set (role narrowed by scopes); a person is
    judged by role. Same rule as require_permission, so the gate, the API and the MCP
    server agree. An explicit empty list means a key that was granted nothing, which is
    why this tests for None rather than falsiness."""
    granted = user.get("permissions")
    return set(granted) if granted is not None else set(permissions_for(user.get("role")))


def authorize(action: Action, user: dict) -> None:
    """Raise unless this caller may run this action on this deployment.

    The capability half is recomputed from the server's own environment by the same
    predicate the route guards use — a map a client sent is never the one that decides.
    """
    if action.permission not in held_permissions(user):
        raise NotPermitted(action)
    if action.capability and not capability_on(action.capability):
        raise CapabilityOff(action)
