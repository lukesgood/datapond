"""store.py against real PostgreSQL (opt-in: DATAPOND_TEST_PG_DSN)."""
import asyncio
import os
from pathlib import Path

import pytest

DSN = os.environ.get("DATAPOND_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="DATAPOND_TEST_PG_DSN not set")
SQL = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
       / "0023_semantic_metrics.sql").read_text()


def test_create_version_approve_read_back():
    import asyncpg
    from app.semantic import store

    async def go():
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
        async with pool.acquire() as c:
            await c.execute("DROP TABLE IF EXISTS public.semantic_metric_versions, "
                            "public.semantic_joins, public.semantic_metrics CASCADE")
            await c.execute(SQL)
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
