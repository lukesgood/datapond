"""Primary and foreign keys declared in source databases, and carried to their lake copies.

The relationship graph had three kinds of evidence: approved joins, joins seen in query
history, and name matches. A foreign key the source database declares is stronger than
all of them and was never read. The source catalogs are Trino catalogs (`src_<slug>`),
and Trino's `system.query` passes a statement through to the database, so the keys come
from the database's own catalog. PostgreSQL only for now: `pg_catalog` shows every
constraint to any role (information_schema.constraint_column_usage shows only tables
the role owns, which hides them from the read-only role the samples use). Other kinds
return nothing until each is checked.

A sync job copies a source table to a lake table, so a key between two synced tables is
also a key between their copies (`via: sync`). Read with the service identity like the
rest of the catalog structure; the graph's catalog filter decides who sees which edge.
"""
import logging
import time
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_TTL = 600.0
_cache: Dict[str, Tuple[float, List[dict]]] = {}

_PG = (
    # Every output column needs its own name: Trino refuses a passthrough result with two.
    "SELECT n.nspname AS ns, cl.relname AS tbl, a.attname AS col, rn.nspname AS ref_ns, "
    "rcl.relname AS ref_tbl, af.attname AS ref_col, c.contype AS kind "
    "FROM pg_constraint c "
    "JOIN pg_class cl ON cl.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = cl.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
    "LEFT JOIN pg_class rcl ON rcl.oid = c.confrelid "
    "LEFT JOIN pg_namespace rn ON rn.oid = rcl.relnamespace "
    "LEFT JOIN pg_attribute af ON af.attrelid = c.confrelid "
    "AND af.attnum = c.confkey[array_position(c.conkey, a.attnum)] "
    "WHERE c.contype IN ('p', 'f') AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
)
QUERIES = {"postgresql": _PG}


def passthrough(catalog: str, kind: str) -> Optional[str]:
    """The Trino statement that reads `catalog`'s keys, or None for a kind not read."""
    sql = QUERIES.get(kind)
    if not sql or not catalog.replace("_", "").isalnum():
        return None
    return f"SELECT * FROM TABLE({catalog}.system.query(query => '{sql.replace(chr(39), chr(39) * 2)}'))"


def parse(catalog: str, rows: Iterable[tuple]) -> List[dict]:
    """[{table, column, kind: 'pk'|'fk', ref_table, ref_column}] with tables as
    catalog.schema.table, lower case."""
    out = []
    for ns, tbl, col, rns, rtbl, rcol, contype in rows:
        key = {"table": f"{catalog}.{ns}.{tbl}".lower(), "column": str(col).lower(),
               "kind": "pk" if contype == "p" else "fk"}
        if contype == "f" and rtbl:
            key.update(ref_table=f"{catalog}.{rns}.{rtbl}".lower(), ref_column=str(rcol or "").lower())
        out.append(key)
    return out


def _read(catalog: str, kind: str) -> List[dict]:
    hit = _cache.get(catalog)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    sql = passthrough(catalog, kind)
    keys: List[dict] = []
    if sql:
        try:
            from app.api.trino_util import trino_conn
            cur = trino_conn(timeout=30).cursor()
            cur.execute(sql)
            keys = parse(catalog, cur.fetchall())
        except Exception as e:
            logger.info("[source-keys] %s: %s", catalog, str(e)[:200])
    _cache[catalog] = (time.monotonic(), keys)
    return keys


def lake_map(jobs: Iterable[dict], catalog_of: Dict[str, str], lake_catalog_of) -> Dict[str, str]:
    """source catalog.schema.table → lake catalog.namespace.table, from enabled sync jobs.
    A source table written without a schema is in `public`, as the PostgreSQL reader
    resolves it."""
    from app.flow_map import sync_target_key
    out = {}
    for j in jobs:
        src_cat = catalog_of.get(str(j["connection_id"]))
        target = sync_target_key(j["source_table"], j["target_table"])
        if not src_cat or not target:
            continue
        parts = str(j["source_table"]).lower().split(".")
        src = f"{src_cat}.{parts[-2] if len(parts) > 1 else 'public'}.{parts[-1]}"
        lake = lake_catalog_of(j.get("target_catalog"))
        if lake:
            out[src] = f"{lake}.{target}".lower()
    return out


def carry(keys: List[dict], copies: Dict[str, str]) -> List[dict]:
    """The same keys on the lake copies; a foreign key only when both ends were synced."""
    out = []
    for k in keys:
        t = copies.get(k["table"])
        if not t:
            continue
        if k["kind"] == "pk":
            out.append(dict(k, table=t, via="sync"))
        elif copies.get(k.get("ref_table", "")):
            out.append(dict(k, table=t, ref_table=copies[k["ref_table"]], via="sync"))
    return out


