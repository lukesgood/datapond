"""The catalog registry is where DataPond learns which data catalogs exist.

One catalog used to be implied by env (ICEBERG_CATALOG_BACKEND + QUERY_ENGINE). The
registry makes it a row, so a second catalog is a second row rather than a second
deployment. A deployment that has never written a row must behave exactly as before:
the env-derived default entry stands in until the table has one.
"""
import asyncio
import re
from pathlib import Path

import pytest

from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry, TableRef, UnknownCatalog


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_registry():
    reg.reset()
    yield
    reg.reset()


# ── the env-derived default ──────────────────────────────────────────────────

def test_glue_deployments_default_to_the_trino_catalog_name(monkeypatch):
    """2.4: Trino is the engine on the glue backend too, so a fresh install names the
    default catalog the way Trino does (`iceberg`), never `AwsDataCatalog`. Existing
    rows that still carry the old name stay valid as an alias (migration 0025)."""
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    monkeypatch.setenv("GLUE_WAREHOUSE", "s3://b/warehouse")
    e = reg.default_entry()
    assert (e.name, e.kind, e.engine_catalog) == ("iceberg", "glue", "iceberg")
    assert e.config["warehouse"] == "s3://b/warehouse"
    assert e.is_default and e.enabled


def test_trino_deployments_default_to_iceberg(monkeypatch):
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "polaris")
    monkeypatch.setenv("POLARIS_WAREHOUSE", "lake")
    e = reg.default_entry()
    assert (e.name, e.kind, e.engine_catalog) == ("iceberg", "polaris", "iceberg")
    # The Polaris catalog this entry lists — not every Polaris catalog there is.
    assert e.config["warehouse"] == "lake"


def test_trino_catalog_env_names_the_default(monkeypatch):
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    monkeypatch.setenv("TRINO_CATALOG", "lakehouse")
    assert reg.default_entry().name == "lakehouse"


def test_an_empty_registry_is_the_env_default(monkeypatch):
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    assert [e.name for e in reg.entries()] == ["iceberg"]


# ── rows from the database ───────────────────────────────────────────────────

def _entries():
    return [
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg",
                     config={"warehouse": "iceberg"}, is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance",
                     config={"warehouse": "finance"}),
        CatalogEntry(name="old", kind="polaris", engine_catalog="old",
                     config={"warehouse": "old"}, enabled=False),
    ]


def test_registry_rows_replace_the_env_default():
    reg.set_entries(_entries())
    assert [e.name for e in reg.entries()] == ["iceberg", "finance"]
    assert [e.name for e in reg.entries(include_disabled=True)] == ["iceberg", "finance", "old"]
    assert reg.default_entry().name == "iceberg"


def test_resolve_none_is_the_default_and_names_match_case_insensitively():
    reg.set_entries(_entries())
    assert reg.resolve(None).name == "iceberg"
    assert reg.resolve("").name == "iceberg"
    assert reg.resolve("FINANCE").name == "finance"


def test_resolve_accepts_the_engine_catalog_name():
    reg.set_entries([
        CatalogEntry(name="fin", kind="glue", engine_catalog="fin_athena", is_default=True),
    ])
    assert reg.resolve("fin_athena").name == "fin"


def test_an_unknown_or_disabled_catalog_is_refused():
    reg.set_entries(_entries())
    with pytest.raises(UnknownCatalog):
        reg.resolve("nope")
    with pytest.raises(UnknownCatalog):
        reg.resolve("old")
    assert issubclass(UnknownCatalog, ValueError)


def test_a_catalog_name_must_be_a_bare_identifier():
    reg.set_entries(_entries())
    with pytest.raises(UnknownCatalog):
        reg.resolve("iceberg; DROP TABLE x")


def test_rows_without_a_default_fall_back_to_the_first_enabled():
    reg.set_entries([CatalogEntry(name="a", kind="polaris", engine_catalog="a"),
                     CatalogEntry(name="b", kind="polaris", engine_catalog="b")])
    assert reg.default_entry().name == "a"


def test_cached_default_name_is_none_until_the_database_answered():
    """The RLS engine asks this on every query; it must never do IO and must say
    "not known" rather than invent the env value it will fall back to anyway."""
    assert reg.cached_default_name() is None
    reg.set_entries(_entries())
    assert reg.cached_default_name() == "iceberg"


class _Conn:
    def __init__(self, rows=(), fail=False):
        self.rows = list(rows)
        self.fail = fail
        self.executed = []

    async def fetch(self, sql, *a):
        if self.fail:
            raise OSError("db down")
        return self.rows

    async def execute(self, sql, *a):
        self.executed.append((sql, a))
        return "INSERT 0 1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self, timeout=None):
        return self.conn


