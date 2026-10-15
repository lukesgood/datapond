"""0023 against a real PostgreSQL. Opt-in: set DATAPOND_TEST_PG_DSN to a scratch
database (it is dropped and recreated schema-wise). CI's fresh-install job runs the
migration for real; this proves the trigger's behaviour locally."""
import asyncio
import os
from pathlib import Path

import pytest

DSN = os.environ.get("DATAPOND_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="DATAPOND_TEST_PG_DSN not set")
VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0023_semantic_metrics.sql").read_text()
# 0008's CREATE TABLE, with its inline CHECKs exactly as deployed; the trigger and prune
# function after it need 0005 and are not what this test is about.
TOOL_CALL_LOG = (VERSIONS / "0008_tool_call_log.sql").read_text().split("CREATE INDEX")[0]


async def _fresh():
    import asyncpg
    conn = await asyncpg.connect(DSN)
    await conn.execute("DROP TABLE IF EXISTS public.semantic_metric_versions, "
                       "public.semantic_joins, public.semantic_metrics, "
                       "public.tool_call_log CASCADE")
    await conn.execute("CREATE TABLE IF NOT EXISTS public.users (id uuid PRIMARY KEY)")
    await conn.execute(TOOL_CALL_LOG)
    await conn.execute(SQL)
    await conn.execute(SQL)                      # idempotent
    mid = await conn.fetchval(
        "INSERT INTO semantic_metrics (name, label) VALUES ('revenue', '매출') RETURNING id")
    await conn.execute(
        "INSERT INTO semantic_metric_versions (metric_id, version, catalog, base_table, measure) "
        "VALUES ($1, 1, 'glue', 'sales.orders', 'SUM(amount)')", mid)
    return conn, mid


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_approving_an_unapproved_version_is_allowed():
    async def go():
        conn, mid = await _fresh()
        await conn.execute("UPDATE semantic_metric_versions SET approved_by_name='root', "
                           "approved_at=now() WHERE metric_id=$1 AND version=1", mid)
        await conn.close()
    _run(go())


def test_editing_a_version_is_refused():
    import asyncpg

    async def go():
        conn, mid = await _fresh()
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("UPDATE semantic_metric_versions SET measure='SUM(x)' "
                               "WHERE metric_id=$1", mid)
        await conn.close()
    _run(go())


def test_approving_twice_is_refused():
    import asyncpg

    async def go():
        conn, mid = await _fresh()
        await conn.execute("UPDATE semantic_metric_versions SET approved_at=now() WHERE metric_id=$1", mid)
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("UPDATE semantic_metric_versions SET approved_at=now(), "
                               "approved_by_name='other' WHERE metric_id=$1", mid)
        await conn.close()
    _run(go())


def test_deleting_a_version_is_refused():
    import asyncpg

    async def go():
        conn, mid = await _fresh()
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM semantic_metric_versions WHERE metric_id=$1", mid)
        await conn.close()
    _run(go())


def test_bad_metric_name_is_refused_by_the_database():
    import asyncpg

    async def go():
        conn, _ = await _fresh()
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute("INSERT INTO semantic_metrics (name, label) VALUES ('Bad-Name', 'x')")
        await conn.close()
    _run(go())


_TCL_ROW = ("INSERT INTO tool_call_log (actor_kind, tool, resource_kind, request_hash, outcome) "
            "VALUES ('human', 'ai.sql', $1, 'h', 'ok')")


def test_tool_call_log_takes_a_metric_row_and_still_refuses_others():
    import asyncpg

    async def go():
        conn, _ = await _fresh()
        await conn.execute(_TCL_ROW, "metric")
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(_TCL_ROW, "bogus")
        await conn.close()
    _run(go())
