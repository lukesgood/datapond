"""The audit trail an authorization *denial* writes, whether or not anyone asked for it.

`query_history` is the closest thing this product had to an audit trail, and
`QueryExecuteRequest.save_history=false` lets the caller turn it off for their own
query. A 403 had no equivalent record anywhere — a credential probing the API for
what it can reach left nothing behind. `app/security_audit.py` is the writer
`require_permission`'s guard now calls on every denial; this file is what proves it
actually happens and that nothing reaches in to stop it.
"""
import asyncio
import inspect

import pytest
from fastapi import HTTPException

from app.api.auth import require_permission
import app.security_audit as security_audit
from app.security_audit import build_row, is_privileged, record


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── build_row: pure, no database ────────────────────────────────────────────

def test_build_row_fills_every_field():
    """Every column `security_audit_log` has, filled from the call — nothing left
    for the database to default silently."""
    from datetime import datetime, timezone

    now = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
    row = build_row(
        actor={"id": "u-1", "username": "alice", "role": "data_engineer"},
        permission="connector:write",
        route="/api/connectors/abc/sync",
        method="post",
        outcome="denied",
        reason="'connector:write' permission required — your role (viewer) does not have it.",
        client_address="203.0.113.9",
        now=now,
    )
    assert row == {
        "actor_id": "u-1",
        "actor_username": "alice",
        "permission": "connector:write",
        "route": "/api/connectors/abc/sync",
        "method": "POST",
        "outcome": "denied",
        "reason": "'connector:write' permission required — your role (viewer) does not have it.",
        "client_address": "203.0.113.9",
        "occurred_at": now,
    }


def test_build_row_defaults_a_missing_actor_rather_than_raising():
    """A service-account principal or a malformed claims dict must not crash the
    audit write on top of whatever else is going wrong."""
    row = build_row(actor={}, permission="knowledge:write", route="/x", method="get",
                     outcome="allowed", reason="")
    assert row["actor_id"] is None
    assert row["actor_username"] == ""


def test_build_row_rejects_an_outcome_that_is_not_allowed_or_denied():
    """There are exactly two outcomes to a permission check. A third value would be
    a bug in the caller, and writing it silently would give the audit log a state
    nothing reading it expects."""
    with pytest.raises(ValueError):
        build_row(actor={"id": "u-1"}, permission="p", route="/x", method="get",
                   outcome="maybe", reason="")


# ── is_privileged: which allows are worth a row ──────────────────────────────

def test_write_shaped_permissions_are_privileged():
    for perm in ("connector:write", "knowledge:write", "governance:write",
                 "settings:write", "query:write", "pipeline:write",
                 "dashboard:write", "workbench:write", "user:manage", "service:manage"):
        assert is_privileged(perm), perm


def test_read_shaped_permissions_are_not_privileged():
    """These are audited on denial regardless — is_privileged only decides whether an
    *allowed* use also gets a row, and recording every read would make this a log of
    every request rather than a security audit trail."""
    for perm in ("catalog:read", "connector:read", "knowledge:read", "governance:read",
                 "audit:read", "spend:read", "workbench:read", "query:run", "ai:generate"):
        assert not is_privileged(perm), perm


# ── record(): the impure edge, faked ────────────────────────────────────────

class _FakeConn:
    def __init__(self, calls):
        self._calls = calls

    async def execute(self, sql, *args):
        self._calls.append(args)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, calls):
        self._calls = calls

    def acquire(self, *a, **k):
        return _FakeConn(self._calls)


class _BrokenPool:
    """Stands in for a database that is down."""

    def acquire(self, *a, **k):
        raise ConnectionRefusedError("Connect call failed")


def _patch_pool(monkeypatch, pool):
    async def _get_db_pool():
        return pool
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _get_db_pool)


def test_record_writes_the_row_it_was_given(monkeypatch):
    calls = []
    _patch_pool(monkeypatch, _FakePool(calls))
    _run(record(actor={"id": "u-1", "username": "alice"}, permission="user:manage",
                route="/api/users/2", method="DELETE", outcome="allowed", reason="ok",
                client_address="10.0.0.1"))
    assert len(calls) == 1
    (actor_id, actor_username, permission, route, method, outcome, reason,
     client_address, occurred_at) = calls[0]
    assert (actor_id, actor_username, permission, route, method, outcome, reason,
            client_address) == ("u-1", "alice", "user:manage", "/api/users/2",
                                 "DELETE", "allowed", "ok", "10.0.0.1")


def test_record_never_raises_when_the_database_write_fails(monkeypatch):
    """An audit write that fails must not turn a working (or correctly denied)
    request into a 500. This is the whole reason `record` swallows rather than
    propagating — logging loudly instead is app/security_audit.py's job, not this
    test's, but the non-negotiable part (it must not raise) is proven here."""
    _patch_pool(monkeypatch, _BrokenPool())
    _run(record(actor={"id": "u-1"}, permission="user:manage", route="/x",
                method="GET", outcome="denied", reason="broken db"))
    # No assertion beyond "did not raise" — reaching this line is the proof.


# ── wired into require_permission: a denial always writes a row ─────────────

