"""Keep each mirror's registration on its owner's current snapshot (app/table_links.py).

A mirror is registered at the owner's metadata file of the moment it was exported. Every
owner commit after that leaves the mirror behind — DataPond routes its own reads to the
owner, but engines outside DataPond (Athena on a Glue mirror, Spark on a Polaris one)
read the mirror directly. Each check, per link:

- **fresh**: the mirror's current metadata file is the owner's. Nothing to do.
- **stale → re-pointed**: the mirror still points at the file we registered; the owner
  moved on. `unregister_table` (catalog entry only — no data is deleted) then
  `register_table` at the owner's current file. No data is copied.
- **diverged**: the mirror's current file is neither ours nor the owner's — someone
  committed through the mirror from outside DataPond. Never overwritten (that would
  discard their commit); reported with an audit row for an operator to resolve.
- **error**: the engine refused a statement; its message is kept.

Runs as one leader-locked loop per deployment (`run`, MIRROR_CHECK_SECONDS, default
300), and on demand from `POST /api/catalogs/mirrors/check`.
"""
import asyncio
import logging
import os
from dataclasses import dataclass, asdict
from typing import List, Optional

from app.catalog_export import ident, split_metadata_path, sql_string

logger = logging.getLogger("mirror_freshness")

LOCK_KEY = 7233183143331076975


@dataclass
class Result:
    mirror: str
    owner: str
    status: str
    detail: Optional[str] = None
    refreshed: bool = False
    location: Optional[str] = None
    metadata_file: Optional[str] = None

    def as_dict(self):
        return asdict(self)


def _latest(cur, catalog: str, schema: str, table: str) -> str:
    cur.execute(f'SELECT file FROM {ident(catalog)}.{ident(schema)}."{table}$metadata_log_entries" '
                "ORDER BY timestamp DESC LIMIT 1")
    return cur.fetchone()[0]


def check_one(cur, link: dict) -> Result:
    m = (link["mirror_catalog"], link["mirror_schema"], link["mirror_table"])
    o = (link["owner_catalog"], link["owner_schema"], link["owner_table"])
    res = Result(mirror=".".join(m), owner=".".join(o), status="fresh",
                 location=link["location"], metadata_file=link["mirror_metadata_file"])
    try:
        owner_loc, owner_file = split_metadata_path(_latest(cur, *o))
        mirror_loc, mirror_file = split_metadata_path(_latest(cur, *m))
    except Exception as e:
        res.status, res.detail = "error", str(e)[:500]
        return res
    if (mirror_loc, mirror_file) == (owner_loc, owner_file):
        return res
    if mirror_file != link["mirror_metadata_file"]:
        res.status = "diverged"
        res.detail = (f"{res.mirror} is at {mirror_file}, which is neither the file DataPond "
                      f"registered ({link['mirror_metadata_file']}) nor the owner's ({owner_file}): "
                      "something committed through the mirror. Left as is.")
        return res
    try:
        cur.execute(f"CALL {ident(m[0])}.system.unregister_table("
                    f"schema_name => {sql_string(m[1])}, table_name => {sql_string(m[2])})")
        cur.fetchall()
        cur.execute(f"CALL {ident(m[0])}.system.register_table("
                    f"schema_name => {sql_string(m[1])}, table_name => {sql_string(m[2])}, "
                    f"table_location => {sql_string(owner_loc)}, "
                    f"metadata_file_name => {sql_string(owner_file)})")
        cur.fetchall()
    except Exception as e:
        res.status, res.detail = "error", f"re-point failed: {str(e)[:450]}"
        return res
    res.refreshed, res.location, res.metadata_file = True, owner_loc, owner_file
    return res


_LINKS = """SELECT mirror_catalog, mirror_schema, mirror_table, owner_catalog, owner_schema,
                   owner_table, location, mirror_metadata_file, status
              FROM catalog_table_links ORDER BY mirror_catalog, mirror_schema, mirror_table"""
_UPDATE = """UPDATE catalog_table_links
                SET status = $4, detail = $5, checked_at = now(), location = $6,
                    mirror_metadata_file = $7,
                    refreshed_at = CASE WHEN $8 THEN now() ELSE refreshed_at END
              WHERE mirror_catalog = $1 AND mirror_schema = $2 AND mirror_table = $3"""
_AUDIT = """INSERT INTO auth_audit_log (event_type, resource, action, result, details)
            VALUES ('catalog_mirror_diverged', $1, 'mirror_check', 'failure', $2)"""


async def check_all(pool, cursor_factory=None) -> List[Result]:
    """One pass over every link: check, re-point what is behind, record the outcome."""
    import json
    if cursor_factory is None:
        from app.catalog_export import _cursor as cursor_factory
    async with pool.acquire() as c:
        links = [dict(r) for r in await c.fetch(_LINKS)]
    if not links:
        return []
    cur = cursor_factory()
    results = []
    for link in links:
        r = await asyncio.to_thread(check_one, cur, link)
        results.append(r)
        async with pool.acquire() as c:
            await c.execute(_UPDATE, link["mirror_catalog"], link["mirror_schema"], link["mirror_table"],
                            r.status, r.detail, r.location, r.metadata_file, r.refreshed)
            if r.status == "diverged" and link.get("status") != "diverged":
                logger.error("[mirror] %s", r.detail)
                try:
                    await c.execute(_AUDIT, r.mirror, json.dumps({"owner": r.owner, "detail": r.detail}))
                except Exception as e:
                    logger.warning("[mirror] divergence audit skipped: %s", e)
    return results


async def tick(pool) -> Optional[List[Result]]:
    """check_all under the leader lock; None when another replica holds it."""
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            return None
        try:
            return await check_all(pool)
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)


async def run(pool) -> None:
    seconds = int(os.getenv("MIRROR_CHECK_SECONDS", "300"))
    logger.info("mirror freshness checks every %ss", seconds)
    while True:
        await asyncio.sleep(seconds)
        try:
            out = await tick(pool)
            if out:
                refreshed = sum(1 for r in out if r.refreshed)
                bad = [r.mirror for r in out if r.status in ("diverged", "error")]
                if refreshed or bad:
                    logger.info("mirrors: %d re-pointed, %d need attention %s", refreshed, len(bad), bad)
        except Exception as e:          # a database before 0028, an engine restart
            logger.warning("mirror check tick error: %s", e)
