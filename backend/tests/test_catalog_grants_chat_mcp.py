"""Catalog grants in the assistant's catalog tools, which are also the MCP tools.

find_tables lists only the caller's catalogs, describe_table answers a hidden catalog
exactly as an unknown one, and explain_relationships drops hidden catalogs' tables.
Over MCP an agent key sees what its account may use — an admin account's key included.
"""
import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import catalog_access
from app import catalog_registry as reg
from app.api import auth
from app.catalog_registry import CatalogEntry
from app.chat import executors
from app.chat.analysis import catalog as chat_catalog
from app.mcp import server
from tests.conftest import _Conn, _Pool, _patch_pool

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "auditor"}
ADMIN = {"id": "33333333-3333-3333-3333-333333333333", "username": "root", "role": "admin"}
ADMIN_KEY = {**ADMIN, "auth_method": "service", "permissions": ["catalog:read"]}


def _run(coro):
    return asyncio.run(coro)


class _R:
    def __init__(self, name, tree):
        self.name, self.tree = name, tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]

    def get_columns(self, ns, t):
        return [{"name": f"{self.name}_id", "type": "bigint"}]


READERS = {"iceberg": _R("iceberg", {"sales": ["orders"]}),
           "finance": _R("finance", {"ledger": ["entries", "orders_fx"]})}


@pytest.fixture(autouse=True)
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])
    catalog_access.set_grants({"finance": [("user", BOB["id"])]})
    reader = lambda name=None: READERS[reg.resolve(name).name]  # noqa: E731
    monkeypatch.setattr(chat_catalog, "get_catalog_reader", reader)
    import app.api.catalog_backend as cb
    monkeypatch.setattr(cb, "get_catalog_reader", reader)
    yield
    reg.reset()


def _find(user, query="orders"):
    return set(_run(executors.EXECUTORS["catalog.find_tables"]({"query": query}, user))["tables"])


def test_find_tables_in_an_open_catalog_is_unchanged():
    catalog_access.set_grants({})
    assert _find(ALICE) == {"sales.orders", "finance.ledger.orders_fx"}


def test_find_tables_leaves_out_a_hidden_catalog():
    assert _find(ALICE) == {"sales.orders"}
    assert _find(BOB) == {"sales.orders", "finance.ledger.orders_fx"}
    assert _find(ADMIN) == {"sales.orders", "finance.ledger.orders_fx"}


def test_describe_table_of_a_hidden_catalog_is_the_unknown_catalog_error():
    describe = executors.EXECUTORS["catalog.describe_table"]
    with pytest.raises(reg.UnknownCatalog) as hidden:
        _run(describe({"catalog": "finance", "namespace": "ledger", "table": "entries"}, ALICE))
    with pytest.raises(reg.UnknownCatalog) as unknown:
        _run(describe({"catalog": "nope", "namespace": "ledger", "table": "entries"}, ALICE))
    assert str(hidden.value) == str(unknown.value).replace("nope", "finance")
    out = _run(describe({"catalog": "finance", "namespace": "ledger", "table": "entries"}, BOB))
    assert out["table"] == "finance.ledger.entries"


def test_explain_relationships_leaves_out_hidden_catalogs(monkeypatch):
    import app.api.queries as q
    schema = {
        "iceberg.sales.orders": [{"name": "account_id", "type": "bigint"}],
        "finance.ledger.accounts": [{"name": "id", "type": "bigint"}],
    }
    monkeypatch.setattr(q, "_catalog_schema_for_graph", lambda: schema)
    run = executors.EXECUTORS["catalog.explain_relationships"]
    assert _run(run({}, ALICE))["relationships"] == []
    assert len(_run(run({}, BOB))["relationships"]) == 1


# ── over MCP ─────────────────────────────────────────────────────────────────

def _mcp(user, name, arguments):
    app = FastAPI()
    app.include_router(server.router, prefix="/api")

    async def _override():
        return user
    app.dependency_overrides[auth.require_user] = _override
    r = TestClient(app).post("/api/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments}})
    return r.json()["result"]


def test_an_admin_accounts_key_sees_over_mcp_only_what_its_grants_allow(monkeypatch):
    monkeypatch.setenv("FEATURE_POLARIS", "true")
    _patch_pool(monkeypatch, _Pool(_Conn()))
    found = _mcp(ADMIN_KEY, "catalog_find_tables", {"query": "orders"})
    assert found["isError"] is False
    assert "finance" not in found["content"][0]["text"]

    hidden = _mcp(ADMIN_KEY, "catalog_describe_table",
                  {"catalog": "finance", "namespace": "ledger", "table": "entries"})
    unknown = _mcp(ADMIN_KEY, "catalog_describe_table",
                   {"catalog": "nope", "namespace": "ledger", "table": "entries"})
    assert hidden["isError"] is True
    assert hidden["content"] == unknown["content"]

    catalog_access.set_grants({"finance": [("user", ADMIN["id"])]})
    found = _mcp(ADMIN_KEY, "catalog_find_tables", {"query": "orders"})
    assert "finance.ledger.orders_fx" in json.dumps(found)