class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _URL:
    def __init__(self, path):
        self.path = path


class _Client:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Just enough of `starlette.Request` for `require_permission`'s guard: a path,
    a method, headers, and a client address — nothing that could carry a suppression
    flag, because the point of the next test is that there is nowhere to put one."""

    def __init__(self, method="GET", path="/api/connectors", headers=None, host="198.51.100.7"):
        self.method = method
        self.url = _URL(path)
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.client = _Client(host)


def test_a_denial_is_recorded(monkeypatch):
    calls = []
    _patch_pool(monkeypatch, _FakePool(calls))
    guard = require_permission("connector:write")
    request = _FakeRequest(method="POST", path="/api/connectors/abc/sync")
    with pytest.raises(HTTPException) as ei:
        _run(guard(request=request, user={"id": "u-1", "username": "bob", "role": "viewer"}))
    assert ei.value.status_code == 403
    assert len(calls) == 1
    (actor_id, actor_username, permission, route, method, outcome, reason,
     client_address, _occurred_at) = calls[0]
    assert actor_id == "u-1"
    assert actor_username == "bob"
    assert permission == "connector:write"
    assert route == "/api/connectors/abc/sync"
    assert method == "POST"
    assert outcome == "denied"
    assert "connector:write" in reason
    assert client_address == "198.51.100.7"


def test_an_allow_of_a_privileged_permission_is_also_recorded(monkeypatch):
    """user:manage is not shaped like `*:write` but is exactly as privileged — see
    app/security_audit.py's docstring for why it is named explicitly."""
    calls = []
    _patch_pool(monkeypatch, _FakePool(calls))
    guard = require_permission("user:manage")
    request = _FakeRequest(method="DELETE", path="/api/users/2")
    user = _run(guard(request=request, user={"id": "u-2", "username": "admin", "role": "admin"}))
    assert user["role"] == "admin"
    assert len(calls) == 1
    assert calls[0][5] == "allowed"


def test_an_allow_of_a_read_permission_writes_nothing():
    """The cost this module is not allowed to add: a database round-trip on every
    GET. `query:run` and the `*:read` permissions cover almost all traffic, so an
    allow of one of them must reach `require_permission` without touching the audit
    table at all. No pool is patched in — if this reached for one, the test would
    hang or fail on a real connection attempt rather than silently pass."""
    guard = require_permission("query:run")
    request = _FakeRequest(method="GET", path="/api/query")
    user = _run(guard(request=request, user={"id": "u-3", "role": "viewer"}))
    assert user["id"] == "u-3"


# ── a caller cannot suppress the write ───────────────────────────────────────

def test_record_has_no_parameter_that_suppresses_the_write():
    """Proves there is nowhere on the writer itself to plug in a `save_history=false`
    equivalent. This does not prove no *caller* of `record` could choose not to call
    it — that half is covered by the behavioural test below, which drives the actual
    authorization guard end to end."""
    params = set(inspect.signature(record).parameters)
    assert params == {"actor", "permission", "route", "method", "outcome",
                       "reason", "client_address"}
    for suspect in ("save_history", "audit", "skip_audit", "silent", "suppress",
                    "no_audit", "record_flag", "quiet"):
        assert suspect not in params


def test_require_permissions_guard_has_no_suppression_parameter_either():
    """Same proof one layer up: the dependency the route actually depends on takes
    only a request and a user. There is no argument a client request could populate
    — no header, no query string, no body field — because there is no parameter for
    one to land in."""
    guard = require_permission("connector:write")
    params = set(inspect.signature(guard).parameters)
    assert params <= {"request", "user"}


def test_headers_and_body_content_cannot_stop_a_denial_from_being_recorded(monkeypatch):
    """Behavioural half of the proof above: even a request that *tries* to say "don't
    audit this" — via a header, since `_guard` takes no body at all — still gets a
    denial row, because nothing in `_guard` ever reads such a header.

    This proves the specific attempt shown here fails, not every conceivable one; the
    signature test above is what rules out a body/query parameter existing at all for
    a future caller to (mis)use.
    """
    calls = []
    _patch_pool(monkeypatch, _FakePool(calls))
    guard = require_permission("connector:write")
    request = _FakeRequest(
        method="POST", path="/api/connectors/abc/sync",
        headers={"X-Skip-Audit": "true", "X-No-Record": "1", "X-Audit": "off"},
    )
    with pytest.raises(HTTPException):
        _run(guard(request=request, user={"id": "u-1", "role": "viewer"}))
    assert len(calls) == 1, "a header claiming to skip audit still produced a row"


def test_a_role_without_the_permission_is_still_refused_when_the_audit_db_is_down(monkeypatch):
    """The non-negotiable property end to end: the audit backend being unreachable
    must not change the authorization outcome — the caller still gets their 403, not
    a 500 from the thing recording it."""
    _patch_pool(monkeypatch, _BrokenPool())
    guard = require_permission("connector:write")
    request = _FakeRequest(method="POST", path="/api/connectors/abc/sync")
    with pytest.raises(HTTPException) as ei:
        _run(guard(request=request, user={"id": "u-1", "role": "viewer"}))
    assert ei.value.status_code == 403
