"""Every path that touches a connector or a transform asks the same question.

Design: docs/superpowers/plans/2026-08-31-governance-and-audit-boundary.md (D2)

`app/resource_access.py` is the decision and `app/api/source_access.py` is the gate.
This file is the wiring proof, and it is A3's method applied to sources: a model
enforced on fourteen of seventeen routes is a suggestion, so the header test drives
*every* route that names an existing connector or transform through the same stranger
and asserts none of them lets them in. A new route that reaches a source without being
added to PATHS is the failure mode this guards against.

Handlers are called directly as coroutines rather than through the HTTP client, the
same pattern tests/test_knowledge_membership_enforcement.py and
tests/test_security_boundaries.py use: it proves what the handler itself enforces,
independent of whichever permission dependency happens to sit in front of it.

The other half of D2 is compatibility, and it gets equal weight below. Every connector
and transform that exists on the day this ships has `owner_id IS NULL`, and the people
who manage them hold `connector:write` / `pipeline:write` and are not admins. If this
change locks them out of their own deployment it has replaced one defect with a worse
one, so the unowned cases are tested as carefully as the private ones.
"""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app.api import connectors, source_access, transforms


OWNER_ID = "00000000-0000-0000-0000-0000000000b1"
OTHER_ID = "00000000-0000-0000-0000-0000000000b2"
RESOURCE_ID = "00000000-0000-0000-0000-0000000000c1"

ADMIN = {"id": "00000000-0000-0000-0000-0000000000ad", "role": "admin"}
OWNER = {"id": OWNER_ID, "role": "data_engineer"}
STRANGER = {"id": OTHER_ID, "role": "data_engineer"}   # holds connector:write
VIEWER = {"id": OTHER_ID, "role": "viewer"}            # holds neither write permission

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


async def _aval(value):
    return value


class _GateConn:
    """Answers the one query `resolve()` runs, for a single fixed resource.

    Every refused path raises out of the gate before it reaches a second statement —
    which is the property under test — so nothing past `fetchrow` needs to be real.
    """

    def __init__(self, owner_id, member_role=None, found=True):
        self.row = None if not found else {
            "id": uuid.UUID(RESOURCE_ID), "owner_id": owner_id, "member_role": member_role,
        }
        self.queries = []

    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        return self.row

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        return "DELETE 0"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _install(monkeypatch, owner_id, member_role=None, found=True):
    conn = _GateConn(owner_id, member_role, found)
    monkeypatch.setattr(connectors, "get_db_pool", lambda: _aval(_Pool(conn)))
    return conn


class _FakeDb:
    """A SQLAlchemy session that would fail loudly if a refused transform route ever
    got past the gate and tried to use it."""

    def query(self, *a, **k):
        raise AssertionError("the gate let a stranger reach the database")


# ── every path, one stranger, one loop ──────────────────────────────────────

def _connector_paths(cid, user):
    """(label, coroutine) for every connectors.py route that names an existing
    connection. New routes belong here — that is the point of the loop below."""
    return [
        ("draft discard", connectors.discard_draft_connection(cid, user)),
        ("get", connectors.get_connection(cid, user)),
        ("config", connectors.get_connection_config(cid, user)),
        ("update", connectors.update_connection(
            cid, connectors.ConnectionUpdateRequest(name="x"), user)),
        ("set schedule", connectors.set_schedule(
            cid, connectors.ScheduleRequest(schedule="0 * * * *"), user)),
        ("get schedule", connectors.get_schedule(cid, user)),
        ("delete", connectors.delete_connection(cid, user)),
        ("tables", connectors.list_tables(cid, user)),
        ("table enabled", connectors.set_table_enabled(cid, "t", {"enabled": False}, user)),
        ("table partition", connectors.set_table_partition(cid, "t", {"partition_spec": []}, user)),
        ("sync mode", connectors.set_connection_sync_mode(cid, {"sync_mode": "full"}, user)),
        ("schema", connectors.get_table_schema(cid, "t", user)),
        ("sync stream", connectors.sync_stream(cid, "full", user)),
        ("sync", connectors.trigger_sync(cid, connectors.SyncRequest(), user)),
        ("status", connectors.get_sync_status(cid, user)),
        ("history", connectors.get_sync_history(cid, 20, user)),
        ("quality", connectors.get_quality_checks(cid, 20, user)),
        ("members list", source_access.list_connector_members(cid, user)),
        ("members add", source_access.add_connector_member(
            cid, source_access.MemberGrant(username="someone", role="reader"), user)),
        ("members remove", source_access.remove_connector_member(cid, "someone", user)),
    ]


