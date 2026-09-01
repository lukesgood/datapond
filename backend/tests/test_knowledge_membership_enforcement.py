"""Every path that reads or changes a collection asks the same question.

app/knowledge_access.py (A3) is the pure decision. This file is the wiring proof: a
model enforced on four of six paths is a suggestion, so the header test below drives
every route this module exposes for an *existing, named* collection through the same
non-member and asserts none of them lets a stranger in. Adding a new route that reads
a collection without adding it to PATHS is the failure mode this guards — the loop
means a forgotten path fails loudly instead of quietly working.

Each handler is called directly as a coroutine, not through the FastAPI test client:
the same pattern tests/test_security_boundaries.py already uses for exactly this
reason — a route dependency like require_admin_or_internal only runs when FastAPI's
own machinery resolves it, so calling the function is *more* honest about what
`_collection_id` itself enforces, independent of whatever gate happens to sit in
front of it at the HTTP layer.
"""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app.api import ai_vectors


OWNER_ID = "00000000-0000-0000-0000-0000000000a1"
OTHER_ID = "00000000-0000-0000-0000-0000000000a2"
ADMIN = {"id": "00000000-0000-0000-0000-0000000000ad", "role": "admin"}
OWNER = {"id": OWNER_ID, "role": "viewer"}
OTHER = {"id": OTHER_ID, "role": "viewer"}   # knowledge:write-capable in some tests

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


async def _aval(value):
    return value


class _CollConn:
    """Answers exactly the join query `_collection_id` runs, for one fixed
    collection. Every handler below raises out of `_collection_id` before it
    reaches a second query when the caller is refused — which is the property
    under test — so nothing past `fetchrow` needs to be real.
    """

    def __init__(self, owner_id, member_role=None):
        self.row = {
            "id": "coll-id", "owner_id": owner_id, "member_role": member_role,
            # ingest() re-fetches these on the same connection once _collection_id
            # has let it through; irrelevant to every *refused* path (they all raise
            # out of _collection_id first) but needed by the one end-to-end success
            # path this fixture also drives.
            "chunk_preset": None, "chunk_size": None, "chunk_overlap": None,
        }

    async def fetchrow(self, query, *args):
        return self.row

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        return "DELETE 0"

    async def executemany(self, query, rows):
        return None

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *a):
                return False

        return _Tx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _install(monkeypatch, owner_id, member_role=None):
    conn = _CollConn(owner_id, member_role)
    monkeypatch.setattr(ai_vectors, "get_db_pool", lambda: _aval(_Pool(conn)))
    monkeypatch.setattr(ai_vectors, "ensure_vector_schema", lambda pool: _aval(None))
    monkeypatch.setattr(ai_vectors, "_embed", lambda texts: _aval([[0.0] * 4 for _ in texts]))
    return conn


# ── every path, one non-member, one loop ─────────────────────────────────────

def _paths(name):
    """(label, coroutine) for every route in ai_vectors.py that resolves an
    *existing* collection by name. New routes belong in this list — that is the
    point of the loop below.
    """
    source = ai_vectors.SourceIngest(type="s3", bucket="docs")
    return [
        ("ingest", ai_vectors.ingest(
            name, ai_vectors.IngestRequest(documents=[]), OTHER)),
        ("ingest-source", ai_vectors.ingest_source(name, source, OTHER)),
        ("schedule (write)", ai_vectors.schedule_ingest(
            name, ai_vectors.ScheduleRequest(source=source), OTHER)),
        ("schedule (read)", ai_vectors.get_schedule(name, OTHER)),
        ("schedule (delete)", ai_vectors.delete_schedule(name, OTHER)),
        ("update", ai_vectors.update_collection(
            name, ai_vectors.CollectionUpdate(description="x"), OTHER)),
        ("delete-source", ai_vectors.delete_source(name, "doc.txt", OTHER)),
        ("composition", ai_vectors.collection_composition(name, OTHER)),
        ("delete-collection", ai_vectors.delete_collection(name, OTHER)),
        ("search", ai_vectors.search(
            ai_vectors.SearchRequest(collection=name, query="q"), OTHER)),
        ("rag", ai_vectors.rag(
            ai_vectors.RagRequest(collection=name, question="q"), OTHER)),
        ("members (list)", ai_vectors.list_members(name, OTHER)),
        ("members (add)", ai_vectors.add_member(
            name, ai_vectors.MemberGrant(username="other", role="editor"), OTHER)),
        ("members (remove)", ai_vectors.remove_member(name, "someone", OTHER)),
    ]


