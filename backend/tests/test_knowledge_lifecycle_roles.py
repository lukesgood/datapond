"""B1: ingesting a source and scheduling it are `knowledge:write`, not admin.

`ai_engineer` is the product's own stated target user. It holds `knowledge:write`
and `ai:generate` — it can create a collection and paste text into it, but until
this change it could not point that collection at an S3 prefix or a table
(`ingest-source`), nor schedule the collection to refresh (`schedule`), because
both routes were gated on `require_admin_or_internal` / `require_admin`.

This is a route-level (HTTP, via TestClient) proof rather than a direct coroutine
call, unlike tests/test_knowledge_membership_enforcement.py — that file explicitly
bypasses FastAPI's dependency machinery to test what `_collection_id` enforces
independent of whatever route dependency sits in front of it. Here the route
dependency IS the thing under test: whether the caller's role/permission gate
lets an `ai_engineer` reach the handler at all, and whether the scoped internal
automation principal still can too — this route sits on
`_INTERNAL_AUTOMATION_ROUTES` for a trusted caller using X-Internal-Key instead
of a user session, and a regression here would silently break that callback.
"""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import ai_vectors, auth

# Captured before any monkeypatch touches `auth.require_user`: `_app`'s
# `dependency_overrides` must key on the same function object FastAPI bound into
# `schedule_ingest`'s dependency graph at import time, not whatever the module
# attribute currently points to.
_REAL_REQUIRE_USER = auth.require_user

OWNER_ID = "00000000-0000-0000-0000-0000000000b1"
STRANGER_ID = "00000000-0000-0000-0000-0000000000b2"


class _CollConn:
    """Answers the join query `_collection_id` runs, for one fixed collection
    owned by `owner_id`. Mirrors tests/test_knowledge_membership_enforcement.py's
    fixture of the same shape."""

    def __init__(self, owner_id):
        self.row = {"id": "coll-id", "owner_id": owner_id, "member_role": None}

    async def fetchrow(self, query, *args):
        return self.row

    async def execute(self, query, *args):
        return "DELETE 0"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


async def _aval(value):
    return value


def _app(user=None):
    """`schedule_ingest` reaches `require_user` through a real `Depends(require_user)`
    node (in `require_permission`'s own guard, and again as its own handler
    parameter) — `dependency_overrides` intercepts that. `ingest-source`'s new
    `require_permission_or_internal` guard cannot use `Depends(require_user)` for
    its own resolution: doing so would resolve (and reject) it before the internal
    check ever runs, which is exactly the regression the plan warns about. It calls
    `require_user(request, credentials)` as a plain function instead, so
    `dependency_overrides` — which only intercepts nodes declared in a Depends
    graph — cannot reach it; `_sign_in_as` below patches the module attribute for
    that path.
    """
    app = FastAPI()
    app.include_router(ai_vectors.router, prefix="/api")
    if user is not None:
        async def _override():
            return user
        app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def _sign_in_as(monkeypatch, user):
    async def _fake_require_user(request, credentials=None):
        return user
    monkeypatch.setattr(auth, "require_user", _fake_require_user)


@pytest.fixture(autouse=True)
def _stub_source_read(monkeypatch):
    # ingest-source's actual S3/Iceberg read and embedding are exercised by
    # tests/test_rag_ingest.py; here only the authorization gate is under test.
    monkeypatch.setattr(
        ai_vectors, "_refresh_from_source",
        lambda pool, coll_id, req: _aval({"documents": 0, "chunks": 0}),
    )


def _install_collection(monkeypatch, owner_id):
    conn = _CollConn(owner_id)
    monkeypatch.setattr(ai_vectors, "get_db_pool", lambda: _aval(_Pool(conn)))
    return conn


SOURCE_BODY = {"type": "s3", "bucket": "docs"}


