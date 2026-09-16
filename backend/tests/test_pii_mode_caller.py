"""A caller can be held to a stricter PII guardrail than the deployment default.

The per-request recheck already reads `users` on every authenticated request, so the
mode rides along with the role rather than costing another query. It is only read
here; applying it is the middleware's job (one place, every route).
"""
import asyncio

import pytest

from app.api import auth


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


UID = "11111111-1111-1111-1111-111111111111"
CLAIMS = {"id": UID, "username": "alice", "role": "viewer"}


class _Conn:
    def __init__(self, row):
        self.row, self.sql = row, None

    async def fetchrow(self, sql, *args, **kw):
        self.sql = sql
        return self.row


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self, **kw):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _install(monkeypatch, row):
    conn = _Conn(row)

    async def _pool():
        return _Pool(conn)

    monkeypatch.setattr(auth, "_get_pool", _pool)
    return conn


def test_the_recheck_reads_the_mode_in_the_query_it_already_runs(monkeypatch):
    conn = _install(monkeypatch, {"is_active": True, "role": "admin", "pii_mode": "block"})
    _run(auth._recheck_user(UID, dict(CLAIMS)))
    assert "pii_mode" in conn.sql and conn.sql.count("SELECT") == 1


def test_a_stricter_caller_mode_rides_on_the_identity(monkeypatch):
    _install(monkeypatch, {"is_active": True, "role": "admin", "pii_mode": "block"})
    out = _run(auth._recheck_user(UID, dict(CLAIMS)))
    assert out["pii_mode"] == "block"
    assert out["role"] == "admin", "the role refresh still happens"


@pytest.mark.parametrize("value", [None, ""])
def test_no_setting_leaves_the_identity_alone(value, monkeypatch):
    _install(monkeypatch, {"is_active": True, "role": "viewer", "pii_mode": value})
    assert "pii_mode" not in _run(auth._recheck_user(UID, dict(CLAIMS)))


def test_a_database_outage_still_fails_open_without_inventing_a_mode(monkeypatch):
    async def _pool():
        raise RuntimeError("aurora unreachable")

    monkeypatch.setattr(auth, "_get_pool", _pool)
    out = _run(auth._recheck_user(UID, dict(CLAIMS)))
    assert out == CLAIMS and "pii_mode" not in out


def test_a_disabled_user_is_still_rejected(monkeypatch):
    _install(monkeypatch, {"is_active": False, "role": "admin", "pii_mode": "block"})
    assert _run(auth._recheck_user(UID, dict(CLAIMS))) is None


# ── applied once per request, not per route ──────────────────────────────────

def test_the_middleware_applies_it_where_the_user_is_resolved():
    """Seven routes call set_actor(); a guardrail wired there would be forgotten by
    the eighth. AuthMiddleware resolves the identity once per request, so that is
    where the mode is applied."""
    import inspect

    import main

    src = inspect.getsource(main.AuthMiddleware.dispatch)
    assert "request.state.user = user" in src
    assert "pii_ko.tighten(user.get(\"pii_mode\"))" in src
    # applied after the identity is known, not before
    assert src.index("request.state.user = user") < src.index("pii_ko.tighten")


def test_tighten_is_the_only_mode_call_in_the_middleware():
    """A loosen() or a raw set() here would let one request's caller relax the
    deployment default for the rest of that request."""
    import inspect

    import main

    src = inspect.getsource(main.AuthMiddleware.dispatch)
    assert "_scoped_mode.set" not in src and "pii_ko.scope" not in src
