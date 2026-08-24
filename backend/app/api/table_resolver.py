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
"""
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Tuple

import sqlglot
from sqlglot import exp

from app.api.catalog_backend import get_catalog_reader

CACHE_TTL_SECONDS = 60


class TableResolutionError(Exception):
    """An unqualified table could not be resolved to exactly one namespace."""


@dataclass(frozen=True)
class CatalogIndex:
    namespaces: Tuple[str, ...]
    tables: Mapping[str, Tuple[str, ...]]  # lowercased table name -> namespaces


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


_cache = {"index": None, "at": 0.0}


def reset_catalog_index_cache() -> None:
    _cache["index"] = None
    _cache["at"] = 0.0


def get_catalog_index() -> CatalogIndex:
    """Cached catalog index. The TTL bounds how long a newly ingested table stays
    invisible to unqualified queries; qualified queries never consult this."""
    now = time.monotonic()
    if _cache["index"] is None or (now - _cache["at"]) > CACHE_TTL_SECONDS:
        _cache["index"] = build_catalog_index(get_catalog_reader())
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


def qualify_tables(sql: str, *, dialect: str, load_index: Callable[[], CatalogIndex]) -> str:
    """Rewrite bare table names to `<namespace>.<table>`.

    `load_index` is called at most once, and only when the query actually contains
    an unqualified table — a fully qualified query costs no catalog reads and is
    returned byte-for-byte unchanged.

    Raises TableResolutionError when a bare name matches zero or more than one
    namespace, with a message naming the alternatives.
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
    for _stmt, tbl in pending:
        name = tbl.name.lower()
        matches = index.tables.get(name, ())
        if len(matches) == 1:
            tbl.set("db", exp.to_identifier(matches[0]))
        elif not matches:
            available = ", ".join(index.namespaces) or "(none)"
            raise TableResolutionError(
                f"Table '{tbl.name}' was not found in the catalog. "
                f"Available namespaces: {available}. "
                f"Qualify the table as <namespace>.{tbl.name}."
            )
        else:
            candidates = ", ".join(f"{ns}.{tbl.name}" for ns in matches)
            raise TableResolutionError(
                f"Table '{tbl.name}' is ambiguous — it exists in {len(matches)} namespaces: "
                f"{candidates}. Qualify which one you mean."
            )

    return ";\n".join(stmt.sql(dialect=dialect) for stmt in statements)
