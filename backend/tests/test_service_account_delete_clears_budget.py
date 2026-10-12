"""Deleting a service account also removes it from the model gateway.

The gateway keeps one "customer" per caller id, with its spend and its cap. Deleting
the DataPond account left that row behind: on the live gateway on 2026-10-12 a
customer for a long-deleted rehearsal account still carried a 1e-07 cap and showed up
in Settings → Budgets with no account to match. The delete is best effort — a gateway
that does not answer must not keep an operator from removing a credential.

One delete is not the end of it. The gateway writes spend asynchronously and creates
the customer row as a side effect, so an account deleted right after its last call
gets its row back a few seconds later (seen live, same day: two rehearsal accounts
deleted with 204, both listed again as customers a minute on). The retention tick
therefore re-sends the delete for every account removed in the last few days; a 404
from the gateway is the goal, not a failure.
"""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ai_budgets, auth, service_account_routes as sar

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ACCT = "22222222-2222-2222-2222-222222222222"


class _Conn:
    def __init__(self, result):
        self.result = result

    async def execute(self, sql, *args):
        assert "DELETE FROM users" in sql and args == (ACCT,)
        return self.result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


class _Resp:
    status_code, text = 200, "{}"


def _gateway_calls(monkeypatch, *, fail=False):
    calls = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            if fail:
                raise ConnectionError("gateway down")
            calls.append((url, json))
            return _Resp()
    monkeypatch.setattr(ai_budgets.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ai_budgets, "_gateway", lambda: ("http://gw", "k"))
    return calls


def _client(monkeypatch, result="DELETE 1"):
    async def _pool():
        return _Pool(_Conn(result))

    async def _event(kind, **kw):
        pass
    monkeypatch.setattr(sar, "_get_pool", _pool)
    monkeypatch.setattr(sar, "record_auth_event", _event)
    app = FastAPI()
    app.include_router(sar.router, prefix="/api")

    async def _admin():
        return ADMIN
    app.dependency_overrides[auth.require_admin] = _admin
    return TestClient(app)


def test_the_gateway_customer_goes_with_the_account(monkeypatch):
    calls = _gateway_calls(monkeypatch)
    r = _client(monkeypatch).delete(f"/api/service-accounts/{ACCT}")
    assert r.status_code == 204, r.text
    assert calls == [("http://gw/customer/delete", {"user_ids": [ACCT]})]


def test_an_unknown_account_touches_nothing_at_the_gateway(monkeypatch):
    calls = _gateway_calls(monkeypatch)
    r = _client(monkeypatch, result="DELETE 0").delete(f"/api/service-accounts/{ACCT}")
    assert r.status_code == 404
    assert calls == []


def test_a_silent_gateway_does_not_keep_the_account_alive(monkeypatch):
    _gateway_calls(monkeypatch, fail=True)
    r = _client(monkeypatch).delete(f"/api/service-accounts/{ACCT}")
    assert r.status_code == 204, r.text


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Missing:
    status_code, text = 404, '{"error":{"message":"End User Id=x does not exist in db"}}'


def test_a_customer_the_gateway_never_had_counts_as_gone(monkeypatch):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            return _Missing()
    monkeypatch.setattr(ai_budgets.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ai_budgets, "_gateway", lambda: ("http://gw", "k"))
    assert _run(ai_budgets.forget_caller(ACCT)) is True


class _AuditConn:
    """The auth audit log as the sweep reads it: who was deleted, how recently."""
    def __init__(self, ids):
        self.ids, self.sql, self.args = ids, None, None

    async def fetch(self, sql, *args):
        self.sql, self.args = sql, args
        return [{"id": i} for i in self.ids]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_the_sweep_resends_the_delete_for_every_account_removed_recently(monkeypatch):
    calls = _gateway_calls(monkeypatch)
    conn = _AuditConn([ACCT, "33333333-3333-3333-3333-333333333333"])
    gone = _run(ai_budgets.forget_deleted_callers(conn, days=7))
    assert gone == 2
    assert [j["user_ids"] for _, j in calls] == [[ACCT], ["33333333-3333-3333-3333-333333333333"]]
    # Only accounts DataPond itself deleted, and only recent ones: the audit log is
    # the source, the window is the argument, and nothing else at the gateway is touched.
    assert "user_deleted" in conn.sql and "service_account" in conn.sql
    assert 7 in conn.args


def test_the_sweep_is_quiet_when_nothing_was_deleted(monkeypatch):
    calls = _gateway_calls(monkeypatch)
    assert _run(ai_budgets.forget_deleted_callers(_AuditConn([]), days=7)) == 0
    assert calls == []
