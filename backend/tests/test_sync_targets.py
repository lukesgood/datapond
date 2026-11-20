"""One lake table per source table (app/sync_targets.py).

Live 2026-11-20: Sample E-Commerce DB's customers was synced by two jobs, `customers` into
iceberg and `public.customers` into polaris_lake — two copies drifting apart, the second
invisible on the connection page. A connection may no longer land two jobs in one
namespace.table; changing a synced table's catalog asks to move it or leave it; existing
duplicates are reported and an alias spelling updates the job it means."""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import catalog_registry as reg
from app import sync_targets
from app.api import connectors
from app.catalog_registry import CatalogEntry

CID = "00000000-0000-0000-0000-0000000000cc"
ADMIN = {"id": "u1", "username": "root", "role": "admin"}
ANALYST = {"id": "u2", "username": "kim", "role": "business_analyst"}
ENGINEER_NO_CATALOG = {"id": "u3", "username": "lee", "role": "x", "permissions": ["connector:write"]}
RAN = datetime(2026, 11, 13, 2, 9, tzinfo=timezone.utc)


def job(source, catalog=None, enabled=True, ran=RAN, target=None):
    return {"id": uuid.uuid4(), "connection_id": CID, "source_table": source,
            "target_table": target or f"datapond.default.{source}", "target_catalog": catalog,
            "enabled": enabled, "last_run_at": ran, "rows_synced": 1200}


# ── the pure rule ─────────────────────────────────────────────────────────────

def test_a_schema_qualified_spelling_lands_in_the_same_table():
    assert sync_targets.lake_table("customers", "datapond.default.customers") == ("default", "customers")
    assert sync_targets.lake_table("public.customers", "datapond.default.public.customers") == ("default", "customers")


def test_conflict_finds_the_other_spelling_but_not_itself_or_other_tables():
    jobs = [job("customers"), job("orders")]
    assert sync_targets.conflict(jobs, "public.customers", "datapond.default.public.customers")["source_table"] == "customers"
    assert sync_targets.conflict(jobs, "customers", "datapond.default.customers") is None
    assert sync_targets.conflict(jobs, "public.payments", None) is None


def test_duplicates_group_enabled_jobs_across_catalogs():
    later = datetime(2026, 11, 20, 3, 18, tzinfo=timezone.utc)
    groups = sync_targets.duplicates([job("customers"), job("public.customers", "polaris_lake", ran=later),
                                      job("orders"), job("public.orders", enabled=False)])
    assert len(groups) == 1
    g = groups[0]
    assert (g["namespace"], g["table"]) == ("default", "customers")
    assert [j["source_table"] for j in g["jobs"]] == ["customers", "public.customers"]
    assert [j["catalog"] for j in g["jobs"]] == [None, "polaris_lake"]


# ── the route ─────────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        return list(self.db["jobs"])

    async def fetchval(self, sql, *args):
        mine = next((j for j in self.db["jobs"] if j["source_table"] == args[-1]), None)
        if "SELECT id FROM connector_sync_jobs" in sql:
            return mine["id"] if mine else None
        if "SELECT target_catalog" in sql:
            return mine["target_catalog"] if mine else None
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("UPDATE connector_sync_jobs SET target_catalog"):
            for j in self.db["jobs"]:
                if j["source_table"] == args[-1]:
                    j["target_catalog"] = args[0]
        elif s.startswith("INSERT INTO connector_sync_jobs"):
            self.db["jobs"].append(job(args[2], ran=None))
        elif not s.startswith("UPDATE connector_sync_jobs SET"):
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
                     CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake")])
    db = {"jobs": [job("customers")], "moved": []}

    async def _pool():
        return _Pool(db)
    monkeypatch.setattr(connectors, "get_db_pool", _pool)

    async def _access(*a, **k):
        return None
    monkeypatch.setattr(connectors, "require_access", _access)

    async def _move(pool, src, dst, schema, table, user):
        db["moved"].append((src, dst, schema, table))
    monkeypatch.setattr(connectors, "_move_table", _move)
    yield db
    reg.reset()


def _set(table, body, user=ADMIN):
    return asyncio.run(connectors.set_table_enabled(CID, table, body, user=user))


def test_a_second_job_for_the_same_table_is_refused(world):
    with pytest.raises(HTTPException) as e:
        _set("public.customers", {"enabled": True, "target_catalog": "polaris_lake"})
    assert e.value.status_code == 409
    assert e.value.detail["code"] == "duplicate_target"
    assert e.value.detail["other"] == "customers" and e.value.detail["other_catalog"] == "iceberg"
    assert [j["source_table"] for j in world["jobs"]] == ["customers"]


def test_a_disabled_duplicate_may_be_turned_off_and_edited(world):
    world["jobs"].append(job("public.customers", "polaris_lake"))
    out = _set("public.customers", {"enabled": False})
    assert out["enabled"] is False


def test_changing_the_catalog_of_a_synced_table_needs_a_choice(world):
    with pytest.raises(HTTPException) as e:
        _set("customers", {"enabled": True, "target_catalog": "polaris_lake"})
    d = e.value.detail
    assert e.value.status_code == 409 and d["code"] == "target_has_data"
    assert (d["from"], d["to"], d["table"], d["rows"]) == ("iceberg", "polaris_lake", "default.customers", 1200)
    assert world["jobs"][0]["target_catalog"] is None


def test_move_registers_the_table_in_the_new_catalog_then_saves(world):
    out = _set("customers", {"enabled": True, "target_catalog": "polaris_lake", "existing": "move"})
    assert world["moved"] == [("iceberg", "polaris_lake", "default", "customers")]
    assert out["target_catalog"] == "polaris_lake"


def test_leave_saves_without_moving(world):
    out = _set("customers", {"enabled": True, "target_catalog": "polaris_lake", "existing": "leave"})
    assert world["moved"] == [] and out["target_catalog"] == "polaris_lake"


def test_moving_needs_catalog_write(world):
    with pytest.raises(HTTPException) as e:
        _set("customers", {"enabled": True, "target_catalog": "polaris_lake", "existing": "move"},
             user=ENGINEER_NO_CATALOG)
    assert e.value.status_code == 403 and world["moved"] == []


def test_a_table_that_never_synced_changes_catalog_freely(world):
    world["jobs"][0]["last_run_at"] = None
    out = _set("customers", {"enabled": True, "target_catalog": "polaris_lake"})
    assert out["target_catalog"] == "polaris_lake"


def test_an_alias_spelling_resolves_to_the_job_it_means(world):
    world["jobs"][0]["target_catalog"] = "polaris_lake"
    assert asyncio.run(connectors._resolve_target_catalog(_Pool(world), CID, "public.customers", None)) == "polaris_lake"
    found = asyncio.run(connectors._job_for(_Pool(world), CID, "public.customers"))
    assert found["source_table"] == "customers"
