"""One writer per table when two catalogs see the same Iceberg table.

The catalog export (app/catalog_export.py) registers a table of one catalog in another
without copying data. The table is then visible in two catalogs: its **owner**, through
which it is written, and a **mirror**. Iceberg records each commit through one catalog,
so a write through the mirror forks the table; a DROP through a Polaris mirror (which
purges on drop) deletes the owner's files; and a read of the mirror returns an old
snapshot under the mirror catalog's grants and policies.

Inside DataPond the rule is enforced on every statement `/queries/execute` runs:

- **writes** (INSERT, UPDATE, DELETE, MERGE, CREATE … AS, ALTER, DROP, TRUNCATE) whose
  target is a mirror are refused, naming the owner to write to instead;
- **reads** of a mirror are rewritten to the owner table, so the owner's catalog grant,
  row filters and masks apply and the data is current.

Writers outside DataPond (Athena, EMR, Spark on the same catalog) cannot be refused
here; app/mirror_freshness.py detects their commits on a mirror.

The links live in `catalog_table_links` (migration 0028) and are cached per process for
CACHE_TTL_SECONDS, like the catalog registry.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

Key = Tuple[str, str, str]
CACHE_TTL_SECONDS = 30


class MirrorWriteRefused(Exception):
    def __init__(self, mirror: Key, owner: Key):
        self.mirror, self.owner = mirror, owner
        super().__init__(
            f"{'.'.join(mirror)} is a read-only mirror of {'.'.join(owner)}: it is written "
            f"through its owner catalog only. Write to {'.'.join(owner)} instead.")


def _key(catalog, schema, table) -> Key:
    return (str(catalog or "").lower(), str(schema or "").lower(), str(table or "").lower())


@dataclass(frozen=True)
class Links:
    owners: Dict[Key, Key] = field(default_factory=dict)    # mirror → owner

    @classmethod
    def from_rows(cls, rows: Iterable[dict]) -> "Links":
        return cls({_key(r["mirror_catalog"], r["mirror_schema"], r["mirror_table"]):
                    _key(r["owner_catalog"], r["owner_schema"], r["owner_table"]) for r in rows})

    def owner_of(self, key: Key) -> Optional[Key]:
        return self.owners.get(key)

    def __bool__(self):
        return bool(self.owners)


def _table_key(tbl, default_catalog: str) -> Key:
    return _key(tbl.catalog or default_catalog, tbl.db, tbl.name)


def _targets_of(stmt) -> list:
    """The exp.Table nodes a statement changes."""
    from sqlglot import exp
    if isinstance(stmt, exp.TruncateTable):
        return [t for t in stmt.expressions if isinstance(t, exp.Table)]
    if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter)):
        target = stmt.this
        if isinstance(target, exp.Schema):
            target = target.this
        return [target] if isinstance(target, exp.Table) else []
    return []


def write_targets(sql: str, dialect: str, default_catalog: str) -> List[Key]:
    import sqlglot
    out: List[Key] = []
    for stmt in sqlglot.parse(sql, read=dialect):
        if stmt is None:
            continue
        out.extend(_table_key(t, default_catalog) for t in _targets_of(stmt))
    return out


def _mentions_a_mirror(sql: str, links: Links) -> Optional[Key]:
    """Fallback for a statement sqlglot cannot parse: any mirror's dotted name in the
    text, quotes ignored. Fail closed — the statement may be a write."""
    flat = re.sub(r'["`\s]', "", sql).lower()
    for mirror in links.owners:
        if ".".join(mirror) in flat:
            return mirror
    return None


def check_writes(sql: str, dialect: str, links: Links, default_catalog: str) -> None:
    """Raise MirrorWriteRefused if the statement changes a mirror table."""
    if not links:
        return
    try:
        targets = write_targets(sql, dialect, default_catalog)
    except Exception:
        hit = _mentions_a_mirror(sql, links)
        if hit:
            raise MirrorWriteRefused(hit, links.owner_of(hit))
        return
    for t in targets:
        owner = links.owner_of(t)
        if owner:
            raise MirrorWriteRefused(t, owner)


def route_reads(sql: str, dialect: str, links: Links, default_catalog: str) -> str:
    """The statement with every mirror table replaced by its owner. Returned unchanged
    (the same object) when it names no mirror."""
    if not links:
        return sql
    import sqlglot
    from sqlglot import exp
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return sql
    changed = False
    for stmt in statements:
        for tbl in stmt.find_all(exp.Table):
            owner = links.owner_of(_table_key(tbl, default_catalog))
            if owner:
                tbl.set("catalog", exp.to_identifier(owner[0]))
                tbl.set("db", exp.to_identifier(owner[1]))
                tbl.set("this", exp.to_identifier(owner[2]))
                changed = True
    if not changed:
        return sql
    return ";\n".join(s.sql(dialect=dialect) for s in statements)


# ── per-process cache ────────────────────────────────────────────────────────

_state = {"links": Links(), "at": 0.0}

_SELECT = """SELECT mirror_catalog, mirror_schema, mirror_table,
                    owner_catalog, owner_schema, owner_table
               FROM catalog_table_links"""


def current() -> Links:
    return _state["links"]


def set_links(links: Links) -> None:
    _state["links"], _state["at"] = links, time.monotonic()


def invalidate() -> None:
    _state["at"] = 0.0


async def load(pool, force: bool = False) -> Links:
    """The links, from the database at most every CACHE_TTL_SECONDS. A database before
    migration 0028 has no links: nothing is a mirror."""
    if not force and _state["at"] and time.monotonic() - _state["at"] < CACHE_TTL_SECONDS:
        return _state["links"]
    try:
        async with pool.acquire() as c:
            rows = await c.fetch(_SELECT)
        set_links(Links.from_rows(rows))
    except Exception as e:
        msg = str(e)
        if "catalog_table_links" in msg and "does not exist" in msg:
            set_links(Links())
        else:
            # Keep the last good set: dropping the guards on a transient error would
            # let a mirror write through.
            logger.warning("[table-links] not refreshed, keeping %d link(s): %s",
                           len(_state["links"].owners), e)
    return _state["links"]
