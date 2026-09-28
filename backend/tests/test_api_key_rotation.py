"""Rotating a service-account key without an outage.

Keys could be issued and revoked, nothing else. Replacing one meant revoking it —
which breaks every agent holding it at that moment — or issuing a second by hand and
remembering to revoke the first. Rotation issues the successor with the same name
and scopes and gives the old key a grace period, so the agent's config can be
updated before the old key stops working.
"""
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, service_account_routes as sar

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
KEY_ID = "33333333-3333-3333-3333-333333333333"
NEW_ID = "44444444-4444-4444-4444-444444444444"
ACCT = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)


def _old_key(**over):
    row = {"id": KEY_ID, "user_id": ACCT, "name": "ci-agent", "key_hash": "old-digest",
           "scopes": ["ai:generate"], "expires_at": None, "created_at": NOW - timedelta(days=10),
           "role": "ai_engineer", "now": NOW}
    row.update(over)
    return row


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self, old):
        self.old, self.executed, self.inserted = old, [], None

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        if "FROM api_keys" in sql:
            return self.old
        if "INSERT INTO api_keys" in sql:
            self.inserted = args
            return {"id": NEW_ID}
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _client(monkeypatch, conn):
    async def _pool():
        return _Pool(conn)
    events = []

    async def _event(kind, **kw):
        events.append((kind, kw))
    monkeypatch.setattr(sar, "_get_pool", _pool)
    monkeypatch.setattr(sar, "record_auth_event", _event)
    app = FastAPI()
    app.include_router(sar.router, prefix="/api")

    async def _admin():
        return ADMIN
    app.dependency_overrides[auth.require_admin] = _admin
    return TestClient(app), events


def test_rotation_issues_a_successor_with_the_same_name_and_scopes(monkeypatch):
    conn = _Conn(_old_key())
    client, events = _client(monkeypatch, conn)
    r = client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"].startswith("dp_sk_")
    assert body["replaces"] == KEY_ID
    user_id, name, _prefix, digest, scopes, expires = conn.inserted
    assert (user_id, name, scopes) == (ACCT, "ci-agent", ["ai:generate"])
    assert digest != "old-digest" and expires is None
    assert events[0][0] == "api_key_rotated"
    assert events[0][1]["details"]["new_key_id"] == NEW_ID


def test_the_old_key_keeps_working_for_the_grace_period(monkeypatch):
    conn = _Conn(_old_key())
    client, _ = _client(monkeypatch, conn)
    r = client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={"grace_hours": 6})
    assert r.status_code == 201
    sql, args = conn.executed[-1]
    assert "expires_at" in sql and "revoked" not in sql
    assert args[1] == NOW + timedelta(hours=6)
    assert r.json()["old_key_expires_at"].startswith("2026-09-28T09:00")


def test_grace_never_extends_a_key_that_expires_sooner(monkeypatch):
    soon = NOW + timedelta(hours=1)
    conn = _Conn(_old_key(expires_at=soon, created_at=NOW - timedelta(days=29)))
    client, _ = _client(monkeypatch, conn)
    client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={"grace_hours": 24})
    assert conn.executed[-1][1][1] == soon


def test_zero_grace_revokes_the_old_key_at_once(monkeypatch):
    conn = _Conn(_old_key())
    client, _ = _client(monkeypatch, conn)
    r = client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={"grace_hours": 0})
    assert r.status_code == 201
    assert "revoked" in conn.executed[-1][0]


def test_a_key_with_a_lifetime_passes_that_lifetime_on(monkeypatch):
    created = NOW - timedelta(days=80)
    conn = _Conn(_old_key(created_at=created, expires_at=created + timedelta(days=90)))
    client, _ = _client(monkeypatch, conn)
    client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={})
    assert conn.inserted[5] == NOW + timedelta(days=90)


def test_a_revoked_or_missing_key_cannot_be_rotated(monkeypatch):
    client, _ = _client(monkeypatch, _Conn(None))
    r = client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={})
    assert r.status_code == 404


def test_the_old_keys_cached_identity_is_dropped(monkeypatch):
    auth._KEY_CACHE["old-digest"] = ({"id": ACCT}, 0.0)
    client, _ = _client(monkeypatch, _Conn(_old_key()))
    client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={"grace_hours": 0})
    assert "old-digest" not in auth._KEY_CACHE


def test_grace_is_bounded(monkeypatch):
    client, _ = _client(monkeypatch, _Conn(_old_key()))
    r = client.post(f"/api/service-accounts/keys/{KEY_ID}/rotate", json={"grace_hours": 24 * 30})
    assert r.status_code == 422
