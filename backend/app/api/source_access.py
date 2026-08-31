"""The gate every route that touches a connector or a saved transform goes through.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (D2)

D1 (`0006_resource_ownership`) gave `connector_connections` and `saved_transforms` an
`owner_id`, and added `connector_members` / `transform_members` beside them. Nothing
read any of it: until this module, a source was still reachable by anyone who held
`connector:write`, which is what let one person edit or delete the connector someone
else created.

This is the wiring, and it is deliberately the same shape as `_collection_id` in
`app/api/ai_vectors.py` (A3):

- The *decision* is `app/resource_access.py`, shared with collections, so there is one
  precedence and not two nearly-identical ones. `SOURCE` / `TRANSFORM` say what an
  unowned row means for each kind — see that module for why it differs.
- The *lookup* is one query with a LEFT JOIN onto the members table, so a caller with
  no grant (every row that predates D1) simply gets `member_role = NULL` and behaves
  exactly as before ownership existed.
- The refusal is 403 for "exists, not yours" and 404 for "no such id", the same
  distinction the collection routes draw.

`resolve()` takes a connection because most connector routes already hold one and a
second acquire would be wasted. `require_access()` is for the handlers that do not —
they call a connector instance or a SQLAlchemy session instead — and acquires its own.

The membership routes for both kinds live here too rather than being written twice in
`connectors.py` and `transforms.py`: they are the same six lines of SQL with a
different table name, and the one thing they must not do is diverge on who is allowed
to call them.
"""
import logging
import uuid
from typing import NamedTuple, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_permission, require_user
from app.resource_access import SOURCE, TRANSFORM, AccessRules, may_read, may_write

logger = logging.getLogger(__name__)
router = APIRouter()


class Kind(NamedTuple):
    """One ownable resource kind: where it lives, where its grants live, and which
    unowned-fallback rules apply to it.

    `table`, `members` and `fk` are interpolated into SQL below. They come from the
    two module-level constants and never from a request — a kind is a constant of
    this module, not a parameter a caller can name.
    """
    label: str            # what the caller is told they cannot reach
    table: str
    members: str
    fk: str               # the members-table column pointing back at `table`.id
    rules: AccessRules
    write_permission: str  # what the membership routes for this kind require


CONNECTOR = Kind(
    label="connector", table="connector_connections", members="connector_members",
    fk="connection_id", rules=SOURCE, write_permission="connector:write",
)
TRANSFORM_KIND = Kind(
    label="transform", table="saved_transforms", members="transform_members",
    fk="transform_id", rules=TRANSFORM, write_permission="pipeline:write",
)


def caller_uuid(user: Optional[dict]):
    """The caller's id as a UUID, or None.

    None is a legitimate answer, not an error: it is what the internal automation
    principal carries (`{"id": None, "role": "admin", …}` from
    require_user_or_internal), and the LEFT JOIN below simply finds no grant for it —
    which is correct, since that principal passes on being an admin, not on a grant.
    """
    try:
        return uuid.UUID(str((user or {}).get("id")))
    except (ValueError, AttributeError, TypeError):
        return None


