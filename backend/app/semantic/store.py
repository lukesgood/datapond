"""The three semantic tables, read and written with asyncpg. Nothing here decides who
may do what — that is service.py and the router."""
import json
from typing import List, Optional

from app.semantic.model import Dimension, Join, MetricVersion

_METRIC_COLS = ("id, name, label, description, synonyms, owner_id::text AS owner_id, "
                "owner_name, status, current_version, updated_at")


def row_to_version(metric_name: str, r) -> MetricVersion:
    dims = r["dimensions"]
    if isinstance(dims, str):
        dims = json.loads(dims)
    return MetricVersion(
        metric=metric_name, version=r["version"], catalog=r["catalog"],
        base_table=r["base_table"], measure=r["measure"], filters=r["filters"],
        time_column=r["time_column"], grains=tuple(r["grains"] or ()),
        max_period_days=r["max_period_days"],
        dimensions=tuple(
            Dimension(d["name"], d["column"],
                      Join(d["join"]["to_table"], tuple(tuple(p) for p in d["join"]["on"]))
                      if d.get("join") else None)
            for d in dims),
        approved_by=r["approved_by_name"],
        approved_at=r["approved_at"].isoformat() if r["approved_at"] else None,
        created_by=str(r["created_by"]) if r["created_by"] else None)


async def get_metric(pool, name: str) -> Optional[dict]:
    async with pool.acquire() as c:
        r = await c.fetchrow(f"SELECT {_METRIC_COLS} FROM semantic_metrics WHERE name = $1", name)
    return dict(r) if r else None


async def list_metrics(pool) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch(f"""
            SELECT {', '.join('m.' + x.strip() for x in _METRIC_COLS.split(','))},
                   (SELECT v.catalog FROM semantic_metric_versions v
                     WHERE v.metric_id = m.id
                     ORDER BY (v.version = m.current_version) DESC, v.version DESC
                     LIMIT 1) AS catalog
              FROM semantic_metrics m ORDER BY m.name""")
    return [dict(r) for r in rows]


async def get_version(pool, metric_id: int, metric_name: str, version: int) -> Optional[MetricVersion]:
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM semantic_metric_versions "
                             "WHERE metric_id = $1 AND version = $2", metric_id, version)
    return row_to_version(metric_name, r) if r else None


async def latest_version_number(pool, metric_id: int) -> int:
    async with pool.acquire() as c:
        return int(await c.fetchval("SELECT COALESCE(MAX(version), 0) FROM "
                                    "semantic_metric_versions WHERE metric_id = $1", metric_id))


async def list_versions(pool, metric_id: int) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM semantic_metric_versions WHERE metric_id = $1 "
                             "ORDER BY version DESC", metric_id)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["dimensions"], str):
            d["dimensions"] = json.loads(d["dimensions"])
        for k in ("created_by", "approved_by"):
            d[k] = str(d[k]) if d[k] else None
        for k in ("created_at", "approved_at"):
            d[k] = d[k].isoformat() if d[k] else None
        out.append(d)
    return out


async def create_metric(pool, *, name, label, description, synonyms, owner_id, owner_name) -> int:
    async with pool.acquire() as c:
        return await c.fetchval(
            "INSERT INTO semantic_metrics (name, label, description, synonyms, owner_id, owner_name) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            name, label, description, list(synonyms), owner_id, owner_name)


async def insert_version(pool, *, metric_id: int, fields: dict, created_by, created_by_name,
                         change_note: str) -> int:
    async with pool.acquire() as c:
        async with c.transaction():
            # Serialise version numbering per metric.
            await c.execute("SELECT id FROM semantic_metrics WHERE id = $1 FOR UPDATE", metric_id)
            n = 1 + int(await c.fetchval("SELECT COALESCE(MAX(version), 0) FROM "
                                         "semantic_metric_versions WHERE metric_id = $1", metric_id))
            await c.execute(
                """INSERT INTO semantic_metric_versions
                     (metric_id, version, catalog, base_table, measure, filters, time_column,
                      grains, max_period_days, dimensions, created_by, created_by_name, change_note)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13)""",
                metric_id, n, fields["catalog"], fields["base_table"], fields["measure"],
                fields.get("filters"), fields.get("time_column"), list(fields.get("grains") or ()),
                int(fields.get("max_period_days") or 366), json.dumps(fields.get("dimensions") or []),
                created_by, created_by_name, change_note or "")
            await c.execute("UPDATE semantic_metrics SET updated_at = now() WHERE id = $1", metric_id)
    return n


class NotApprovable(Exception):
    """The version is missing, already approved, or older than the current one."""


async def approve_version(pool, *, metric_id: int, version: int, approver_id, approver_name) -> None:
    async with pool.acquire() as c:
        async with c.transaction():
            # Never backwards: approving an older draft would roll current_version back.
            moved = await c.execute(
                "UPDATE semantic_metrics SET status = 'approved', current_version = $2, "
                "updated_at = now() WHERE id = $1 "
                "AND (current_version IS NULL OR current_version < $2)", metric_id, version)
            stamped = await c.execute(
                "UPDATE semantic_metric_versions SET approved_by = $3, approved_by_name = $4, "
                "approved_at = now() WHERE metric_id = $1 AND version = $2 AND approved_at IS NULL",
                metric_id, version, approver_id, approver_name)
            if moved != "UPDATE 1" or stamped != "UPDATE 1":
                raise NotApprovable(f"version {version} cannot be approved")   # rolls back


async def retire_metric(pool, metric_id: int) -> None:
    async with pool.acquire() as c:
        await c.execute("UPDATE semantic_metrics SET status = 'retired', updated_at = now() "
                        "WHERE id = $1", metric_id)


async def list_joins(pool, catalog: Optional[str] = None) -> List[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT id, catalog, from_table, to_table, on_columns, source, approved_by_name, "
            "approved_at FROM semantic_joins WHERE $1::text IS NULL OR lower(catalog) = lower($1) "
            "ORDER BY from_table, to_table, id", catalog)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["on_columns"], str):
            d["on_columns"] = json.loads(d["on_columns"])
        d["approved_at"] = d["approved_at"].isoformat() if d["approved_at"] else None
        out.append(d)
    return out


async def get_join(pool, join_id: int) -> Optional[dict]:
    for j in await list_joins(pool):
        if j["id"] == join_id:
            return j
    return None


async def insert_join(pool, *, catalog, from_table, to_table, on_columns, source,
                      approver_id, approver_name) -> int:
    async with pool.acquire() as c:
        return await c.fetchval(
            """INSERT INTO semantic_joins (catalog, from_table, to_table, on_columns, source,
                                           approved_by, approved_by_name)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7)
               ON CONFLICT (catalog, from_table, to_table, on_columns)
               DO UPDATE SET source = semantic_joins.source
               RETURNING id""",
            catalog, from_table, to_table, json.dumps(on_columns), source, approver_id, approver_name)