def _transform_paths(tid, user):
    return [
        ("get", transforms.get_transform(tid, _FakeDb(), user)),
        ("update", transforms.update_transform(
            tid, transforms.TransformUpdateRequest(description="x"), _FakeDb(), user)),
        ("trigger", transforms.trigger_transform(tid, _FakeDb(), user)),
        ("delete", transforms.delete_transform(tid, _FakeDb(), user)),
        ("members list", source_access.list_transform_members(tid, user)),
        ("members add", source_access.add_transform_member(
            tid, source_access.MemberGrant(username="someone", role="reader"), user)),
        ("members remove", source_access.remove_transform_member(tid, "someone", user)),
    ]


def _refusals(paths):
    failures = []
    for label, coro in paths:
        try:
            _run(coro)
            failures.append(f"{label}: did not raise")
        except HTTPException as exc:
            if exc.status_code != 403:
                failures.append(f"{label}: raised {exc.status_code}, not 403")
        except AssertionError as exc:
            failures.append(f"{label}: {exc}")
    return failures


def test_a_stranger_cannot_reach_someone_elses_connector_through_any_path(monkeypatch):
    """STRANGER is not the owner, not an admin, holds no grant — and *does* hold
    connector:write, which is exactly the hole D2 closes: before this, that
    permission alone reached every connector in the deployment."""
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role=None)
    failures = _refusals(_connector_paths(RESOURCE_ID, STRANGER))
    assert not failures, "connector paths that let a stranger through:\n  " + "\n  ".join(failures)


def test_a_stranger_cannot_reach_someone_elses_transform_through_any_path(monkeypatch):
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role=None)
    failures = _refusals(_transform_paths(RESOURCE_ID, STRANGER))
    assert not failures, "transform paths that let a stranger through:\n  " + "\n  ".join(failures)


def test_a_reader_grant_is_not_a_write_grant(monkeypatch):
    """The write half specifically: a reader may look at the source and may not
    sync it, edit it, delete it, or hand access to anyone else."""
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role="reader")
    write_only = {
        "draft discard", "update", "set schedule", "delete", "table enabled",
        "table partition", "sync mode", "sync stream", "sync",
        "members list", "members add", "members remove",
    }
    paths = [(label, coro) for label, coro in _connector_paths(RESOURCE_ID, STRANGER)
             if label in write_only]
    assert len(paths) == len(write_only), "a write path disappeared from the list"
    failures = _refusals(paths)
    assert not failures, "write paths a reader got through:\n  " + "\n  ".join(failures)


def test_a_missing_connector_is_404_not_403(monkeypatch):
    """"Not yours" and "does not exist" stay different answers, as they are on the
    collection routes."""
    _install(monkeypatch, owner_id=None, found=False)
    with pytest.raises(HTTPException) as exc:
        _run(connectors.get_connection(RESOURCE_ID, STRANGER))
    assert exc.value.status_code == 404


def test_a_malformed_id_is_400_and_never_reaches_the_query(monkeypatch):
    conn = _install(monkeypatch, owner_id=None)
    with pytest.raises(HTTPException) as exc:
        _run(connectors.get_connection("not-a-uuid", STRANGER))
    assert exc.value.status_code == 400
    assert conn.queries == []


# ── compatibility: every source that exists today is unowned ────────────────

def test_the_owner_passes_the_gate(monkeypatch):
    conn = _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID))
    row = _run(source_access.require_access(
        source_access.CONNECTOR, RESOURCE_ID, OWNER, write=True))
    assert str(row["id"]) == RESOURCE_ID
    assert conn.queries, "the gate did not query for the resource"


def test_an_editor_grant_passes_the_write_gate(monkeypatch):
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID), member_role="editor")
    assert _run(source_access.require_access(
        source_access.CONNECTOR, RESOURCE_ID, STRANGER, write=True))


def test_an_admin_passes_the_gate_on_anything(monkeypatch):
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID))
    assert _run(source_access.require_access(
        source_access.CONNECTOR, RESOURCE_ID, ADMIN, write=True))


@pytest.mark.parametrize("write", (False, True))
def test_an_unowned_connector_still_works_for_a_data_engineer(monkeypatch, write):
    """The compatibility case, and the one most likely to break a live deployment:
    owner_id IS NULL is the state of every connector that exists when 0006 runs, and
    the people who manage them are data engineers, not admins."""
    _install(monkeypatch, owner_id=None)
    assert _run(source_access.require_access(
        source_access.CONNECTOR, RESOURCE_ID, STRANGER, write=write))