def test_a_non_member_cannot_reach_a_private_collection_through_any_path(monkeypatch):
    """OTHER is not the owner, not an admin, and — member_role=None — not a member
    either. Every single one of the routes above must refuse with 403, and none
    may fall through and touch the collection some other way (a 200, a 404 for
    the wrong reason, or a silent no-op would all be the model becoming a
    suggestion on that one path)."""
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role=None)
    failures = []
    for label, coro in _paths("private"):
        try:
            _run(coro)
            failures.append(f"{label}: did not raise")
        except HTTPException as exc:
            if exc.status_code != 403:
                failures.append(f"{label}: raised {exc.status_code}, not 403")
    assert not failures, "paths that let a non-member through:\n  " + "\n  ".join(failures)


# ── backwards compatibility: no membership rows at all ───────────────────────

def test_owner_access_is_unchanged_when_no_membership_row_exists(monkeypatch):
    """Every collection that existed before A2 has zero rows in
    ai_collection_members. The LEFT JOIN in _collection_id must still resolve
    `member_role` to None for those — not error, not deny the owner — exactly as
    if the table were empty, because for those collections it is."""
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role=None)
    assert _run(ai_vectors._collection_id(
        _CollConn(uuid.UUID(OWNER_ID)), "mine", OWNER, write=True)) == "coll-id"


def test_global_read_is_unchanged_when_no_membership_row_exists(monkeypatch):
    """owner_id IS NULL, no membership row: any authenticated caller with
    knowledge:read (the route's own gate) can still read it, same as before A2."""
    conn = _CollConn(owner_id=None, member_role=None)
    assert _run(ai_vectors._collection_id(conn, "shared", OTHER)) == "coll-id"
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors._collection_id(conn, "shared", OTHER, write=True))
    assert exc.value.status_code == 403


def test_member_role_missing_from_the_row_entirely_is_treated_as_no_membership():
    """A plain dict fixture — or a hand-rolled query that forgot the LEFT JOIN
    alias — with no 'member_role' key at all must not KeyError. `.get()` is what
    makes a dict lacking the column behave like a NULL from the real JOIN."""
    row_without_the_column = {"id": "coll-id", "owner_id": uuid.UUID(OWNER_ID)}

    class _Bare:
        async def fetchrow(self, query, *args):
            return row_without_the_column

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    assert _run(ai_vectors._collection_id(_Bare(), "mine", OWNER)) == "coll-id"


# ── explicit membership grants read and/or write ─────────────────────────────

def test_a_reader_grant_allows_read_but_not_write(monkeypatch):
    conn = _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role="reader")
    assert _run(ai_vectors._collection_id(conn, "private", OTHER)) == "coll-id"
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors._collection_id(conn, "private", OTHER, write=True))
    assert exc.value.status_code == 403


def test_an_editor_grant_allows_read_and_write(monkeypatch):
    conn = _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role="editor")
    assert _run(ai_vectors._collection_id(conn, "private", OTHER)) == "coll-id"
    assert _run(ai_vectors._collection_id(conn, "private", OTHER, write=True)) == "coll-id"


def test_an_editor_grant_reaches_ingest_end_to_end(monkeypatch):
    """Not just the gate function in isolation — the actual route handler, with
    an editor grant, must be let through rather than 403ing before it gets the
    chance to ingest anything."""
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role="editor")
    out = _run(ai_vectors.ingest(
        "private", ai_vectors.IngestRequest(documents=[]), OTHER))
    assert out["success"] is True


