"""Deleting a service account also removes it from the model gateway.

The gateway keeps one "customer" per caller id, with its spend and its cap. Deleting
the DataPond account left that row behind: on the live gateway on 2026-10-12 a
customer for a long-deleted rehearsal account still carried a 1e-07 cap and showed up
in Settings → Budgets with no account to match. The delete is best effort — a gateway
that does not answer must not keep an operator from removing a credential.
"""
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