def test_an_unowned_connector_is_readable_but_not_writable_by_a_viewer(monkeypatch):
    _install(monkeypatch, owner_id=None)
    assert _run(source_access.require_access(source_access.CONNECTOR, RESOURCE_ID, VIEWER))
    with pytest.raises(HTTPException) as exc:
        _run(source_access.require_access(
            source_access.CONNECTOR, RESOURCE_ID, VIEWER, write=True))
    assert exc.value.status_code == 403


# ── listing: the same rule, expressed in SQL ────────────────────────────────

def test_the_listing_predicate_is_the_read_rule_and_admins_get_none():
    clause, args = source_access.visible_clause(source_access.CONNECTOR, ADMIN, "c", 1)
    assert clause == "" and args == []

    clause, args = source_access.visible_clause(source_access.CONNECTOR, STRANGER, "c", 1)
    assert "c.owner_id = $1" in clause              # mine
    assert "c.owner_id IS NULL" in clause           # unowned: everyone's, as today
    assert "connector_members" in clause            # or granted to me
    assert "EXISTS" in clause                       # once per source, not once per grant
    assert args == [uuid.UUID(OTHER_ID)]


def test_the_listing_query_carries_the_predicate_and_its_argument(monkeypatch):
    """Not just that the fragment is right, but that list_connections actually
    interpolates it and passes the argument — a filter built and then dropped is the
    kind of thing that only shows up in production."""
    captured = {}

    class _ListConn:
        async def fetch(self, query, *args):
            captured["query"], captured["args"] = query, args
            return []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(connectors, "get_db_pool", lambda: _aval(_Pool(_ListConn())))
    assert _run(connectors.list_connections(STRANGER)) == []
    assert "WHERE" in captured["query"] and "connector_members" in captured["query"]
    assert captured["args"] == (uuid.UUID(OTHER_ID),)

    _run(connectors.list_connections(ADMIN))
    assert "WHERE" not in captured["query"]
    assert captured["args"] == ()


# ── creation: what makes any of this mean anything ──────────────────────────

def test_creating_a_connector_records_the_caller_as_its_owner(monkeypatch):
    """Without this the feature is inert: every new connector would be unowned, and
    unowned means everyone's."""
    captured = {}

    class _InsertConn:
        async def execute(self, query, *args):
            captured["query"], captured["args"] = query, args
            return "INSERT 0 1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(connectors, "get_db_pool", lambda: _aval(_Pool(_InsertConn())))

    class _OkConnector:
        async def test_connection(self):
            return type("R", (), {"success": True})()

    monkeypatch.setattr(connectors, "_create_connector", lambda t, c: _OkConnector())
    monkeypatch.setattr(connectors.vault, "encrypt_credentials", lambda cfg: "enc")

    request = connectors.ConnectionCreateRequest(
        name="mine", connector_type=connectors.ConnectorType.S3, config={"bucket": "b"})
    _run(connectors.create_connection(request, OWNER))

    assert "owner_id" in captured["query"]
    assert uuid.UUID(OWNER_ID) in captured["args"]


def test_overwriting_someone_elses_transform_by_name_is_refused(monkeypatch):
    """create(overwrite=true) resolves to an existing row, and writing to that row is
    a write to a transform someone else owns — the one place where "create" can
    destroy another person's work."""
    _install(monkeypatch, owner_id=uuid.UUID(OWNER_ID))

    existing = type("Row", (), {"id": uuid.UUID(RESOURCE_ID), "name": "theirs", "dag_id": None})()

    class _Query:
        def __init__(self, result):
            self.result = result

        def filter(self, *a, **k):
            return self

        def first(self):
            return self.result

    class _Db:
        def __init__(self):
            self.calls = 0

        def query(self, *a, **k):
            self.calls += 1
            # First query looks for a dag_id clash (none), second for the name.
            return _Query(None if self.calls == 1 else existing)

    monkeypatch.setattr(transforms, "_validate_transform_sql", lambda sql: None)
    monkeypatch.setattr(transforms, "_explain_check", lambda sql: _aval(None))
    monkeypatch.setattr(transforms, "_deploy_dag",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("deployed a DAG for a refused overwrite")))

    req = transforms.TransformCreateRequest(
        name="theirs", source_namespace="raw", target_namespace="refined",
        target_table="t", sql="SELECT 1", overwrite=True)
    with pytest.raises(HTTPException) as exc:
        _run(transforms.create_transform(req, _Db(), STRANGER))
    assert exc.value.status_code == 403
