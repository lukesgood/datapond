"""Which catalog a sync writes into: the one the request names, else the one the job
last used (connector_sync_jobs.target_catalog), else the engine's default. Only Iceberg
lake catalogs qualify."""
import asyncio

import pytest
from fastapi import HTTPException

from app import catalog_registry as reg
from app.api import connectors
from app.catalog_registry import CatalogEntry


class _Conn:
    def __init__(self, stored):
        self.stored = stored

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetchval(self, sql, *args):
        assert "target_catalog" in sql
        return self.stored


class _Pool:
    def __init__(self, stored=None):
        self.stored = stored

    def acquire(self):
        return _Conn(self.stored)


@pytest.fixture(autouse=True)
def registry():
    reg.set_entries([
        CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="polaris_lake", kind="polaris", engine_catalog="polaris_lake"),
        CatalogEntry(name="src_crm", kind="trino_source", engine_catalog="src_crm")])
    yield
    reg.reset()


CID = "00000000-0000-0000-0000-0000000000aa"


def _resolve(pool, requested):
    return asyncio.run(connectors._resolve_target_catalog(pool, CID, "public.orders", requested))


def test_the_requested_catalog_wins_and_is_given_by_its_engine_name():
    assert _resolve(_Pool("iceberg"), "polaris_lake") == "polaris_lake"
    assert _resolve(_Pool(), "AwsDataCatalog") == "iceberg"


def test_without_a_request_the_job_s_last_catalog_applies_else_the_default():
    assert _resolve(_Pool("polaris_lake"), None) == "polaris_lake"
    assert _resolve(_Pool(None), None) is None


def test_a_source_catalog_or_an_unknown_one_is_refused():
    with pytest.raises(HTTPException) as e:
        _resolve(_Pool(), "src_crm")
    assert e.value.status_code == 400 and "lake catalog" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _resolve(_Pool(), "nope")
    assert e.value.status_code == 400


def test_the_retry_wrapper_hands_the_target_to_the_connector():
    class C:
        target_catalog = None

        async def sync_to_iceberg(self, **kw):
            from app.connectors.base import SyncJobStatus, SyncStatus
            from datetime import datetime
            self.seen = self.target_catalog
            return SyncJobStatus(status=SyncStatus.SUCCESS, started_at=datetime.utcnow(),
                                 completed_at=datetime.utcnow(), rows_processed=1)
    c = C()
    asyncio.run(connectors._sync_with_retry(c, target_catalog="polaris_lake", source_table="t"))
    assert c.seen == "polaris_lake"
