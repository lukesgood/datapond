"""Resolve unqualified table references against the catalog, before execution.

`SELECT * FROM orders` is ambiguous to us in two different ways, and they are not
equally harmless:

1. The engine resolves it against its *session* database (`ATHENA_DATABASE` for
   Athena), which is a single static value and usually not the namespace the table
   actually lives in — so the query fails even though the table exists.
2. RLS keys policies on the fully qualified name (`app/rls/engine.py:_qualify`,
   which falls back to `RLS_DEFAULT_SCHEMA`). If that fallback and the engine's
   session database disagree, a policy on `sales.orders` does not match a query
   that says `FROM orders` — and with `RLS_DEFAULT_DENY` off (the default) the
   query then runs unfiltered.

Qualifying here, *before* `enforce()`, closes both. The resolution is fail-closed:
if the catalog cannot be read we raise rather than hand an unqualified query to the
engine, because that is exactly the case (2) above.

Engine-neutral by construction — the namespace list comes from the configured
`CatalogReader` (Glue or Polaris), not from the query engine.

Several catalogs (app/catalog_registry.py): the index spans every enabled one. A bare
name found only in the default catalog is rewritten to `<namespace>.<table>` exactly
as before — the default catalog is the engine's session catalog. Found only in another
catalog, it becomes `<catalog>.<namespace>.<table>`, because two parts would execute
against the default catalog and key RLS on the wrong table. Found in more than one
(catalog, namespace), it is an error naming each candidate in full.
"""
import logging
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple, Union

import sqlglot
from sqlglot import exp

from app.api.catalog_backend import get_catalog_reader

CACHE_TTL_SECONDS = 60


class TableResolutionError(Exception):
    """An unqualified table could not be resolved to exactly one namespace."""


logger = logging.getLogger(__name__)

# Where a bare name was found: a namespace string means the default catalog; a
# (catalog, namespace) pair means another one.
Location = Union[str, Tuple[str, str]]


@dataclass(frozen=True)
class CatalogIndex:
    namespaces: Tuple[str, ...]            # "ns" (default catalog) or "catalog.ns"
    tables: Mapping[str, Tuple[Location, ...]]  # lowercased table name -> locations
    default_catalog: Optional[str] = None  # engine name of the default catalog


def build_catalog_index(reader) -> CatalogIndex:
    """Index every table the catalog can see by (lowercased) bare name.

    A namespace whose table list fails is skipped rather than fatal — one broken
    namespace must not make every unqualified query unresolvable.
    """
    namespaces = tuple(reader.list_namespaces())
    tables = {}
    for ns in namespaces:
        try:
            names = reader.list_tables(ns)
        except Exception:
            continue
        for name in names:
            tables.setdefault(name.lower(), []).append(ns)
    return CatalogIndex(namespaces=namespaces,
                        tables={k: tuple(v) for k, v in tables.items()})


def build_multi_catalog_index(readers) -> CatalogIndex:
    """Index every enabled catalog. `readers` is [(entry, reader)]; the default
    entry's locations are plain namespaces so single-catalog output is unchanged.

    A catalog that cannot be listed is skipped, like a namespace that cannot: the
    others stay resolvable, and a name that lived only there reports "not found"."""
    default = None
    namespaces, tables = [], {}
    for entry, reader in readers:
        cat = entry.engine_catalog
        if entry.is_default:
            default = cat
        try:
            sub = build_catalog_index(reader)
        except Exception as e:
            logger.warning("[resolver] catalog %s unreadable: %s", entry.name, e)
            continue
        for ns in sub.namespaces:
            namespaces.append(ns if entry.is_default else f"{cat}.{ns}")
        for name, nss in sub.tables.items():
            tables.setdefault(name, []).extend(
                ns if entry.is_default else (cat, ns) for ns in nss)
    return CatalogIndex(namespaces=tuple(namespaces),
                        tables={k: tuple(v) for k, v in tables.items()},
                        default_catalog=default)


def _registry_readers():
    from app.catalog_registry import entries
    out = []
    for entry in entries():
        try:
            out.append((entry, get_catalog_reader(entry.name)))
        except Exception as e:
            logger.warning("[resolver] no reader for catalog %s: %s", entry.name, e)
    return out


_cache = {"index": None, "at": 0.0}


def reset_catalog_index_cache() -> None:
    _cache["index"] = None
    _cache["at"] = 0.0


def get_catalog_index() -> CatalogIndex:
    """Cached catalog index. The TTL bounds how long a newly ingested table stays
    invisible to unqualified queries; qualified queries never consult this."""
    now = time.monotonic()
    if _cache["index"] is None or (now - _cache["at"]) > CACHE_TTL_SECONDS:
        _cache["index"] = build_multi_catalog_index(_registry_readers())
        _cache["at"] = now
    return _cache["index"]


