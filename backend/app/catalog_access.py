"""Which data catalogs a caller may use (multi-catalog P3).

`catalog_grants` (migration 0021) names, per catalog, the users and roles that may use
it. The rule:

- A catalog with **no grants** is open to every caller that already passes today's
  checks (`catalog:read`, `query:run`, collection ACL, RLS). A deployment that never
  grants anything behaves exactly as it did before this table existed.
- A catalog with **one grant or more** is visible and queryable only to a signed-in
  administrator, a user granted directly (a service account is a user), and a user
  whose role is granted.

"Signed-in administrator" is deliberate. A delegated credential — a service-account
key or an IdP access token (`is_delegated_credential`) — on an admin account is not
exempt: its account's grants decide, like anyone else's. A credential that lives in a
config file must not see every catalog because of the role its account happens to hold.

A hidden catalog is indistinguishable from an unknown one: listings leave it out,
detail routes answer 404 with the unknown-catalog message, the table resolver never
matches a bare name in it, and the "known catalogs" list in an error names only the
catalogs the caller may use.

Failure is closed. Grants that cannot be read make every catalog hidden to every
caller except a signed-in administrator — except when the table does not exist yet
(a database behind migration 0021), which means no grants, which means open.

Grants are read at most every GRANTS_TTL_SECONDS per replica; a change through the
admin API invalidates this replica at once.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Mapping, Optional, Set, Tuple

from app import catalog_registry

logger = logging.getLogger(__name__)

GRANTS_TTL_SECONDS = 30
PRINCIPAL_KINDS = ("user", "role")

Grant = Tuple[str, str]          # (principal_kind, principal)

_state: dict = {"grants": None, "at": 0.0}


class GrantsUnavailable(RuntimeError):
    """The grants table exists (or may) and could not be read."""


# ── the cache ────────────────────────────────────────────────────────────────

def _normalise(kind: str, principal: str) -> Grant:
    kind = str(kind or "").strip().lower()
    principal = str(principal or "").strip()
    # A user id is a uuid, compared case-insensitively; a role name is exact.
    return (kind, principal.lower() if kind == "user" else principal)


def set_grants(mapping: Mapping[str, Iterable[Grant]]) -> None:
    """Install grants as if the database had returned them (load and tests)."""
    grants: Dict[str, FrozenSet[Grant]] = {}
    for name, rows in (mapping or {}).items():
        items = frozenset(_normalise(k, p) for k, p in rows)
        if items:
            grants[str(name).lower()] = items
    _state["grants"] = grants
    _state["at"] = time.monotonic()


def reset() -> None:
    """Forget what the database said; the next caller reads it again."""
    _state["grants"] = None
    _state["at"] = 0.0


invalidate = reset


def _missing_table(exc: BaseException) -> bool:
    return (getattr(exc, "sqlstate", None) == "42P01"
            or type(exc).__name__ == "UndefinedTableError")


_SELECT = "SELECT catalog_name, principal_kind, principal FROM catalog_grants"


async def _pool():
    from app.api.connectors import get_db_pool
    return await get_db_pool()


async def load_grants(*, force: bool = False, timeout: float = 3.0) -> Dict[str, FrozenSet[Grant]]:
    """{lowercased catalog name: grants}. Raises GrantsUnavailable when the table
    cannot be read; a missing table is no grants."""
    fresh = _state["grants"] is not None and \
        (time.monotonic() - _state["at"]) < GRANTS_TTL_SECONDS
    if fresh and not force:
        return _state["grants"]
    try:
        pool = await _pool()

        async def _fetch():
            async with pool.acquire() as c:
                return await c.fetch(_SELECT)
        rows = await asyncio.wait_for(_fetch(), timeout=timeout)
    except Exception as e:
        if _missing_table(e):
            set_grants({})
            return _state["grants"]
        # Not cached: the next request tries again rather than staying closed for a TTL.
        raise GrantsUnavailable(str(e)) from e
    mapping: Dict[str, list] = {}
    for r in rows:
        mapping.setdefault(r["catalog_name"], []).append((r["principal_kind"], r["principal"]))
    set_grants(mapping)
    return _state["grants"]


# ── one caller's view ────────────────────────────────────────────────────────

def is_exempt(user: Optional[dict]) -> bool:
    """A signed-in administrator (or the scoped internal automation principal) sees
    every catalog. A delegated credential on an admin account does not."""
    from app.api.auth import is_delegated_credential
    user = user or {}
    return user.get("role") == "admin" and not is_delegated_credential(user)


def unknown_message(name, visible) -> str:
    known = ", ".join(e.name for e in visible) or "(none)"
    return f"Unknown catalog '{str(name).strip()}'. Known catalogs: {known}."


@dataclass(frozen=True)
class CatalogAccess:
    """What one caller may use. `grants=None` on a non-exempt caller means the grants
    could not be read: nothing is allowed."""
    exempt: bool = False
    grants: Optional[Mapping[str, FrozenSet[Grant]]] = None
    user_id: Optional[str] = None
    role: Optional[str] = None

    def allows(self, entry) -> bool:
        """`entry` is a CatalogEntry or a registry name."""
        if self.exempt:
            return True
        if self.grants is None:
            return False
        name = entry if isinstance(entry, str) else entry.name
        granted = self.grants.get(str(name).lower())
        if not granted:
            return True
        if self.user_id and ("user", self.user_id.lower()) in granted:
            return True
        return bool(self.role) and ("role", self.role) in granted

    def entries(self, include_disabled: bool = False):
        return [e for e in catalog_registry.entries(include_disabled=include_disabled)
                if self.allows(e)]

    def resolve(self, name=None):
        """catalog_registry.resolve, but a hidden catalog is an unknown one and the
        known list names only what this caller may use."""
        try:
            entry = catalog_registry.resolve(name)
        except catalog_registry.UnknownCatalog as e:
            if not str(e).startswith("Unknown catalog"):
                raise                        # "Not a catalog name" — says nothing
            entry = None
        if entry is None or not self.allows(entry):
            shown = name if name not in (None, "") else (entry.name if entry else "")
            raise catalog_registry.UnknownCatalog(unknown_message(shown, self.entries()))
        return entry

    def hidden_sql_names(self) -> Set[str]:
        """Every name SQL could use for a catalog this caller may not use (lowercased),
        disabled entries included — the engine still knows those."""
        if self.exempt:
            return set()
        out = set()
        for e in catalog_registry.entries(include_disabled=True):
            if not self.allows(e):
                out |= {e.name.lower(), e.engine_catalog.lower()}
        return out

    def allows_sql_catalog(self, name: Optional[str]) -> bool:
        """Whether a catalog as SQL names it may be used. None is the default. A name
        no registry entry answers to is not governed here (the engine decides)."""
        if self.exempt:
            return True
        if name is None or str(name).strip() == "":
            name = catalog_registry.default_entry().engine_catalog
        return str(name).strip().lower() not in self.hidden_sql_names()


EVERYTHING = CatalogAccess(exempt=True)


async def for_caller(user: Optional[dict]) -> CatalogAccess:
    if is_exempt(user):
        return EVERYTHING
    try:
        grants = await load_grants()
    except Exception as e:
        logger.warning("[catalog_access] grants unreadable, hiding restricted catalogs: %s", e)
        grants = None
    user = user or {}
    return CatalogAccess(grants=grants, user_id=str(user.get("id") or "") or None,
                         role=user.get("role"))


# ── statements ───────────────────────────────────────────────────────────────

def referenced_catalogs(sql: str, dialect: str) -> Optional[Set[str]]:
    """Lowercased catalog of every table the statement names — a two- or one-part
    name is the default catalog. None when the statement cannot be parsed."""
    import sqlglot
    from sqlglot import exp
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return None
    ctes = set()
    for stmt in statements:
        for cte in stmt.find_all(exp.CTE):
            if cte.alias:
                ctes.add(cte.alias.lower())
    default = catalog_registry.default_entry().engine_catalog.lower()
    out = set()
    for stmt in statements:
        for tbl in stmt.find_all(exp.Table):
            if not isinstance(tbl.this, exp.Identifier):
                continue                     # table function / UNNEST
            if not tbl.db and not tbl.catalog and tbl.name.lower() in ctes:
                continue
            out.add((tbl.catalog or default).lower())
    return out


def statement_uses_hidden(access: CatalogAccess, sql: str, dialect: str) -> bool:
    """True when the statement names a catalog this caller may not use, or could read
    one's metadata. A caller with nothing hidden pays no parse. For one with something
    hidden, three more shapes are refused, because each can list a hidden catalog's
    tables without naming a table the parser sees:

    - a statement that cannot be parsed (what it reads cannot be known);
    - a metadata command the parser keeps as opaque text (SHOW TABLES/SCHEMAS/CREATE,
      USE, and the like — sqlglot returns them as Command/Use with no table nodes);
    - a catalog no registry entry answers to, `system` included: Trino's
      system.jdbc.tables and system.metadata.* list every catalog's tables.
    """
    hidden = access.hidden_sql_names()
    if not hidden:
        return False
    import sqlglot
    from sqlglot import exp
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return True
    if any(isinstance(s, (exp.Command, exp.Use)) for s in statements):
        return True
    cats = referenced_catalogs(sql, dialect)
    if cats is None:
        return True
    known = set()
    for e in catalog_registry.entries(include_disabled=True):
        known |= {e.name.lower(), e.engine_catalog.lower()}
    return bool(cats & hidden) or bool(cats - known)


def hidden_reason(access: CatalogAccess, sql: str, dialect: str) -> str:
    """Why `statement_uses_hidden` refused this statement, naming the catalog — for
    the security audit row only, which auditors read. Never put it in a response: the
    caller may not know the catalog exists."""
    import sqlglot
    from sqlglot import exp
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return "a statement that could not be parsed"
    if any(isinstance(s, (exp.Command, exp.Use)) for s in statements):
        return "a metadata command while a catalog is hidden"
    cats = referenced_catalogs(sql, dialect)
    if cats is None:
        return "a statement that could not be parsed"
    hidden = access.hidden_sql_names()
    known = set()
    for e in catalog_registry.entries(include_disabled=True):
        known |= {e.name.lower(), e.engine_catalog.lower()}
    parts = []
    if cats & hidden:
        parts.append("hidden catalog " + ", ".join(sorted(cats & hidden)))
    if cats - known:
        parts.append("catalog outside the registry " + ", ".join(sorted(cats - known)))
    return "; ".join(parts)
