"""The service-account list carries what the console needs to link an OAuth client.

`PUT /service-accounts/{id}/oauth-client` existed with no screen: the list did not say
which client an account was linked to, nor whether the deployment accepts IdP tokens
at all, so the console could not show either.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from app.api import service_account_routes as sar

ISSUER = "https://idp.example.com/oauth2/default"
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def _account(id_, external_id=None, external_provider=None):
    return {"id": id_, "username": f"svc-{id_}", "display_name": id_, "role": "analyst",
            "is_active": True, "created_at": NOW,
            "external_id": external_id, "external_provider": external_provider}


class _Conn:
    def __init__(self, accounts):
        self.accounts = accounts

    async def fetch(self, sql, *args):
        return self.accounts if "FROM users" in sql else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _list(monkeypatch, accounts):
    async def _pool():
        return _Pool(_Conn(accounts))
    monkeypatch.setattr(sar, "_get_pool", _pool)
    return asyncio.run(sar.list_service_accounts(admin={"id": "a", "role": "admin"}))


@pytest.fixture
def oauth_on(monkeypatch):
    monkeypatch.setenv("OAUTH_RS_ENABLED", "true")
    monkeypatch.setenv("OAUTH_RS_ISSUER", ISSUER)


@pytest.fixture
def oauth_off(monkeypatch):
    monkeypatch.delenv("OAUTH_RS_ENABLED", raising=False)
    monkeypatch.delenv("OAUTH_RS_ISSUER", raising=False)


def test_the_list_says_the_mode_is_off(oauth_off, monkeypatch):
    out = _list(monkeypatch, [_account("a1")])
    assert out["oauth"] == {"enabled": False, "issuer": None}


def test_the_list_names_the_issuer_when_the_mode_is_on(oauth_on, monkeypatch):
    out = _list(monkeypatch, [_account("a1")])
    assert out["oauth"] == {"enabled": True, "issuer": ISSUER}


def test_a_linked_account_shows_its_client_and_the_issuer_it_was_linked_under(oauth_on, monkeypatch):
    out = _list(monkeypatch, [_account("a1", "agent-client", ISSUER), _account("a2")])
    by_id = {a["id"]: a for a in out["accounts"]}
    assert by_id["a1"]["oauth_client"] == {"client_id": "agent-client", "issuer": ISSUER}
    assert by_id["a2"]["oauth_client"] is None


def test_the_listing_query_reads_the_link_columns(oauth_on, monkeypatch):
    seen = []

    class _Recording(_Conn):
        async def fetch(self, sql, *args):
            seen.append(sql)
            return await super().fetch(sql, *args)

    async def _pool():
        return _Pool(_Recording([]))
    monkeypatch.setattr(sar, "_get_pool", _pool)
    asyncio.run(sar.list_service_accounts(admin={"id": "a", "role": "admin"}))
    users_sql = next(s for s in seen if "FROM users" in s)
    assert "external_id" in users_sql and "external_provider" in users_sql
