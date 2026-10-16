"""Grant or revoke one user's access to a catalog without rewriting the whole list.

`PUT /catalogs/{name}/grants` replaces every grant, so a page that wants to add one
agent would have to read, edit and write the list back — and lose a concurrent change.
These two routes touch only the one row, and either is safe to repeat.
"""
import pytest

from app import catalog_access
from app.api import catalog_admin as ca
from tests.test_catalog_admin import (  # noqa: F401  (fixtures and fakes shared on purpose)
    ADMIN, ALICE_ID, BOT_ID, _Conn as _BaseConn, _Pool as _BasePool, _client, db, people)


class _Conn(_BaseConn):
    """The shared fake plus the two single-row statements these routes use. The insert
    honours ON CONFLICT DO NOTHING, which is what makes a repeat a no-op."""

    async def execute(self, sql, *args):
        if "INSERT INTO catalog_grants" in sql and "ON CONFLICT" in sql:
            row = (args[0], args[1], args[2])
            if row not in self.db.grants:
                self.db.grants.append(row)
            return "INSERT 0 1"
        if "DELETE FROM catalog_grants" in sql and "principal" in sql:
            self.db.grants = [g for g in self.db.grants
                              if g != (args[0], "user", args[1])]
            return "DELETE 1"
        return await super().execute(sql, *args)


@pytest.fixture(autouse=True)
def _pool(people, monkeypatch):
    class Pool(_BasePool):
        def acquire(self):
            return _Conn(self.db)

    async def _p():
        return Pool(people)
    monkeypatch.setattr(ca, "_pool", _p)


URL = f"/api/catalogs/lake/grants/user/{BOT_ID}"


def test_user_grant_idempotent(people):
    for _ in range(2):
        r = _client().put(URL)
        assert r.status_code == 200, r.text
    assert people.grants == [("lake", "user", BOT_ID)]
    body = r.json()
    assert body["catalog"] == "lake" and body["restricted"] is True
    assert [(g["kind"], g["principal"]) for g in body["grants"]] == [("user", BOT_ID)]

    for _ in range(2):
        r = _client().delete(URL)
        assert r.status_code == 200, r.text
    assert people.grants == []
    assert r.json() == {"catalog": "lake", "restricted": False, "grants": []}


def test_user_grant_leaves_other_grants_alone(people):
    people.grants.append(("lake", "role", "auditor"))
    _client().put(URL)
    _client().delete(URL)
    assert people.grants == [("lake", "role", "auditor")]


def test_user_grant_normalises_the_principal(people):
    assert _client().put(f"/api/catalogs/lake/grants/user/{BOT_ID.upper()}").status_code == 200
    assert people.grants == [("lake", "user", BOT_ID)]


def test_user_grant_audits_the_difference(people):
    _client().put(URL)
    assert people.audit[-1]["event"] == "catalog_grants_changed"
    assert people.audit[-1]["details"]["added"] == [f"user:{BOT_ID}"]
    _client().delete(URL)
    assert people.audit[-1]["details"]["removed"] == [f"user:{BOT_ID}"]


def test_user_grant_invalidates_cache(people):
    for call in (_client().put, _client().delete):
        catalog_access.set_grants({})
        assert call(URL).status_code == 200
        assert catalog_access._state["grants"] is None


def test_user_grant_unknown_user_400(people):
    ghost = "55555555-5555-5555-5555-555555555555"
    r = _client().put(f"/api/catalogs/lake/grants/user/{ghost}")
    assert r.status_code == 400 and f"No user with id {ghost}" in r.json()["detail"]
    assert people.grants == []
    assert _client().put("/api/catalogs/lake/grants/user/not-a-uuid").status_code == 400


def test_user_grant_unknown_catalog_404(people):
    assert _client().put(f"/api/catalogs/nope/grants/user/{BOT_ID}").status_code == 404
    assert _client().delete(f"/api/catalogs/nope/grants/user/{BOT_ID}").status_code == 404


@pytest.mark.parametrize("principal", [
    {"id": ADMIN["id"], "username": "bot", "role": "admin", "auth_method": "service"},
    {"id": ADMIN["id"], "username": "v", "role": "viewer"},
])
def test_user_grant_non_admin_403(people, principal):
    c = _client(principal)
    assert c.put(URL).status_code == 403
    assert c.delete(URL).status_code == 403
    assert people.grants == []