def test_load_reads_rows_from_the_database():
    rows = [{"name": "iceberg", "kind": "polaris", "engine_catalog": "iceberg",
             "config": '{"warehouse": "iceberg"}', "secret_ref": None,
             "is_default": True, "enabled": True}]
    out = _run(reg.load(_Pool(_Conn(rows)), force=True))
    assert [e.name for e in out] == ["iceberg"]
    assert out[0].config == {"warehouse": "iceberg"}
    assert reg.cached_default_name() == "iceberg"


def test_an_unreachable_database_keeps_the_env_default(monkeypatch):
    monkeypatch.setenv("TRINO_CATALOG", "lake")
    out = _run(reg.load(_Pool(_Conn(fail=True)), force=True))
    assert [e.name for e in out] == ["lake"]


def test_an_unreachable_database_keeps_the_last_good_rows():
    reg.set_entries(_entries())
    _run(reg.load(_Pool(_Conn(fail=True)), force=True))
    assert [e.name for e in reg.entries()] == ["iceberg", "finance"]


def test_seed_inserts_the_env_default_only_into_an_empty_table(monkeypatch):
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    conn = _Conn()
    _run(reg.seed_from_env(_Pool(conn)))
    sql, args = conn.executed[0]
    assert "INSERT INTO data_catalogs" in sql
    assert "WHERE NOT EXISTS (SELECT 1 FROM data_catalogs)" in sql
    assert args[0] == "iceberg" and args[1] == "glue" and args[2] == "iceberg"


# ── TableRef ─────────────────────────────────────────────────────────────────

def test_tableref_parses_one_two_and_three_parts():
    assert TableRef.parse("orders", default="iceberg") == TableRef(None, None, "orders")
    assert TableRef.parse("sales.orders", default="iceberg") == TableRef("iceberg", "sales", "orders")
    assert TableRef.parse("fin.sales.orders", default="iceberg") == TableRef("fin", "sales", "orders")


def test_tableref_two_parts_default_to_the_registry_default():
    reg.set_entries(_entries())
    assert TableRef.parse("sales.orders").catalog == "iceberg"


def test_tableref_refuses_anything_but_identifiers():
    for bad in ("", "a.b.c.d", "sales.orders;drop", "x'.t", "a..b"):
        with pytest.raises(ValueError):
            TableRef.parse(bad, default="iceberg")


def test_tableref_sql_and_key():
    ref = TableRef("Fin", "Sales", "Orders")
    assert ref.sql() == "Fin.Sales.Orders"
    assert ref.key() == "fin.sales.orders"
    assert TableRef(None, "sales", "orders").sql() == "sales.orders"


# ── the migration ────────────────────────────────────────────────────────────

def test_the_migration_creates_the_registry_with_one_default_at_most():
    versions = Path(__file__).resolve().parents[1] / "migrations/versions"
    sql = (versions / "0018_data_catalogs.sql").read_text()
    py = (versions / "0018_data_catalogs.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.data_catalogs" in sql
    assert "CHECK (kind IN ('glue', 'iceberg_rest', 'polaris'))" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in sql and "WHERE is_default" in sql
    assert 'down_revision: Union[str, None] = "0017_chunk_access"' in py
    # No secret in a column: config is non-secret, secret_ref names where one lives.
    assert re.search(r"secret_ref\s+text NULL", sql)


# ── the 2.4 alias: AwsDataCatalog row, iceberg engine name ───────────────────

def _alias_entries():
    return [CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg",
                         config={"warehouse": "s3://b/warehouse"}, is_default=True)]


def test_alias_resolves_to_the_engine_name():
    reg.set_entries(_alias_entries())
    assert reg.resolve("AwsDataCatalog").engine_catalog == "iceberg"
    assert reg.resolve("iceberg").name == "AwsDataCatalog"
    assert reg.default_entry().engine_catalog == "iceberg"
    assert reg.cached_default_name() == "iceberg"


def test_a_metric_stored_under_the_alias_compiles_to_the_engine_name():
    """semantic/service.py compiles with access.resolve(v.catalog).engine_catalog, so a
    metric version whose stored catalog is AwsDataCatalog must come out as iceberg.*"""
    from datetime import date
    from app.semantic.compile import compile_metric
    from app.semantic.model import MetricVersion
    reg.set_entries(_alias_entries())
    v = MetricVersion(metric="revenue", version=1, catalog="AwsDataCatalog",
                      base_table="sales.orders", measure="SUM(amount)", time_column="order_date")
    sql = compile_metric(v, engine_catalog=reg.resolve(v.catalog).engine_catalog,
                         dialect="trino", today=date(2026, 11, 9), period="last_month").sql
    assert "iceberg" in sql.lower() and "awsdatacatalog" not in sql.lower()