def test_ai_engineer_owner_can_ingest_source_and_schedule(monkeypatch):
    _install_collection(monkeypatch, uuid.UUID(OWNER_ID))
    user = {"id": OWNER_ID, "username": "eng", "role": "ai_engineer"}
    _sign_in_as(monkeypatch, user)
    client = TestClient(_app(user))

    ingest = client.post("/api/ai/collections/mine/ingest-source", json=SOURCE_BODY)
    assert ingest.status_code == 200, ingest.text

    schedule = client.post(
        "/api/ai/collections/mine/schedule", json={"source": SOURCE_BODY})
    assert schedule.status_code == 200, schedule.text


def test_viewer_is_refused_before_the_collection_is_ever_touched(monkeypatch):
    """A viewer holds no knowledge:write — refused by the role gate itself, not by
    _collection_id, even though this viewer happens to own the collection."""
    _install_collection(monkeypatch, uuid.UUID(OWNER_ID))
    user = {"id": OWNER_ID, "username": "v", "role": "viewer"}
    _sign_in_as(monkeypatch, user)
    client = TestClient(_app(user))

    ingest = client.post("/api/ai/collections/mine/ingest-source", json=SOURCE_BODY)
    assert ingest.status_code == 403
    assert "knowledge:write" in ingest.json()["detail"]

    schedule = client.post(
        "/api/ai/collections/mine/schedule", json={"source": SOURCE_BODY})
    assert schedule.status_code == 403
    assert "knowledge:write" in schedule.json()["detail"]


def test_knowledge_write_holder_who_is_a_stranger_is_refused_by_the_collection(monkeypatch):
    """Holding knowledge:write is necessary but not sufficient: a caller who isn't
    the owner and isn't a member is refused by _collection_id's ownership check,
    not by the role gate — the 403 here must not name the permission."""
    _install_collection(monkeypatch, uuid.UUID(OWNER_ID))
    stranger = {"id": STRANGER_ID, "username": "s", "role": "ai_engineer"}
    _sign_in_as(monkeypatch, stranger)
    client = TestClient(_app(stranger))

    ingest = client.post("/api/ai/collections/mine/ingest-source", json=SOURCE_BODY)
    assert ingest.status_code == 403
    assert "knowledge:write" not in ingest.json()["detail"]
    assert "Not authorized for collection" in ingest.json()["detail"]

    schedule = client.post(
        "/api/ai/collections/mine/schedule", json={"source": SOURCE_BODY})
    assert schedule.status_code == 403
    assert "knowledge:write" not in schedule.json()["detail"]
    assert "Not authorized for collection" in schedule.json()["detail"]


def test_internal_automation_principal_still_reaches_ingest_source(monkeypatch):
    """The allowlisted internal-automation callback (X-Internal-Key, no user
    session at all) must keep reaching ingest-source after the role gate replaces
    require_admin_or_internal — this is the regression the defect warning in the
    plan calls out explicitly."""
    monkeypatch.setenv("INTERNAL_API_KEY", "scheduler-secret")
    _install_collection(monkeypatch, uuid.UUID(OWNER_ID))
    client = TestClient(_app())  # no sign-in: internal automation bypasses require_user entirely

    ingest = client.post(
        "/api/ai/collections/mine/ingest-source",
        json=SOURCE_BODY,
        headers={"X-Internal-Key": "scheduler-secret"},
    )
    assert ingest.status_code == 200, ingest.text


def test_schedule_has_no_internal_route_and_is_not_reachable_with_the_key(monkeypatch):
    """schedule is explicitly not on the internal-automation allowlist (only
    ingest-source and connector sync are) — the key must not open it."""
    monkeypatch.setenv("INTERNAL_API_KEY", "scheduler-secret")
    _install_collection(monkeypatch, uuid.UUID(OWNER_ID))
    client = TestClient(_app())

    schedule = client.post(
        "/api/ai/collections/mine/schedule",
        json={"source": SOURCE_BODY},
        headers={"X-Internal-Key": "scheduler-secret"},
    )
    assert schedule.status_code == 401
