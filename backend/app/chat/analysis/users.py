"""Granting a role — the one action that changes who can do what.

**The identifier.** The brief that shaped this module named the parameter `email` and
a helper `_user_by_email`. That assumption already shipped once on this branch and was
wrong: `knowledge.py`'s `MemberGrantParams`/`MemberRemoveParams` resolve collection
membership strictly on `username`, with a field description saying so, because
`add_member`/`remove_member` look people up by `username`. Reading `schema/auth.sql`
and `app/api/auth.py` shows the same shape holds everywhere a person is resolved to an
account in this codebase: `email` is `NOT NULL UNIQUE` but is only ever used for the
email-based password-recovery flow; login (`SELECT ... WHERE username=$1`), the
default-admin seed, and the LDAP directory upsert all key on `username`, and the
default admin's own `username` is `"admin"`, not an email address. `username` is
therefore the identifier that actually resolves a person reliably here, so that is
what this module's parameter, helper, and `target_field` are named — matching the
precedent `knowledge.py` already set, not the brief's guess.

**Why the three constraints live at execution, not in the schema.** The params schema
shapes what the model may propose. A forged proposal — someone posting this action id
and parameters directly, or a later change that widens the schema — never goes through
the schema at all, so the schema cannot be what stops it. These three checks run in
`grant_role` itself, before `update_user` is reached, and each raises rather than
silently narrowing the request:

1. No grant may exceed the caller's own effective permissions — you cannot hand out
   what you do not hold.
2. `admin` is never grantable through the assistant, because `admin` carries
   `user:manage` and an assistant that can make administrators is a different product
   from this one.
3. Nobody may change their own role through the assistant. A holder of `user:manage`
   can still do it in the UI, so this costs them nothing, and it closes the path
   injected content aims at first.
"""
from typing import Callable, Dict, Literal, Optional

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r
from app.chat.dependents import Dependents
from app.permissions import ASSIGNABLE_ROLES, ROLE_PERMISSIONS, permissions_for

# Excludes every role that carries user:manage, not just the name "admin" — a role
# added later that also carries user:manage must be excluded too, and constraint 1
# would not catch it (an admin caller holds user:manage, so granted - held is empty
# for such a role). Expressing the property, not a proxy for it, is what keeps this
# holding if that ever happens — see constraint 2 in the module docstring.
GRANTABLE = frozenset(
    r for r in ASSIGNABLE_ROLES if "user:manage" not in ROLE_PERMISSIONS.get(r, ()))

# Every role, admin included, is offered in the schema — the schema only shapes what
# the model may propose; `grant_role` below is what a forged proposal actually meets.
_Role = Literal[tuple(sorted(ASSIGNABLE_ROLES))]


class GrantRoleParams(_Strict):
    username: str = Field(
        description="The person's login username, not their email address — role "
                    "assignment resolves strictly on username, the same identifier "
                    "collection membership uses.")
    role: _Role


async def _user_by_username(username: str) -> Optional[dict]:
    """A thin reader over the users table. Returns id/username/email/role, or None."""
    from app.api.auth import _get_pool

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, email, role FROM users WHERE username = $1",
            username)
    return dict(row) if row else None