def _as_uuid(kind: Kind, resource_id) -> uuid.UUID:
    try:
        return uuid.UUID(str(resource_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, f"Invalid {kind.label} id")


async def resolve(c, kind: Kind, resource_id, user: dict, *, write: bool = False):
    """Load `resource_id` of `kind` and enforce read/write access, or raise.

    Returns the row (`id`, `owner_id`, `member_role`) so a caller that needs the
    owner — the list/detail responses do, to show whose it is — does not query twice.
    """
    rid = _as_uuid(kind, resource_id)
    row = await c.fetchrow(
        f"""SELECT r.id, r.owner_id, m.role AS member_role
            FROM {kind.table} r
            LEFT JOIN {kind.members} m ON m.{kind.fk} = r.id AND m.user_id = $2
            WHERE r.id = $1""",
        rid, caller_uuid(user),
    )
    if not row:
        raise HTTPException(404, f"{kind.label.capitalize()} not found")
    resource = {"owner_id": row["owner_id"]}
    member_role = row["member_role"] if "member_role" in row else None
    allowed = may_write(resource, user, member_role, kind.rules) if write \
        else may_read(resource, user, member_role, kind.rules)
    if not allowed:
        raise HTTPException(403, f"Not authorized for this {kind.label}.")
    return row


async def require_access(kind: Kind, resource_id, user: dict, *, write: bool = False):
    """`resolve()` for a handler that is not already holding a connection."""
    from app.api.connectors import get_db_pool   # local: connectors.py imports this module

    pool = await get_db_pool()
    async with pool.acquire() as c:
        return await resolve(c, kind, resource_id, user, write=write)


def visible_clause(kind: Kind, user: dict, alias: str, first_arg: int):
    """SQL predicate limiting a listing to what `user` may see, plus its arguments.

    Returns `("", [])` for an admin — no predicate at all rather than one that
    happens to be true, so the common case adds nothing to the query.

    The non-admin predicate is deliberately the SQL twin of `may_read`: owned by me,
    unowned (which for a source means visible to everyone, exactly as today), or named
    in a grant. EXISTS rather than a join, so a source shared with three people still
    lists once.
    """
    if (user or {}).get("role") == "admin":
        return "", []
    return (
        f"({alias}.owner_id = ${first_arg} OR {alias}.owner_id IS NULL "
        f"OR EXISTS (SELECT 1 FROM {kind.members} m "
        f"WHERE m.{kind.fk} = {alias}.id AND m.user_id = ${first_arg}))",
        [caller_uuid(user)],
    )


async def granted_roles(kind: Kind, user: dict) -> dict:
    """`{resource_id: role}` for every grant this caller holds on `kind`.

    One query for the whole listing, not one per row — the same reason
    `resource_access`'s functions take `member_role` instead of looking it up
    themselves. Used by a listing that cannot push the predicate into its own query
    (transforms lists through SQLAlchemy).
    """
    from app.api.connectors import get_db_pool

    uid = caller_uuid(user)
    if uid is None:
        return {}
    pool = await get_db_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            f"SELECT {kind.fk} AS rid, role FROM {kind.members} WHERE user_id = $1", uid)
    return {str(r["rid"]): r["role"] for r in rows}


def may_see(kind: Kind, row, user: dict, member_role: Optional[str] = None) -> bool:
    """`may_read` for a row already in hand — for a listing that cannot filter in SQL.

    `transforms.py` lists through SQLAlchemy and has no place to put the predicate
    above; it filters in Python instead, and this keeps that filter answering the same
    question as everything else here.
    """
    owner_id = getattr(row, "owner_id", None) if not isinstance(row, dict) else row.get("owner_id")
    return may_read({"owner_id": owner_id}, user, member_role, kind.rules)


# ── Sharing: the same three routes for both kinds ───────────────────────────────

class MemberGrant(BaseModel):
    username: str
    role: str   # "reader" | "editor"


async def _list_members(kind: Kind, resource_id: str, user: dict):
    from app.api.connectors import get_db_pool

    pool = await get_db_pool()
    async with pool.acquire() as c:
        # write=True, not read: the permission on the route says the caller may manage
        # sharing somewhere; this says they may manage it on *this* source. Without it
        # any connector:write holder could read (and, below, change) the membership of
        # a source they neither own nor were granted.
        row = await resolve(c, kind, resource_id, user, write=True)
        rows = await c.fetch(
            f"""SELECT u.username, m.role, m.granted_at
                FROM {kind.members} m JOIN users u ON u.id = m.user_id
                WHERE m.{kind.fk} = $1 ORDER BY u.username""",
            row["id"],
        )
        owner = await c.fetchrow(
            "SELECT username FROM users WHERE id = $1", row["owner_id"]
        ) if row["owner_id"] else None
    return {
        "id": str(row["id"]),
        # Both: the id is what a client compares against its own identity ("is this
        # mine?"), the username is what it can show to anyone else.
        "owner_id": str(row["owner_id"]) if row["owner_id"] else None,
        "owner": owner["username"] if owner else None,
        "members": [
            {"username": r["username"], "role": r["role"],
             "granted_at": r["granted_at"].isoformat() if r["granted_at"] else None}
            for r in rows
        ],
    }


