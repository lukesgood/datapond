"""Unqualified table references must be resolved against the catalog before
execution — and before RLS enforcement, which keys policies on the fully
qualified name (see app/rls/engine.py:_qualify).
"""
import pytest

from app.api.table_resolver import (
    CatalogIndex,
    TableResolutionError,
    build_catalog_index,
    qualify_tables,
)


def _index(tables, namespaces=None):
    """CatalogIndex from {table: [namespace, ...]}."""
    if namespaces is None:
        namespaces = sorted({ns for nss in tables.values() for ns in nss})
    return CatalogIndex(
        namespaces=tuple(namespaces),
        tables={t: tuple(nss) for t, nss in tables.items()},
    )


class _Loader:
    """Zero-arg index provider that records how often it was called."""

    def __init__(self, index):
        self.index = index
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.index


def test_qualifies_a_unique_table_name():
    loader = _Loader(_index({"orders": ["sales"]}))

    out = qualify_tables("SELECT * FROM orders", dialect="athena", load_index=loader)

    assert out == "SELECT * FROM sales.orders"


def test_leaves_already_qualified_sql_byte_identical():
    loader = _Loader(_index({"orders": ["sales"]}))
    sql = "SELECT  id,\n  amt\nFROM sales.orders  -- keep formatting"

    assert qualify_tables(sql, dialect="athena", load_index=loader) == sql
    assert loader.calls == 0, "catalog must not be read for a fully qualified query"


def test_ambiguous_table_names_the_candidates():
    loader = _Loader(_index({"orders": ["ops", "sales"]}))

    with pytest.raises(TableResolutionError) as ei:
        qualify_tables("SELECT * FROM orders", dialect="athena", load_index=loader)

    msg = str(ei.value)
    assert "orders" in msg and "ops" in msg and "sales" in msg


def test_unknown_table_lists_available_namespaces():
    loader = _Loader(_index({"orders": ["sales"]}, namespaces=["ops", "sales"]))

    with pytest.raises(TableResolutionError) as ei:
        qualify_tables("SELECT * FROM widgets", dialect="athena", load_index=loader)

    msg = str(ei.value)
    assert "widgets" in msg and "ops" in msg and "sales" in msg


def test_qualifies_tables_in_joins_and_subqueries():
    loader = _Loader(_index({"orders": ["sales"], "regions": ["ref"]}))

    out = qualify_tables(
        "SELECT * FROM orders o JOIN (SELECT * FROM regions) r ON o.rid = r.id",
        dialect="athena",
        load_index=loader,
    )

    assert "sales.orders" in out and "ref.regions" in out


def test_does_not_qualify_cte_names():
    loader = _Loader(_index({"orders": ["sales"]}))

    out = qualify_tables(
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
        dialect="athena",
        load_index=loader,
    )

    assert "sales.orders" in out
    assert "sales.recent" not in out


def test_loads_the_index_at_most_once():
    loader = _Loader(_index({"orders": ["sales"], "regions": ["ref"]}))

    qualify_tables("SELECT * FROM orders, regions", dialect="athena", load_index=loader)

    assert loader.calls == 1


def test_unparseable_sql_is_passed_through_untouched():
    """Not our error to raise — the engine (or RLS default-deny) reports it."""
    loader = _Loader(_index({"orders": ["sales"]}))
    sql = "SELECT FROM WHERE ((("

    assert qualify_tables(sql, dialect="athena", load_index=loader) == sql


def test_table_matching_is_case_insensitive():
    loader = _Loader(_index({"orders": ["sales"]}))

    out = qualify_tables("SELECT * FROM Orders", dialect="athena", load_index=loader)

    assert "sales." in out.lower()


class _FakeReader:
    def __init__(self, tables_by_ns):
        self._t = tables_by_ns

    def list_namespaces(self):
        return list(self._t)

    def list_tables(self, namespace):
        value = self._t[namespace]
        if isinstance(value, Exception):
            raise value
        return value


def test_build_catalog_index_maps_tables_to_namespaces():
    index = build_catalog_index(_FakeReader({"sales": ["orders"], "ops": ["orders", "runs"]}))

    assert index.namespaces == ("sales", "ops")
    assert set(index.tables["orders"]) == {"sales", "ops"}
    assert index.tables["runs"] == ("ops",)


def test_build_catalog_index_skips_a_namespace_that_fails_to_list():
    index = build_catalog_index(
        _FakeReader({"sales": ["orders"], "broken": RuntimeError("glue down")})
    )

    assert index.tables["orders"] == ("sales",)
    assert "broken" in index.namespaces


