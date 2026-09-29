"""Which data catalogs DataPond reads, and how a table is named across them.

The `data_catalogs` table (migration 0018) is the source of truth. Until it has a row
— a fresh install before startup seeded it, a database that cannot be reached, a unit
test — the registry is one entry derived from today's env, so a single-catalog
deployment behaves exactly as it did before the registry existed.

Reads are synchronous and never do IO: the catalog readers, the table resolver and the
RLS engine run on request threads and inside `asyncio.to_thread`. The database is read
by `load()` — at startup and on a short interval by `run_refresher()` — and the rows it
returns are what every synchronous caller sees. A database that stops answering keeps
the last rows it gave, rather than falling back to env mid-flight and changing what a
two-part table name means.

A catalog's `name` is the registry key; `engine_catalog` is what the query engine calls
it and what SQL carries. For the default entry the two are the same value — the one
`rls_policies.catalog_name` already stores — and `resolve()` accepts either.
"""
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

KINDS = ("glue", "iceberg_rest", "polaris")
CACHE_TTL_SECONDS = 30

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


class UnknownCatalog(ValueError):
    """A catalog name that is not an enabled registry entry."""


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    kind: str
    engine_catalog: str
    config: dict = field(default_factory=dict, compare=False, hash=False)
    secret_ref: Optional[str] = None
    is_default: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class TableRef:
    """One table, named the way the engine names it: catalog.namespace.table.

    A bare name parses to catalog=None, namespace=None — the table resolver decides
    which catalog and namespace it means, and refuses when it could mean several.
    Two parts mean the default catalog.
    """
    catalog: Optional[str]
    namespace: Optional[str]
    table: str

    @classmethod
    def parse(cls, text: str, default: Optional[str] = None) -> "TableRef":
        parts = str(text or "").strip().split(".")
        if not 1 <= len(parts) <= 3 or not all(_IDENT.match(p or "") for p in parts):
            raise ValueError(
                f"Not a table name: {text!r} — expected table, namespace.table or "
                f"catalog.namespace.table, each a bare identifier.")
        if len(parts) == 1:
            return cls(None, None, parts[0])
        if len(parts) == 2:
            return cls(default or default_entry().engine_catalog, parts[0], parts[1])
        return cls(parts[0], parts[1], parts[2])

    def sql(self) -> str:
        return ".".join(p for p in (self.catalog, self.namespace, self.table) if p)

    def key(self) -> str:
        return self.sql().lower()


# ── the env-derived default ──────────────────────────────────────────────────

def env_default_entry() -> CatalogEntry:
    """The one catalog today's env describes. Computed on every call — tests and
    Settings change env at runtime, and this costs nothing."""
    backend = os.getenv("ICEBERG_CATALOG_BACKEND", "polaris").strip().lower()
    # The engine names the catalog. An unset QUERY_ENGINE on the glue backend is the
    # Athena reference (Helm derives one from the other).
    engine = (os.getenv("QUERY_ENGINE") or ("athena" if backend == "glue" else "trino"))
    if engine.strip().lower() == "athena":
        name = "AwsDataCatalog"
    else:
        name = (os.getenv("TRINO_CATALOG") or "iceberg").strip() or "iceberg"
    if backend == "glue":
        config = {"warehouse": os.getenv("GLUE_WAREHOUSE", "")}
        region = os.getenv("S3_REGION")
        if region:
            config["region"] = region
        kind = "glue"
    else:
        # The Polaris catalog this entry lists. Other Polaris catalogs are other rows.
        config = {"warehouse": os.getenv("POLARIS_WAREHOUSE", "iceberg") or "iceberg"}
        uri = os.getenv("POLARIS_URI")
        if uri:
            config["uri"] = uri
        kind = "polaris"
    return CatalogEntry(name=name, kind=kind, engine_catalog=name, config=config,
                        is_default=True, enabled=True)


# ── the cache ────────────────────────────────────────────────────────────────

_state = {"entries": None, "at": 0.0}


def reset() -> None:
    """Forget what the database said; the env default stands in again."""
    _state["entries"] = None
    _state["at"] = 0.0


