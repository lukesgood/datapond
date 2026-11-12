"""The per-table sync settings carry the target catalog (persona review #3): the console
can choose where a table lands and show it."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app import catalog_registry as reg
from app.api import connectors
from app.catalog_registry import CatalogEntry

CID = "00000000-0000-0000-0000-0000000000bb"
ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}


class _Conn:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetchval(self, sql, *args):
        if "SELECT id FROM connector_sync_jobs" in sql:
            return self.db.get("id")
        if "SELECT target_catalog" in sql:
            return self.db.get("target_catalog")
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("UPDATE connector_sync_jobs SET target_catalog"):
            self.db["target_catalog"] = args[0]
        elif s.startswith("UPDATE connector_sync_jobs SET") or s.startswith("INSERT INTO connector_sync_jobs"):
            self.db["id"] = self.db.get("id") or uuid.uuid4()
        else:
            raise AssertionError(s)
        return "OK"


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _Conn(self.db)


@pytest.fixture
def world(monkeypatch):
    reg.set_entries([CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True),
                     CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake"),
                     CatalogEntry(name="src_crm", kind="trino_source", engine_catalog="src_crm")])
    db = {"id": uuid.uuid4()}

    async def _pool():
        return _Pool(db)
    monkeypatch.setattr(connectors, "get_db_pool", _pool)

    async def _access(*a, **k):
        return None
    monkeypatch.setattr(connectors, "require_access", _access)
    yield db
    reg.reset()


def _set(body):
    return asyncio.run(connectors.set_table_enabled(CID, "public.orders", body, user=ADMIN))


def test_a_target_catalog_is_stored_by_its_engine_name_and_returned(world):
    out = _set({"enabled": True, "target_catalog": "polaris_lake"})
    assert world["target_catalog"] == "polaris_lake" and out["target_catalog"] == "polaris_lake"


def test_an_empty_target_goes_back_to_the_default(world):
    world["target_catalog"] = "polaris_lake"
    out = _set({"enabled": True, "target_catalog": ""})
    assert world["target_catalog"] is None and out["target_catalog"] is None


def test_a_source_catalog_is_refused_and_omitting_the_field_keeps_it(world):
    with pytest.raises(HTTPException) as e:
        _set({"enabled": True, "target_catalog": "src_crm"})
    assert e.value.status_code == 400
    world["target_catalog"] = "polaris_lake"
    _set({"enabled": False})
    assert world["target_catalog"] == "polaris_lake"