def test_catalog_index_is_cached_between_calls(monkeypatch):
    from app.api import table_resolver

    reader = _FakeReader({"sales": ["orders"]})
    calls = []
    monkeypatch.setattr(table_resolver, "get_catalog_reader", lambda *a: (calls.append(1), reader)[1])
    monkeypatch.setattr(table_resolver.time, "monotonic", lambda: 1000.0)
    table_resolver.reset_catalog_index_cache()

    table_resolver.get_catalog_index()
    table_resolver.get_catalog_index()

    assert len(calls) == 1


def test_catalog_index_refreshes_after_the_ttl(monkeypatch):
    from app.api import table_resolver

    reader = _FakeReader({"sales": ["orders"]})
    calls = []
    monkeypatch.setattr(table_resolver, "get_catalog_reader", lambda *a: (calls.append(1), reader)[1])
    clock = {"t": 1000.0}
    monkeypatch.setattr(table_resolver.time, "monotonic", lambda: clock["t"])
    table_resolver.reset_catalog_index_cache()

    table_resolver.get_catalog_index()
    clock["t"] += table_resolver.CACHE_TTL_SECONDS + 1
    table_resolver.get_catalog_index()

    assert len(calls) == 2


# ── DDL/DML: only read positions are resolved ─────────────────────────────────
# execute_query also accepts CREATE / DROP / ALTER (see queries.py add_limit_to_query).
# A table being *defined* need not exist yet, and silently redirecting a DROP to a
# namespace the user never named would be destructive — so only FROM/JOIN sources
# are qualified.

def test_leaves_a_create_table_target_alone():
    loader = _Loader(_index({"orders": ["sales"]}))
    sql = "CREATE TABLE foo (id INT)"

    assert qualify_tables(sql, dialect="athena", load_index=loader) == sql
    assert loader.calls == 0


def test_qualifies_a_ctas_source_but_not_its_target():
    loader = _Loader(_index({"orders": ["sales"]}))

    out = qualify_tables(
        "CREATE TABLE newt AS SELECT * FROM orders", dialect="athena", load_index=loader
    )

    assert "sales.orders" in out
    assert "sales.newt" not in out


def test_never_redirects_a_drop_target():
    loader = _Loader(_index({"orders": ["sales"]}))
    sql = "DROP TABLE orders"

    assert qualify_tables(sql, dialect="athena", load_index=loader) == sql


def test_leaves_an_alter_target_alone():
    loader = _Loader(_index({"orders": ["sales"]}))
    sql = "ALTER TABLE orders ADD COLUMN x INT"

    assert qualify_tables(sql, dialect="athena", load_index=loader) == sql


def test_qualifies_an_insert_source_but_not_its_target():
    loader = _Loader(_index({"orders": ["sales"]}))

    out = qualify_tables(
        "INSERT INTO foo SELECT * FROM orders", dialect="athena", load_index=loader
    )

    assert "sales.orders" in out
    assert "sales.foo" not in out


def test_leaves_describe_alone():
    loader = _Loader(_index({"orders": ["sales"]}))
    sql = "DESCRIBE orders"

    assert qualify_tables(sql, dialect="athena", load_index=loader) == sql


def test_qualifies_a_table_referenced_only_in_a_subquery():
    loader = _Loader(_index({"orders": ["sales"]}))

    out = qualify_tables(
        "SELECT * FROM sales.customers WHERE id IN (SELECT cid FROM orders)",
        dialect="athena",
        load_index=loader,
    )

    assert "sales.orders" in out


# ── several catalogs ──────────────────────────────────────────────────────────
# A bare name found in a non-default catalog used to be rewritten to two parts, so it
# executed against the session (default) catalog — and its RLS key named the default
# catalog, so the other catalog's policy did not apply.

def _multi(tables, default="iceberg"):
    """CatalogIndex from {table: [(catalog, namespace), ...]}."""
    from app.api.table_resolver import CatalogIndex as _CI
    ns = sorted({(c, n) for pairs in tables.values() for c, n in pairs})
    return _CI(
        namespaces=tuple(n if c == default else f"{c}.{n}" for c, n in ns),
        tables={t: tuple(n if c == default else (c, n) for c, n in pairs)
                for t, pairs in tables.items()},
        default_catalog=default,
    )


def test_a_table_in_the_default_catalog_stays_two_part():
    loader = _Loader(_multi({"orders": [("iceberg", "sales")]}))
    assert qualify_tables("SELECT * FROM orders", dialect="trino",
                          load_index=loader) == "SELECT * FROM sales.orders"


def test_a_table_in_another_catalog_is_qualified_with_that_catalog():
    loader = _Loader(_multi({"entries": [("finance", "ledger")]}))
    out = qualify_tables("SELECT * FROM entries", dialect="trino", load_index=loader)
    assert out == "SELECT * FROM finance.ledger.entries"


