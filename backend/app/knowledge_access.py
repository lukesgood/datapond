"""Who may read or change a collection — one decision, independent of the several
places that ask it.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (A3, D2)

`ai_collections.owner_id` plus "owner_id IS NULL means everyone may read" used to be
the whole access model, and it was checked inline wherever a route happened to touch
a collection — `_collection_id` in app/api/ai_vectors.py had one copy, list_collections
and knowledge_lineage each rebuilt a second and third version of the same rule
straight in SQL. `ai_collection_members` (0003_collection_members.sql, A2) adds a
fourth state — named people, not just the owner or the world — and landing it without
a single shared answer would have meant four places to get the new state wrong
instead of one.

D2 then gave connectors and transforms the same three columns, and asking the same
question about them from a second copy of this rule is the same mistake one level up.
So the precedence itself now lives in `app/resource_access.py`, parameterised by what
an *unowned* resource means for a given kind, and this module is the collection's
answer to that parameter: `resource_access.KNOWLEDGE`.

The precedence is unchanged — admin, then owner, then an explicit `ai_collection_members`
grant (`editor` reads and writes, `reader` only reads), then the legacy
`owner_id IS NULL` global collection, which anyone holding `knowledge:read` may read
and only an admin may write. `app/resource_access.py`'s docstring carries the full
reasoning, including why the unowned *write* rule differs between a collection and a
connector.

Both functions keep the signature A3's call sites use: `collection` is anything
carrying `owner_id` (a dict or an asyncpg Record both work); `user` is anything
carrying `id` and `role`; `member_role` is `None`, `"reader"` or `"editor"` — whatever
`ai_collection_members.role` holds for this exact (collection, user) pair, resolved by
the caller. Neither does I/O, so a caller listing many collections can load every
grant once and call these in a loop.
"""
from typing import Optional

from app import resource_access
from app.resource_access import KNOWLEDGE


def may_read(collection: dict, user: dict, member_role: Optional[str]) -> bool:
    """May `user` read `collection`? See the module docstring for the precedence."""
    return resource_access.may_read(collection, user, member_role, KNOWLEDGE)


def may_write(collection: dict, user: dict, member_role: Optional[str]) -> bool:
    """May `user` change `collection` — ingest, update, schedule, or delete it?

    Only `editor` membership grants this; `reader` grants read alone. The legacy
    global collection (`owner_id IS NULL`) has no owner to delegate write from, so
    only an administrator may write to it — unchanged from before membership
    existed, and what keeps a shared collection from becoming a free-for-all the
    moment it stops having a single owner.
    """
    return resource_access.may_write(collection, user, member_role, KNOWLEDGE)
