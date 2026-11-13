"""Sync history carries a diagnosis per failed table, and 'recreate' drops the target and
runs a full sync (design thinking C2)."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app import table_links
from app.api import connectors

CID = str(uuid.uuid4())
ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
TYPE = "Column 'payload' changed type from row(\"a\" varchar) to varchar; Iceberg cannot alter it in place."


class _Conn:
    def __init__(self, rows, stored):
        self.rows, self.stored = rows, stored

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        assert "FROM connector_sync_history" in sql
        return self.rows

    async def fetchval(self, sql, *args):
        if "SELECT target_table" in sql:
            return self.stored.get("target_table")
        if "SELECT target_catalog" in sql:
            return self.stored.get("target_catalog")
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if "INSERT INTO auth_audit_log" in sql:
            self.stored.setdefault("audit", []).append(args)
            return "INSERT 0 1"
        raise AssertionError(sql)


class _Pool:
    def __init__(self, rows=None, stored=None):
        self.rows, self.stored = rows or [], stored if stored is not None else {}

    def acquire(self):
        return _Conn(self.rows, self.stored)


@pytest.fixture
def world(monkeypatch):
    calls = {"dropped": [], "synced": []}

    async def _access(*a, **k):
        return None
    monkeypatch.setattr(connectors, "require_access", _access)

    class _Trino:
        target_catalog = None
    monkeypatch.setattr(connectors, "_is_trino_backed", lambda c: True)

    async def _instance(cid):
        return _Trino()
    monkeypatch.setattr(connectors, "_get_connector_instance", _instance)
    monkeypatch.setattr(connectors, "_drop_target_table", lambda ref: calls["dropped"].append(ref.sql()))

    async def _sync(cid, request=None, user=None):
        calls["synced"].append((request.source_table, request.sync_mode.value))
        return {"status": "success", "rows_processed": 9000}
    monkeypatch.setattr(connectors, "trigger_sync", _sync)
    yield calls
    table_links.set_links(table_links.Links())


def test_history_tables_carry_a_diagnosis(monkeypatch, world):
    row = {"id": uuid.uuid4(), "started_at": None, "completed_at": None, "status": "failed",
           "rows_processed": 0, "rows_failed": 0, "error_message": TYPE,
           "metadata": {"tables": [{"table": "public.api_events", "ok": False, "error": TYPE},
                                   {"table": "public.orders", "ok": True, "rows": 6000}]}}

    async def _pool():
        return _Pool(rows=[row])
    monkeypatch.setattr(connectors, "get_db_pool", _pool)
    (s,) = asyncio.run(connectors.get_sync_history(CID, user=ADMIN))
    bad, good = s["tables"]
    assert bad["diagnosis"]["code"] == "type_change" and bad["diagnosis"]["action"] == "recreate"
    assert good.get("diagnosis") is None


def test_recreate_drops_the_target_then_runs_a_full_sync(monkeypatch, world):
    pool = _Pool(stored={"target_table": "datapond.default.public.api_events", "target_catalog": None})

    async def _pool():
        return pool
    monkeypatch.setattr(connectors, "get_db_pool", _pool)
    out = asyncio.run(connectors.recreate_table(CID, "public.api_events", user=ADMIN))
    assert world["dropped"] == ["iceberg.default.api_events"]
    assert world["synced"] == [("public.api_events", "full")]
    assert out["recreated"] == "iceberg.default.api_events" and out["status"] == "success"
    assert pool.stored["audit"][0][0] == "sync_target_recreated"


def test_recreate_uses_the_table_s_target_catalog(monkeypatch, world):
    async def _pool():
        return _Pool(stored={"target_table": None, "target_catalog": "polaris_lake"})
    monkeypatch.setattr(connectors, "get_db_pool", _pool)
    asyncio.run(connectors.recreate_table(CID, "public.customers", user=ADMIN))
    assert world["dropped"] == ["polaris_lake.default.customers"]


def test_recreate_refuses_a_mirror(monkeypatch, world):
    table_links.set_links(table_links.Links.from_rows([{
        "mirror_catalog": "iceberg", "mirror_schema": "default", "mirror_table": "orders",
        "owner_catalog": "polaris_lake", "owner_schema": "default", "owner_table": "orders"}]))

    async def _pool():
        return _Pool(stored={})
    monkeypatch.setattr(connectors, "get_db_pool", _pool)
    with pytest.raises(HTTPException) as e:
        asyncio.run(connectors.recreate_table(CID, "public.orders", user=ADMIN))
    assert e.value.status_code == 409 and world["dropped"] == []