async def _add_member(kind: Kind, resource_id: str, body: MemberGrant, user: dict):
    from app.api.connectors import get_db_pool

    if body.role not in ("reader", "editor"):
        raise HTTPException(400, "role must be 'reader' or 'editor'.")
    pool = await get_db_pool()
    async with pool.acquire() as c:
        row = await resolve(c, kind, resource_id, user, write=True)
        target = await c.fetchrow(
            "SELECT id FROM users WHERE username = $1", body.username.strip())
        if not target:
            raise HTTPException(404, f"No user '{body.username}'.")
        # Re-granting changes the role rather than erroring or duplicating: the
        # (resource, user) primary key from 0006 is what makes ON CONFLICT well-defined.
        await c.execute(
            f"""INSERT INTO {kind.members} ({kind.fk}, user_id, role, granted_by)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT ({kind.fk}, user_id)
                DO UPDATE SET role = EXCLUDED.role, granted_by = EXCLUDED.granted_by,
                              granted_at = now()""",
            row["id"], target["id"], body.role, caller_uuid(user),
        )
    return {"success": True, "id": str(row["id"]),
            "username": body.username, "role": body.role}


async def _remove_member(kind: Kind, resource_id: str, username: str, user: dict):
    from app.api.connectors import get_db_pool

    pool = await get_db_pool()
    async with pool.acquire() as c:
        row = await resolve(c, kind, resource_id, user, write=True)
        target = await c.fetchrow(
            "SELECT id FROM users WHERE username = $1", username.strip())
        if not target:
            raise HTTPException(404, f"No user '{username}'.")
        result = await c.execute(
            f"DELETE FROM {kind.members} WHERE {kind.fk} = $1 AND user_id = $2",
            row["id"], target["id"],
        )
    removed = int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
    if removed == 0:
        raise HTTPException(404, f"'{username}' has no grant on this {kind.label}.")
    return {"success": True, "id": str(row["id"]), "username": username}


@router.get("/connectors/{connection_id}/members",
            dependencies=[Depends(require_permission("connector:write"))])
async def list_connector_members(connection_id: str, user: dict = Depends(require_user)):
    """Who this source is shared with, and who owns it."""
    return await _list_members(CONNECTOR, connection_id, user)


@router.post("/connectors/{connection_id}/members",
             dependencies=[Depends(require_permission("connector:write"))])
async def add_connector_member(connection_id: str, body: MemberGrant,
                               user: dict = Depends(require_user)):
    """Share this source with one more person, as reader or editor."""
    return await _add_member(CONNECTOR, connection_id, body, user)


@router.delete("/connectors/{connection_id}/members",
               dependencies=[Depends(require_permission("connector:write"))])
async def remove_connector_member(connection_id: str, username: str,
                                  user: dict = Depends(require_user)):
    """Revoke one person's grant on this source."""
    return await _remove_member(CONNECTOR, connection_id, username, user)


@router.get("/transforms/{transform_id}/members",
            dependencies=[Depends(require_permission("pipeline:write"))])
async def list_transform_members(transform_id: str, user: dict = Depends(require_user)):
    return await _list_members(TRANSFORM_KIND, transform_id, user)


@router.post("/transforms/{transform_id}/members",
             dependencies=[Depends(require_permission("pipeline:write"))])
async def add_transform_member(transform_id: str, body: MemberGrant,
                               user: dict = Depends(require_user)):
    return await _add_member(TRANSFORM_KIND, transform_id, body, user)


@router.delete("/transforms/{transform_id}/members",
               dependencies=[Depends(require_permission("pipeline:write"))])
async def remove_transform_member(transform_id: str, username: str,
                                  user: dict = Depends(require_user)):
    return await _remove_member(TRANSFORM_KIND, transform_id, username, user)