def test_a_name_in_two_catalogs_is_ambiguous_and_names_both_fully():
    loader = _Loader(_multi({"orders": [("iceberg", "sales"), ("finance", "sales")]}))
    with pytest.raises(TableResolutionError) as ei:
        qualify_tables("SELECT * FROM orders", dialect="trino", load_index=loader)
    msg = str(ei.value)
    assert "iceberg.sales.orders" in msg and "finance.sales.orders" in msg


def test_two_part_names_are_left_to_mean_the_default_catalog():
    loader = _Loader(_multi({"entries": [("finance", "ledger")]}))
    sql = "SELECT * FROM ledger.entries"
    assert qualify_tables(sql, dialect="trino", load_index=loader) == sql
    assert loader.calls == 0


def test_the_index_spans_every_enabled_catalog(monkeypatch):
    from app import catalog_registry as reg
    from app.api import table_resolver
    from app.catalog_registry import CatalogEntry

    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
        CatalogEntry(name="off", kind="polaris", engine_catalog="off", enabled=False),
    ])
    readers = {"iceberg": _FakeReader({"sales": ["orders"]}),
               "finance": _FakeReader({"ledger": ["entries", "orders"]}),
               "off": _FakeReader({"x": ["hidden"]})}
    monkeypatch.setattr(table_resolver, "get_catalog_reader", lambda name=None: readers[name])
    table_resolver.reset_catalog_index_cache()
    try:
        index = table_resolver.get_catalog_index()
    finally:
        reg.reset()
        table_resolver.reset_catalog_index_cache()
    assert index.default_catalog == "iceberg"
    assert index.tables["entries"] == (("finance", "ledger"),)
    assert set(index.tables["orders"]) == {"sales", ("finance", "ledger")}
    assert "hidden" not in index.tables
    assert "finance.ledger" in index.namespaces and "sales" in index.namespaces


def test_one_unreadable_catalog_does_not_blind_the_others(monkeypatch):
    from app import catalog_registry as reg
    from app.api import table_resolver
    from app.catalog_registry import CatalogEntry

    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
    ])

    class _Down:
        def list_namespaces(self):
            raise RuntimeError("polaris down")

    readers = {"iceberg": _FakeReader({"sales": ["orders"]}), "finance": _Down()}
    monkeypatch.setattr(table_resolver, "get_catalog_reader", lambda name=None: readers[name])
    table_resolver.reset_catalog_index_cache()
    try:
        index = table_resolver.get_catalog_index()
    finally:
        reg.reset()
        table_resolver.reset_catalog_index_cache()
    assert index.tables["orders"] == ("sales",)


# ── a caller's catalogs (multi-catalog P3, app/catalog_access.py) ─────────────
# The index is global; the caller's view is applied at lookup. A table in a catalog
# the caller may not use must not be matched, nor named as a candidate or namespace —
# otherwise "ambiguous: iceberg.sales.x, secret.hr.x" tells the caller what exists.

def _two_catalog_index():
    return CatalogIndex(
        namespaces=("sales", "secret.hr"),
        tables={"orders": ("sales",), "salaries": (("secret", "hr"),),
                "people": ("sales", ("secret", "hr"))},
        default_catalog="iceberg")


def _no_secret(catalog):
    return (catalog or "").lower() != "secret"


def test_a_bare_name_only_in_a_hidden_catalog_is_not_found_and_not_named():
    with pytest.raises(TableResolutionError) as exc:
        qualify_tables("SELECT * FROM salaries", dialect="trino",
                       load_index=lambda: _two_catalog_index(), catalog_allowed=_no_secret)
    msg = str(exc.value)
    assert "was not found" in msg
    assert "secret" not in msg and "hr" not in msg


def test_a_name_in_a_visible_and_a_hidden_catalog_resolves_to_the_visible_one():
    out = qualify_tables("SELECT * FROM people", dialect="trino",
                         load_index=lambda: _two_catalog_index(), catalog_allowed=_no_secret)
    assert out == "SELECT * FROM sales.people"


def test_without_a_caller_view_the_ambiguity_is_reported_as_before():
    with pytest.raises(TableResolutionError) as exc:
        qualify_tables("SELECT * FROM people", dialect="trino",
                       load_index=lambda: _two_catalog_index())
    assert "secret.hr.people" in str(exc.value)


def test_a_hidden_default_catalog_hides_its_bare_names_too():
    with pytest.raises(TableResolutionError) as exc:
        qualify_tables("SELECT * FROM orders", dialect="trino",
                       load_index=lambda: _two_catalog_index(),
                       catalog_allowed=lambda c: (c or "").lower() != "iceberg")
    assert "Available namespaces: secret.hr." in str(exc.value)