async def grant_role(params: dict, user: dict) -> dict:
    """Set someone's role, within three limits that hold even for an admin.

    Enforced here rather than in the params schema because the schema only shapes
    what the model may propose; this is what a forged proposal meets.
    """
    from app.api.auth import update_user
    # Lazy import: app.chat.gate imports names from app.chat.actions that do not
    # exist yet while actions.py is still assembling ACTIONS out of this package —
    # a top-level import here would be circular.
    from app.chat.gate import _held_permissions

    role = params["role"]
    if role not in GRANTABLE:
        # `admin` carries user:manage, and an assistant that can make administrators
        # is a different product from this one.
        raise PermissionError(f"{role!r} cannot be granted through the assistant.")

    target = await _user_by_username(params["username"])
    if target is None:
        raise ValueError(f"No account for {params['username']!r}.")

    if str(target.get("id")) == str(user.get("id")):
        # An admin can still do this in the UI. Refusing here costs them nothing and
        # closes the path injected content aims at first.
        raise PermissionError("You cannot change your own role through the assistant.")

    granted = set(ROLE_PERMISSIONS.get(role, ()))
    # Same rule the rest of the codebase states three times (app/api/auth.py:385-387,
    # auth.py:1043, gate.py:62): an explicit `permissions` set is authoritative,
    # including when it is empty — a service key scoped down to nothing must not
    # silently regain its role's full permission set here. `_held_permissions` is
    # the one answer to this question; this module does not write a second one.
    held = _held_permissions(user)
    beyond = sorted(granted - held)
    if beyond:
        raise PermissionError(
            f"You do not hold {', '.join(beyond)}, so you cannot grant them.")

    return {"user": await update_user(str(target["id"]), {"role": role}, admin=user)}


async def preview_grant_role(params: dict, user: dict) -> dict:
    """Who this is, their role today, and the role being proposed — the dependents
    callable below answers what that change actually grants."""
    username, role = params["username"], params["role"]
    try:
        target = await _user_by_username(username)
    except Exception as e:
        return {"username": username, "new_role": role,
                "summary": f"Set {username!r}'s role to {role!r} — their current "
                          f"role could not be read to confirm this: {e}"}
    if target is None:
        return {"username": username, "new_role": role,
                "summary": f"Set {username!r}'s role to {role!r} — no account with "
                          f"that username was found."}
    return {"username": username, "current_role": target.get("role"), "new_role": role,
            "summary": f"Change {username!r}'s role from {target.get('role')!r} to "
                      f"{role!r}."}


async def dependents_grant_role(params: dict, user: dict) -> dict:
    """The permissions this person gains that they do not have today — not the role
    name. "They become an admin" is not something an approver can weigh; the specific
    things they will newly be able to do is."""
    d = Dependents("users.grant_role")
    username, role = params["username"], params["role"]

    try:
        target = await _user_by_username(username)
    except Exception as e:
        d.skipped(f"Could not look up {username!r} to check what this grant changes: "
                  f"{e}")
        return d.done()
    if target is None:
        d.skipped(f"No account for {username!r} — what this grant would change could "
                  f"not be determined.")
        return d.done()

    current_role = target.get("role") or "viewer"
    held = permissions_for(current_role)
    new_perms = set(ROLE_PERMISSIONS.get(role, ()))
    gained = sorted(new_perms - held)
    lost = sorted(held - new_perms)
    for perm in gained:
        d.item("permission", perm,
               f"{username} moves from {current_role!r} to {role!r} and gains "
               f"{perm}, which they do not hold today.")
    for perm in lost:
        # A downgrade with no gained items and no not_checked entries would, per
        # Dependents' own docstring, be the affirmative claim that nothing depends
        # on this change — false for a role that loses permissions. Named as a loss,
        # not folded into "gains", so an approver can tell a grant from a revocation
        # at a glance.
        d.item("permission", perm,
               f"{username} moves from {current_role!r} to {role!r} and loses "
               f"{perm}, which they hold today.")
    return d.done()


ACTIONS = (
    Action("users.grant_role", "Grant role",
           "Change a person's role, and with it the permissions they hold. `admin` "
           "is never a valid target — it carries user:manage and cannot be granted "
           "through the assistant — and a caller cannot grant permissions beyond "
           "their own, or change their own role.",
           ("*",), "user:manage", ActionKind.DESTRUCTIVE, GrantRoleParams,
           target_field="username"),
)

EXECUTORS: Dict[str, Callable] = {
    "users.grant_role": grant_role,
}

RESOLVERS: Dict[str, Callable] = {
    "users.grant_role": _r("app.api.auth", "update_user"),
}

PREVIEWERS: Dict[str, Callable] = {
    "users.grant_role": preview_grant_role,
}

DEPENDENTS: Dict[str, Callable] = {
    "users.grant_role": dependents_grant_role,
}