def _cte_names(statements) -> set:
    """Aliases bound by WITH — never table references to resolve.

    Collected per statement rather than per scope: a real table shadowed by a
    same-named CTE elsewhere in the query is left unqualified (the engine then
    reports it), which is the safe direction to err.
    """
    names = set()
    for stmt in statements:
        for cte in stmt.find_all(exp.CTE):
            if cte.alias:
                names.add(cte.alias.lower())
    return names


# Only these parents are *read* references. An allowlist, not a DDL denylist: a
# statement shape we do not recognise is left untouched rather than resolved by
# accident. `execute_query` also accepts CREATE / DROP / ALTER, where the table need
# not exist yet — and silently redirecting a DROP to a namespace the user never
# named would be destructive.
_READ_PARENTS = (exp.From, exp.Join)


def _unqualified(stmt, cte_names):
    for tbl in stmt.find_all(exp.Table):
        if tbl.db or tbl.catalog:
            continue
        if not isinstance(tbl.parent, _READ_PARENTS):
            continue
        if not isinstance(tbl.this, exp.Identifier):
            continue  # table function / UNNEST — not a catalog table
        if tbl.name.lower() in cte_names:
            continue
        yield tbl


def _split(location: Location, default: Optional[str]):
    """(catalog to write, namespace). The catalog is None for the default catalog, so
    single-catalog SQL keeps its two-part output."""
    if isinstance(location, tuple):
        catalog, ns = location
        if default is not None and catalog.lower() == default.lower():
            return None, ns
        return catalog, ns
    return None, location


def _full(location: Location, default: Optional[str], table: str) -> str:
    if isinstance(location, tuple):
        return f"{location[0]}.{location[1]}.{table}"
    return f"{default}.{location}.{table}" if default else f"{location}.{table}"


def _location_catalog(location: Location, default: Optional[str]) -> Optional[str]:
    return location[0] if isinstance(location, tuple) else default


def _namespace_catalog(namespace: str, default: Optional[str]) -> Optional[str]:
    """Index namespaces are "ns" in the default catalog and "catalog.ns" elsewhere."""
    return namespace.split(".", 1)[0] if "." in namespace else default


def qualify_tables(sql: str, *, dialect: str, load_index: Callable[[], CatalogIndex],
                   catalog_allowed: Optional[Callable[[Optional[str]], bool]] = None) -> str:
    """Rewrite bare table names to `<namespace>.<table>` — or
    `<catalog>.<namespace>.<table>` when the table lives outside the default catalog.

    `load_index` is called at most once, and only when the query actually contains
    an unqualified table — a fully qualified query costs no catalog reads and is
    returned byte-for-byte unchanged.

    Raises TableResolutionError when a bare name matches zero or more than one
    namespace, with a message naming the alternatives.

    `catalog_allowed` (app/catalog_access.py) takes the engine name of a catalog and
    says whether this caller may use it. The index is global and cached; the caller's
    view is applied here, at lookup: a table in a catalog the caller may not use is
    neither matched nor named as a candidate or an available namespace — a bare name
    that exists only there is "not found".
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return sql  # unparseable — the engine (or RLS default-deny) reports it

    cte_names = _cte_names(statements)
    pending = [(stmt, tbl) for stmt in statements for tbl in _unqualified(stmt, cte_names)]
    if not pending:
        return sql

    index = load_index()
    default = getattr(index, "default_catalog", None)
    allowed = catalog_allowed or (lambda _catalog: True)
    visible_namespaces = [ns for ns in index.namespaces
                          if allowed(_namespace_catalog(ns, default))]
    for _stmt, tbl in pending:
        name = tbl.name.lower()
        matches = [m for m in index.tables.get(name, ())
                   if allowed(_location_catalog(m, default))]
        if len(matches) == 1:
            catalog, ns = _split(matches[0], default)
            tbl.set("db", exp.to_identifier(ns))
            if catalog is not None:
                tbl.set("catalog", exp.to_identifier(catalog))
        elif not matches:
            available = ", ".join(visible_namespaces) or "(none)"
            raise TableResolutionError(
                f"Table '{tbl.name}' was not found in the catalog. "
                f"Available namespaces: {available}. "
                f"Qualify the table as <namespace>.{tbl.name}."
            )
        else:
            candidates = ", ".join(_full(m, default, tbl.name) for m in matches)
            raise TableResolutionError(
                f"Table '{tbl.name}' is ambiguous — it exists in {len(matches)} namespaces: "
                f"{candidates}. Qualify which one you mean."
            )

    return ";\n".join(stmt.sql(dialect=dialect) for stmt in statements)
