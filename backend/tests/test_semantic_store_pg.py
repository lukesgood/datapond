"""store.py against real PostgreSQL (opt-in: DATAPOND_TEST_PG_DSN)."""
import asyncio
import os
from pathlib import Path

import pytest

DSN = os.environ.get("DATAPOND_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="DATAPOND_TEST_PG_DSN not set")
VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0023_semantic_metrics.sql").read_text()
# 0023 widens tool_call_log's CHECK, so the table 0008 creates must exist first.
TOOL_CALL_LOG = (VERSIONS / "0008_tool_call_log.sql").read_text().split("CREATE INDEX")[0]


async def _fresh_pool():
    import asyncpg
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    async with pool.acquire() as c:
        await c.execute("DROP TABLE IF EXISTS public.semantic_metric_versions, "
                        "public.semantic_joins, public.semantic_metrics, "
                        "public.tool_call_log CASCADE")
        await c.execute("CREATE TABLE IF NOT EXISTS public.users (id uuid PRIMARY KEY)")
        await c.execute(TOOL_CALL_LOG)
        await c.execute(SQL)
    return pool


def test_create_version_approve_read_back():
    from app.semantic import store

    async def go():
        pool = await _fresh_pool()
        mid = await store.create_metric(pool, name="revenue", label="매출", description="",
                                        synonyms=["sales"], owner_id=None, owner_name="root")
        fields = {"catalog": "glue", "base_table": "sales.orders", "measure": "SUM(amount)",
                  "time_column": "ordered_at", "grains": ["month"],
                  "dimensions": [{"name": "region", "column": "region",
                                  "join": {"to_table": "sales.customers", "on": [["customer_id", "id"]]}}]}
        n1 = await store.insert_version(pool, metric_id=mid, fields=fields, created_by=None,
                                        created_by_name="root", change_note="first")
        n2 = await store.insert_version(pool, metric_id=mid, fields=fields, created_by=None,
                                        created_by_name="root", change_note="second")
        assert (n1, n2) == (1, 2)
        await store.approve_version(pool, metric_id=mid, version=1, approver_id=None,
                                    approver_name="root")
        meta = await store.get_metric(pool, "revenue")
        assert (meta["status"], meta["current_version"]) == ("approved", 1)
        v = await store.get_version(pool, mid, "revenue", 1)
        assert v.approved_by == "root" and v.dimensions[0].join.on == (("customer_id", "id"),)
        assert [r["version"] for r in await store.list_versions(pool, mid)] == [2, 1]
        (listed,) = await store.list_metrics(pool)
        assert listed["catalog"] == "glue"
        jid = await store.insert_join(pool, catalog="glue", from_table="sales.orders",
                                      to_table="sales.customers", on_columns=[["customer_id", "id"]],
                                      source="manual", approver_id=None, approver_name="root")
        again = await store.insert_join(pool, catalog="glue", from_table="sales.orders",
                                        to_table="sales.customers", on_columns=[["customer_id", "id"]],
                                        source="history", approver_id=None, approver_name="root")
        assert jid == again
        await pool.close()
    asyncio.run(go())


def test_approve_refuses_a_missing_an_approved_or_an_older_version():
    """Nothing changes unless an unapproved version newer than the current one exists:
    approving an older draft would roll current_version back."""
    from app.semantic import store

    async def go():
        pool = await _fresh_pool()
        mid = await store.create_metric(pool, name="revenue", label="매출", description="",
                                        synonyms=[], owner_id=None, owner_name="root")
        fields = {"catalog": "glue", "base_table": "sales.orders", "measure": "SUM(amount)"}
        for note in ("one", "two", "three"):
            await store.insert_version(pool, metric_id=mid, fields=fields, created_by=None,
                                       created_by_name="root", change_note=note)
        await store.approve_version(pool, metric_id=mid, version=3, approver_id=None,
                                    approver_name="root")
        for version in (3, 2, 9):          # already approved, older than current, missing
            with pytest.raises(store.NotApprovable):
                await store.approve_version(pool, metric_id=mid, version=version,
                                            approver_id=None, approver_name="root")
        meta = await store.get_metric(pool, "revenue")
        assert meta["current_version"] == 3
        assert (await store.get_version(pool, mid, "revenue", 2)).approved_at is None
        await pool.close()
    asyncio.run(go())
