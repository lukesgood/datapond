"""Who may read or change a collection — one decision, independent of the several
places that ask it.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (A3)

`ai_collections.owner_id` plus "owner_id IS NULL means everyone may read" used to be
the whole access model, and it was checked inline wherever a route happened to touch
a collection — `_collection_id` in app/api/ai_vectors.py had one copy, list_collections
and knowledge_lineage each rebuilt a second and third version of the same rule
straight in SQL. `ai_collection_members` (0003_collection_members.sql, A2) adds a
fourth state — named people, not just the owner or the world — and landing it without
a single shared answer would have meant four places to get the new state wrong
instead of one. This module is that one place.

Precedence, high to low:
  1. admin               — sees and changes everything, same as everywhere else in
                            the product.
  2. owner                — created it, keeps full control of it.
  3. explicit membership — `editor` may read and write; `reader` may only read.
                            Checked before the legacy-global fallback below, so a
                            membership row is meaningful even on an owner_id IS NULL
                            collection (an editor grant there still grants write,
                            which the fallback alone would not).
  4. owner_id IS NULL    — the legacy "global" collection predates membership
     (legacy global)       entirely. Anyone holding `knowledge:read` may read it —
                            the same permission the caller already needed to reach
                            any route this gates — but nobody may write to it except
                            an admin, because there is no owner left to delegate
                            write from.
  5. otherwise           — no. A private collection with no grant is exactly that:
                            private.

Both functions take the same three arguments so a caller cannot accidentally check
read where it meant write: `collection` is anything carrying `owner_id` (a dict or an
asyncpg Record both work); `user` is anything carrying `id` and `role`; `member_role`
is `None`, `"reader"`, or `"editor"` — whatever `ai_collection_members.role` holds for
this exact (collection, user) pair, resolved by the caller before either function
runs. Neither function does I/O: the membership lookup is the caller's job precisely
so a caller listing many collections can load every grant once and call these in a
loop, rather than paying a query per collection.
"""
from typing import Optional

from app.permissions import has_permission


def _is_admin(user: Optional[dict]) -> bool:
    return (user or {}).get("role") == "admin"


def _is_owner(collection: Optional[dict], user: Optional[dict]) -> bool:
    owner_id = (collection or {}).get("owner_id")
    if owner_id is None:
        return False
    uid = (user or {}).get("id")
    if uid is None:
        return False
    return str(owner_id) == str(uid)


def may_read(collection: dict, user: dict, member_role: Optional[str]) -> bool:
    """May `user` read `collection`? See the module docstring for the precedence."""
    if _is_admin(user):
        return True
    if _is_owner(collection, user):
        return True
    if member_role in ("reader", "editor"):
        return True
    if (collection or {}).get("owner_id") is None:
        return has_permission((user or {}).get("role"), "knowledge:read")
    return False


def may_write(collection: dict, user: dict, member_role: Optional[str]) -> bool:
    """May `user` change `collection` — ingest, update, schedule, or delete it?

    Only `editor` membership grants this; `reader` grants read alone. The legacy
    global collection (`owner_id IS NULL`) has no owner to delegate write from, so
    only an administrator may write to it — unchanged from before membership
    existed, and what keeps a shared collection from becoming a free-for-all the
    moment it stops having a single owner.
    """
    if _is_admin(user):
        return True
    if _is_owner(collection, user):
        return True
    if member_role == "editor":
        return True
    return False