# ── the membership API itself ─────────────────────────────────────────────────

class _MembersConn:
    """Distinguishes queries by the table they name, since add/remove/list each
    run more than one statement on the same connection within one handler."""

    def __init__(self, owner_id, member_role=None, target_user_id="target-id"):
        self.owner_id = owner_id
        self.member_role = member_role
        self.target_user_id = target_user_id
        self.executed = []

    async def fetchrow(self, query, *args):
        q = " ".join(query.split())
        if "FROM ai_collections" in q:
            return {"id": "coll-id", "owner_id": self.owner_id,
                    "member_role": self.member_role}
        if "FROM users" in q:
            return {"id": self.target_user_id} if self.target_user_id else None
        raise AssertionError(f"unexpected fetchrow: {q}")

    async def fetch(self, query, *args):
        return [{"username": "reader1", "role": "reader", "granted_by": None,
                 "granted_at": None}]

    async def execute(self, query, *args):
        self.executed.append((" ".join(query.split()), args))
        if "DELETE FROM ai_collection_members" in query:
            return "DELETE 1"
        return "INSERT 0 1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _install_members(monkeypatch, owner_id, member_role=None, target_user_id="target-id"):
    conn = _MembersConn(owner_id, member_role, target_user_id)
    monkeypatch.setattr(ai_vectors, "get_db_pool", lambda: _aval(_Pool(conn)))
    return conn


def test_owner_can_grant_and_the_grant_reaches_the_insert(monkeypatch):
    conn = _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID))
    out = _run(ai_vectors.add_member(
        "private", ai_vectors.MemberGrant(username="newperson", role="reader"), OWNER))
    assert out["success"] is True
    inserts = [q for q, _a in conn.executed if "INSERT INTO ai_collection_members" in q]
    assert inserts, "add_member did not write a membership row"


def test_a_knowledge_write_holder_cannot_grant_themselves_someone_elses_collection(monkeypatch):
    """The property the plan calls out by name: holding knowledge:write is not
    the same as holding write access to THIS collection. OTHER owns nothing here
    and has no membership row — self-granting access to OWNER's private
    collection must 403 before any INSERT runs."""
    conn = _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role=None)
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors.add_member(
            "private", ai_vectors.MemberGrant(username=OTHER_ID, role="editor"), OTHER))
    assert exc.value.status_code == 403
    assert conn.executed == [], "a refused grant must not reach the database at all"


def test_a_reader_cannot_grant_membership_either(monkeypatch):
    """Read access is not write access: a reader grant must not let its holder
    extend membership to anyone else."""
    conn = _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role="reader")
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors.add_member(
            "private", ai_vectors.MemberGrant(username="x", role="editor"), OTHER))
    assert exc.value.status_code == 403
    assert conn.executed == []


def test_an_invalid_role_is_rejected_before_touching_the_database(monkeypatch):
    conn = _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID))
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors.add_member(
            "private", ai_vectors.MemberGrant(username="x", role="admin"), OWNER))
    assert exc.value.status_code == 400
    assert conn.executed == []


def test_granting_an_unknown_username_is_a_404(monkeypatch):
    _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID), target_user_id=None)
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors.add_member(
            "private", ai_vectors.MemberGrant(username="ghost", role="reader"), OWNER))
    assert exc.value.status_code == 404


def test_owner_can_revoke_a_member(monkeypatch):
    conn = _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID))
    out = _run(ai_vectors.remove_member("private", "reader1", OWNER))
    assert out["success"] is True
    deletes = [q for q, _a in conn.executed if "DELETE FROM ai_collection_members" in q]
    assert deletes


def test_listing_members_is_also_gated_on_write_not_just_the_permission(monkeypatch):
    """GET is included in the same may_write gate as POST/DELETE: who has access
    to a private collection is itself something only someone who may manage that
    collection should see."""
    _install_members(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role=None)
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors.list_members("private", OTHER))
    assert exc.value.status_code == 403