def fk_edges(keys: List[dict]) -> List[dict]:
    """Foreign keys as relationship-graph edges, one per table pair."""
    pairs: Dict[Tuple[str, str], dict] = {}
    for k in keys:
        if k["kind"] != "fk" or not k.get("ref_table"):
            continue
        e = pairs.setdefault((k["table"], k["ref_table"]), {
            "source": k["table"], "target": k["ref_table"], "count": 0, "evidence": "fk",
            "via": k.get("via", "source"), "joins": []})
        e["joins"].append({"left_column": k["column"], "right_column": k["ref_column"], "count": 0})
    return list(pairs.values())


def merge(graph: dict, edges: List[dict]) -> dict:
    """Add FK edges to a relationship graph. A pair people also joined keeps its count
    and becomes `fk`; a name-match guess for the pair is dropped."""
    index = {frozenset((e["source"], e["target"])): i for i, e in enumerate(graph["edges"])}
    keep = list(graph["edges"])
    drop = set()
    for e in edges:
        i = index.get(frozenset((e["source"], e["target"])))
        if i is None:
            keep.append(e)
            continue
        old = keep[i]
        if old.get("evidence") == "candidate":
            drop.add(i)
            keep.append(e)
        else:
            keep[i] = dict(old, evidence="fk", via=e["via"], fk_joins=e["joins"])
    graph["edges"] = [e for i, e in enumerate(keep) if i not in drop]
    have = {n["id"] for n in graph["nodes"]}
    for e in edges:
        for t in (e["source"], e["target"]):
            if t not in have:
                graph["nodes"].append({"id": t, "query_count": 0, "columns": []})
                have.add(t)
    return graph


async def all_keys() -> List[dict]:
    """Keys of every source catalog that can be read, plus their lake copies."""
    import asyncio
    from app import catalog_registry
    from app.api.connectors import get_db_pool
    pool = await get_db_pool()
    async with pool.acquire() as c:
        cats = await c.fetch(
            "SELECT d.engine_catalog, d.config->>'connection_id' AS cid, "
            "COALESCE(d.config->>'connector_type', cc.connector_type) AS kind "
            "FROM data_catalogs d LEFT JOIN connector_connections cc "
            "ON cc.id::text = d.config->>'connection_id' "
            "WHERE d.kind = 'trino_source' AND d.enabled")
        jobs = [dict(r) for r in await c.fetch(
            "SELECT connection_id, source_table, target_table, target_catalog "
            "FROM connector_sync_jobs WHERE enabled")]
    keys: List[dict] = []
    for r in cats:
        keys += await asyncio.to_thread(_read, r["engine_catalog"], r["kind"] or "")

    def lake_of(name):
        try:
            return catalog_registry.resolve(name).engine_catalog
        except Exception:
            return None
    copies = lake_map(jobs, {r["cid"]: r["engine_catalog"] for r in cats}, lake_of)
    # A job whose table was never written (a failing sync) has no copy to carry keys to.
    present = await asyncio.to_thread(_existing, {t.split(".", 1)[0] for t in copies.values()})
    if present is not None:
        copies = {s: t for s, t in copies.items() if t in present}
    return keys + carry(keys, copies)


_tables_cache: Dict[str, Tuple[float, set]] = {}


def _existing(catalogs: set) -> Optional[set]:
    """catalog.namespace.table of every table in these lake catalogs; None when they
    cannot be listed (then nothing is dropped rather than everything)."""
    from app.api.trino_util import trino_conn
    out = set()
    try:
        for cat in sorted(catalogs):
            hit = _tables_cache.get(cat)
            if hit and time.monotonic() - hit[0] < _TTL:
                out |= hit[1]
                continue
            cur = trino_conn(timeout=30).cursor()
            cur.execute(f'SELECT table_schema, table_name FROM "{cat}".information_schema.tables '
                        "WHERE table_schema <> 'information_schema'")
            names = {f"{cat}.{ns}.{t}".lower() for ns, t in cur.fetchall()}
            _tables_cache[cat] = (time.monotonic(), names)
            out |= names
        return out
    except Exception as e:
        logger.info("[source-keys] lake tables not listed: %s", e)
        return None


def for_table(keys: List[dict], table: str) -> dict:
    """{primary: [columns], foreign: [{column, ref_table, ref_column, via}]} for one
    catalog.namespace.table."""
    t = table.lower()
    mine = [k for k in keys if k["table"] == t]
    return {"primary": sorted({k["column"] for k in mine if k["kind"] == "pk"}),
            "foreign": [{"column": k["column"], "ref_table": k["ref_table"], "ref_column": k["ref_column"],
                         "via": k.get("via", "source")} for k in mine if k["kind"] == "fk"],
            "referenced_by": [{"table": k["table"], "column": k["column"], "ref_column": k["ref_column"]}
                              for k in keys if k["kind"] == "fk" and k.get("ref_table") == t]}
