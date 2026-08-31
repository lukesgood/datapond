"""Who may read or change a resource that has an owner — one decision, several kinds.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (D2)

A3 wrote this rule for collections in `app/knowledge_access.py`. D1 gave connectors
and transforms the same three columns (`owner_id`, plus a members table keyed on
(resource, user) with a reader/editor role), and D2 has to ask the same question about
them on every route that touches one. Two files holding nearly the same precedence is
how one of them ends up wrong — so the precedence lives here once, and
`knowledge_access` is now a thin wrapper that keeps A3's call sites and its name.

Precedence, high to low, for every kind:

  1. admin              — sees and changes everything, as everywhere else in the
                          product.
  2. owner              — created it, keeps full control of it.
  3. explicit grant     — `editor` reads and writes; `reader` only reads. Checked
                          *before* the unowned fallback below, so a grant means
                          something even on an unowned resource (an editor grant
                          there still grants write, which the fallback alone would
                          not).
  4. unowned            — `owner_id IS NULL`. What that permits is the one thing
     (the fallback)       that differs between kinds, and it is `AccessRules` below.
  5. otherwise          — no.

Neither function does I/O. `member_role` is whatever the members table holds for this
exact (resource, user) pair — `None`, `"reader"` or `"editor"` — resolved by the
caller, precisely so a caller listing many resources can load every grant in one query
and call these in a loop rather than paying a query per row.

### Why the unowned fallback is a parameter and not a constant

Because "unowned" describes two genuinely different situations:

- An unowned **collection** is the deliberate everyone-can-read artifact. A3 made
  writing to it admin-only: there is no owner to delegate write from, and a shared
  collection must not become a free-for-all the moment it stops having one.
- An unowned **connector or transform** is, on the day D2 ships, *every connector and
  transform that exists*. `owner_id` arrived in 0006 with nothing to backfill it from
  (see that migration's header for why it must stay nullable). Admin-only writes would
  therefore take source management away from every data engineer on every existing
  deployment — an outage dressed as a security fix. So an unowned source keeps exactly
  today's rule, "anyone holding the write permission this route already required", and
  ownership does its work on what gets created from now on.

Reading follows the same logic: an unowned collection is read by whoever holds
`knowledge:read`, the permission its routes already require, while the connector and
transform read routes require no permission at all today (`connector:read` is defined
in app/permissions.py but no route enforces it — a separate gap, and closing it here
would be a second change hiding inside this one). `global_read=None` says exactly
that: any authenticated caller, which is who can read them today.
"""
from typing import NamedTuple, Optional

from app.permissions import has_permission


class AccessRules(NamedTuple):
    """What `owner_id IS NULL` permits for one kind of resource.

    `global_read` / `global_write` are permission names, or None. For reads, None
    means "any authenticated caller" — the caller has already passed authentication
    and whatever gate the route itself carries. For writes, None means "admin only",
    because a write fallback that admits everyone would make ownership decorative.
    """
    global_read: Optional[str]
    global_write: Optional[str]


# A collection: A3's rule, unchanged.
KNOWLEDGE = AccessRules(global_read="knowledge:read", global_write=None)

# A connector, and a saved transform. Both unowned-writable by the permission their
# routes already require, for the reason in the module docstring.
SOURCE = AccessRules(global_read=None, global_write="connector:write")
TRANSFORM = AccessRules(global_read=None, global_write="pipeline:write")


def _is_admin(user: Optional[dict]) -> bool:
    # The role alone, not narrowed by a service-account key's scopes — the same
    # asymmetry A3 shipped, kept rather than quietly changed here: a key issued from
    # an admin account is an admin identity everywhere else in the product too, and
    # narrowing that is a decision about service accounts, not about ownership.
    return (user or {}).get("role") == "admin"


def _is_owner(resource: Optional[dict], user: Optional[dict]) -> bool:
    owner_id = (resource or {}).get("owner_id")
    if owner_id is None:
        return False
    uid = (user or {}).get("id")
    if uid is None:
        return False
    # asyncpg returns uuid.UUID, the token carries a string. Compared as-is, an owner
    # is locked out of their own resource.
    return str(owner_id) == str(uid)


def _holds(user: Optional[dict], permission: Optional[str]) -> bool:
    if permission is None:
        return False
    granted = (user or {}).get("permissions")
    if granted is not None:
        # A service-account key carries its own effective set; when present it is
        # authoritative, including when it is empty. Same rule require_permission()
        # applies in app/api/auth.py.
        return permission in granted
    return has_permission((user or {}).get("role"), permission)


def may_read(resource: Optional[dict], user: Optional[dict],
             member_role: Optional[str], rules: AccessRules) -> bool:
    """May `user` read `resource`? See the module docstring for the precedence."""
    if _is_admin(user):
        return True
    if _is_owner(resource, user):
        return True
    if member_role in ("reader", "editor"):
        return True
    if (resource or {}).get("owner_id") is None and resource is not None:
        return True if rules.global_read is None else _holds(user, rules.global_read)
    return False


def may_write(resource: Optional[dict], user: Optional[dict],
              member_role: Optional[str], rules: AccessRules) -> bool:
    """May `user` change `resource` — edit it, run it, schedule it, delete it?

    Only an `editor` grant carries this; `reader` carries read alone.
    """
    if _is_admin(user):
        return True
    if _is_owner(resource, user):
        return True
    if member_role == "editor":
        return True
    if (resource or {}).get("owner_id") is None and resource is not None:
        return _holds(user, rules.global_write)
    return False
