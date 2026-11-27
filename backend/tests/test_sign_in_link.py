"""A one-time sign-in link for a tester (POST /auth/users/{id}/sign-in-link).

The link is a password_reset_tokens row: single use, only its hash stored, older
unused links voided, opening it lets the person choose a password. It never signs
anyone in by itself, so nothing reusable travels in a chat message or a URL.
"""
import asyncio
import hashlib
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

import app.api.auth as auth

UID = uuid.uuid4()


class _Conn:
    def __init__(self, row):
        self.row, self.calls = row, []

    async def fetchrow(self, sql, *a):
        return self.row

    async def execute(self, sql, *a):
        self.calls.append((sql, a))

    def transaction(self):
        conn = self

        class _T:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *e):
                return False
        return _T()


def _setup(monkeypatch, row):
    conn = _Conn(row)

    class _Acq:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *e):
            return False

    async def _pool():
        return SimpleNamespace(acquire=lambda: _Acq())
    events = []

    async def _event(kind, **kw):
        events.append((kind, kw))
    monkeypatch.setattr(auth, "_get_pool", _pool)
    monkeypatch.setattr(auth, "record_auth_event", _event)
    monkeypatch.setenv("APP_BASE_URL", "https://dp.example")
    return conn, events


def _person(**kw):
    return {"id": UID, "username": "tester1", "email": "t@example.com",
            "is_active": True, "auth_method": "local", **kw}


def _call(body=None):
    req = SimpleNamespace(base_url="http://x/", client=None, headers={})
    return asyncio.run(auth.create_sign_in_link(str(UID), req, body, admin={"username": "admin"}, _human={}))


def test_the_link_sets_a_password_once_and_stores_only_a_hash(monkeypatch):
    conn, events = _setup(monkeypatch, _person())
    out = _call()
    u = urlparse(out["url"])
    assert (u.scheme, u.netloc, u.path) == ("https", "dp.example", "/reset")
    token = parse_qs(u.query)["token"][0]
    assert parse_qs(u.query)["invite"] == ["1"]
    voided, inserted = conn.calls
    assert "used_at = NOW()" in voided[0]                      # older links voided
    assert inserted[1][1] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(conn.calls)                      # never stored raw
    assert out["hours"] == 72
    assert events[0][0] == "password_reset_request"
    assert events[0][1]["details"]["kind"] == "sign_in_link"


def test_hours_are_clamped_to_a_week():
    assert auth.sign_in_link_hours(None) == 72
    assert auth.sign_in_link_hours(1000) == 168
    assert auth.sign_in_link_hours(0) == 1
    assert auth.sign_in_link_hours("x") == 72


@pytest.mark.parametrize("row,msg", [
    (_person(auth_method="service"), "keys"),
    (_person(is_active=False), "Reactivate"),
    (_person(auth_method="ldap"), "ldap"),
])
def test_refused_where_a_password_link_would_not_work(monkeypatch, row, msg):
    _setup(monkeypatch, row)
    with pytest.raises(HTTPException) as e:
        _call()
    assert e.value.status_code == 400 and msg in e.value.detail


def test_unknown_person_is_404(monkeypatch):
    _setup(monkeypatch, None)
    with pytest.raises(HTTPException) as e:
        _call()
    assert e.value.status_code == 404