def set_entries(entries: List[CatalogEntry]) -> None:
    """Install rows as if the database had returned them (load() and tests)."""
    _state["entries"] = list(entries) if entries else None
    _state["at"] = time.monotonic()


def entries(include_disabled: bool = False) -> List[CatalogEntry]:
    rows = _state["entries"]
    if not rows:
        return [env_default_entry()]
    return [e for e in rows if include_disabled or e.enabled]


def default_entry() -> CatalogEntry:
    enabled = entries()
    for e in enabled:
        if e.is_default:
            return e
    return enabled[0] if enabled else env_default_entry()


def cached_default_name() -> Optional[str]:
    """The default entry's SQL name, only when the database supplied it. None means
    "not known" — the caller keeps its own env fallback. Never does IO."""
    if not _state["entries"]:
        return None
    return default_entry().engine_catalog


def resolve(name: Optional[str] = None) -> CatalogEntry:
    """The enabled entry `name` refers to — by registry name or engine catalog name,
    case-insensitively (SQL identifiers are). None or "" is the default."""
    if name is None or str(name).strip() == "":
        return default_entry()
    wanted = str(name).strip()
    if not _IDENT.match(wanted):
        raise UnknownCatalog(f"Not a catalog name: {name!r}")
    low = wanted.lower()
    enabled = entries()
    for e in enabled:
        if e.name.lower() == low:
            return e
    for e in enabled:
        if e.engine_catalog.lower() == low:
            return e
    known = ", ".join(e.name for e in enabled) or "(none)"
    raise UnknownCatalog(f"Unknown catalog '{wanted}'. Known catalogs: {known}.")


def is_default(name: Optional[str]) -> bool:
    """True when `name` is empty or refers to the default entry."""
    if name is None or str(name).strip() == "":
        return True
    d = default_entry()
    low = str(name).strip().lower()
    return low in (d.name.lower(), d.engine_catalog.lower())


# ── the database ─────────────────────────────────────────────────────────────

_SELECT = """SELECT name, kind, engine_catalog, config, secret_ref, is_default, enabled
               FROM data_catalogs
              ORDER BY is_default DESC, name"""


def _row_to_entry(r) -> CatalogEntry:
    cfg = r["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg or "{}")
    return CatalogEntry(name=r["name"], kind=r["kind"], engine_catalog=r["engine_catalog"],
                        config=dict(cfg or {}), secret_ref=r["secret_ref"],
                        is_default=bool(r["is_default"]), enabled=bool(r["enabled"]))


async def load(pool, *, force: bool = False, timeout: float = 5.0) -> List[CatalogEntry]:
    """Read the registry from the database when the cache is stale (or `force`).

    Never raises. An empty table leaves the env default in place; an unreachable
    database keeps whatever rows were last read.
    """
    fresh = _state["entries"] is not None and \
        (time.monotonic() - _state["at"]) < CACHE_TTL_SECONDS
    if fresh and not force:
        return entries()
    try:
        async def _fetch():
            async with pool.acquire() as c:
                return await c.fetch(_SELECT)
        rows = await asyncio.wait_for(_fetch(), timeout=timeout)
        set_entries([_row_to_entry(r) for r in rows])
    except Exception as e:
        logger.warning("[catalogs] registry read failed, keeping %s: %s",
                       "last rows" if _state["entries"] else "env default", e)
    return entries()


_SEED = """INSERT INTO data_catalogs (name, kind, engine_catalog, config, is_default, enabled)
           SELECT $1, $2, $3, $4::jsonb, true, true
            WHERE NOT EXISTS (SELECT 1 FROM data_catalogs)
           ON CONFLICT DO NOTHING"""


async def seed_from_env(pool) -> None:
    """Write the env default as the first row of an empty registry. Idempotent: a
    registry with any row — including one an admin edited — is left alone."""
    e = env_default_entry()
    async with pool.acquire() as c:
        await c.execute(_SEED, e.name, e.kind, e.engine_catalog, json.dumps(e.config))


async def run_refresher(pool, interval: float = CACHE_TTL_SECONDS) -> None:
    """Keep the cache within one interval of the table. Runs for the process lifetime."""
    while True:
        await load(pool, force=True)
        await asyncio.sleep(interval)
