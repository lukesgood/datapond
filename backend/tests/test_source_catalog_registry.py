"""A Trino-backed connection is a registry catalog (`trino_source`) named from the
connection, whose grants are its owner and members (Phase 2 plan, Task 4)."""
import asyncio
import json
import re
import uuid

import pytest

from app import catalog_registry
from app.connectors import source_catalog


def test_trino_source_is_a_registry_kind_that_names_its_connection():
    assert "trino_source" in catalog_registry.KINDS
    cfg = catalog_registry.validate_config(
        "trino_source", {"connection_id": "x", "connector_type": "postgresql"})
    assert cfg["connection_id"] == "x"
    with pytest.raises(ValueError):
        catalog_registry.validate_config("trino_source", {"connection_id": "x"})


class FakeConn:
    """Enough asyncpg for register/unregister/catalog_for/sync_grants/ensure_rows:
    data_catalogs, catalog_grants, connector_connections, connector_members as lists of
    dicts; each call is matched on the SQL the module documents in its docstring."""

    def __init__(self, catalogs=(), connections=(), members=(), grants=()):
        self.catalogs = [dict(kind="polaris", config={}, **c) for c in catalogs]
        self.connections = [dict(c) for c in connections]
        self.members = [dict(m) for m in members]
        self.grants_rows = [dict(g) for g in grants]

    def catalog(self, name):
        return next((c for c in self.catalogs if c["name"] == name), None)

    def grants(self, name):
        return [g for g in self.grants_rows if g["catalog_name"] == name]

    def _catalog_of(self, cid):
        return next((c for c in self.catalogs if c["kind"] == "trino_source"
                     and c["config"].get("connection_id") == str(cid)), None)

    async def fetch(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT name, engine_catalog FROM data_catalogs"):
            return [{"name": c["name"], "engine_catalog": c["engine_catalog"]} for c in self.catalogs]
        if s.startswith("SELECT user_id FROM connector_members"):
            return [{"user_id": m["user_id"]} for m in self.members if str(m["connection_id"]) == str(args[0])]
        if s.startswith("SELECT c.id, c.name, c.connector_type FROM connector_connections c"):
            return [{"id": c["id"], "name": c["name"], "connector_type": c["connector_type"]}
                    for c in self.connections if self._catalog_of(c["id"]) is None]
        raise AssertionError(f"unexpected fetch: {s}")

    async def fetchval(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT engine_catalog FROM data_catalogs WHERE kind = 'trino_source'"):
            row = self._catalog_of(args[0])
            return row["engine_catalog"] if row else None
        if s.startswith("SELECT owner_id FROM connector_connections"):
            row = next((c for c in self.connections if str(c["id"]) == str(args[0])), None)
            return row["owner_id"] if row else None
        if s.startswith("DELETE FROM data_catalogs WHERE kind = 'trino_source'"):
            row = self._catalog_of(args[0])
            if row is None:
                return None
            self.catalogs.remove(row)
            self.grants_rows = [g for g in self.grants_rows if g["catalog_name"] != row["name"]]
            return row["engine_catalog"]
        raise AssertionError(f"unexpected fetchval: {s}")

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO data_catalogs"):
            name, kind, engine, config = args[0], args[1], args[2], json.loads(args[3])
            assert self.catalog(name) is None
            self.catalogs.append({"name": name, "kind": kind, "engine_catalog": engine,
                                  "config": config, "is_default": False, "enabled": True})
            return "INSERT 0 1"
        if s.startswith("DELETE FROM catalog_grants WHERE catalog_name"):
            self.grants_rows = [g for g in self.grants_rows if g["catalog_name"] != args[0]]
            return "DELETE 1"
        if s.startswith("INSERT INTO catalog_grants"):
            self.grants_rows.append({"catalog_name": args[0], "principal_kind": "user",
                                     "principal": args[1]})
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {s}")

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def test_register_picks_a_unique_slug_and_unregister_removes_it():
    conn = FakeConn(catalogs=[{"name": "src_sales_db", "engine_catalog": "src_sales_db"}])
    cid = str(uuid.uuid4())
    slug = asyncio.run(source_catalog.register(
        conn, connection_id=cid, name="Sales DB", connector_type="mysql"))
    assert slug == "src_sales_db_2"
    row = conn.catalog("src_sales_db_2")
    assert row["kind"] == "trino_source"
    assert row["config"] == {"connection_id": cid, "connector_type": "mysql"}
    assert asyncio.run(source_catalog.catalog_for(conn, cid)) == "src_sales_db_2"
    assert asyncio.run(source_catalog.unregister(conn, cid)) == "src_sales_db_2"
    assert conn.catalog("src_sales_db_2") is None
    assert asyncio.run(source_catalog.unregister(conn, cid)) is None


def test_register_never_yields_a_name_the_chart_already_uses():
    conn = FakeConn()
    for name in ("postgres", "iceberg", "system"):
        slug = asyncio.run(source_catalog.register(
            conn, connection_id=str(uuid.uuid4()), name=name, connector_type="postgresql"))
        assert slug.startswith("src_") and slug not in source_catalog.RESERVED


def test_sync_grants_projects_owner_and_members_as_user_grants():
    owner, m1 = str(uuid.uuid4()), str(uuid.uuid4())
    conn = FakeConn(connections=[{"id": "c1", "owner_id": owner}],
                    members=[{"connection_id": "c1", "user_id": m1, "role": "reader"}])
    asyncio.run(source_catalog.register(conn, connection_id="c1", name="CRM",
                                        connector_type="postgresql"))
    assert set(asyncio.run(source_catalog.sync_grants(conn, "c1"))) == {owner, m1}
    assert {g["principal"] for g in conn.grants("src_crm")} == {owner, m1}
    # Re-syncing replaces rather than accumulates.
    conn.members.clear()
    assert asyncio.run(source_catalog.sync_grants(conn, "c1")) == [owner]
    assert [g["principal"] for g in conn.grants("src_crm")] == [owner]


def test_an_unowned_connection_leaves_its_catalog_open():
    conn = FakeConn(connections=[{"id": "c1", "owner_id": None}])
    asyncio.run(source_catalog.register(conn, connection_id="c1", name="Sample",
                                        connector_type="postgresql"))
    assert asyncio.run(source_catalog.sync_grants(conn, "c1")) == []
    assert conn.grants("src_sample") == []


def test_sync_grants_on_an_unregistered_connection_writes_nothing():
    conn = FakeConn(connections=[{"id": "c1", "owner_id": str(uuid.uuid4())}])
    assert asyncio.run(source_catalog.sync_grants(conn, "c1")) == []
    assert conn.grants_rows == []


def test_ensure_rows_registers_a_connection_that_predates_phase_2():
    conn = FakeConn(connections=[
        {"id": "old", "owner_id": None, "name": "Legacy PG", "connector_type": "postgresql"},
        {"id": "url", "owner_id": None, "name": "Fin", "connector_type": "database_url"},
        {"id": "s3", "owner_id": None, "name": "Bucket", "connector_type": "s3"}])
    added = asyncio.run(source_catalog.ensure_rows(FakePool(conn)))
    assert added == 2
    assert conn.catalog("src_legacy_pg") is not None and conn.catalog("src_fin") is not None
    assert conn.catalog("src_bucket") is None
    assert asyncio.run(source_catalog.ensure_rows(FakePool(conn))) == 0


# ── the registry's view of such an entry ──────────────────────────────────────

def test_the_reader_for_a_source_catalog_reads_through_trino():
    from app.api import catalog_backend
    entry = catalog_registry.CatalogEntry(
        name="src_crm", kind="trino_source", engine_catalog="src_crm",
        config={"connection_id": "c", "connector_type": "postgresql"})
    reader = catalog_backend.reader_for_entry(entry)
    assert isinstance(reader, catalog_backend.TrinoSourceReader)
    assert reader.get_location("public", "orders") is None
    assert reader.row_count("public", "orders") is None


def test_the_source_reader_hides_system_schemas_and_lists_through_trino(monkeypatch):
    from app.api import catalog_backend

    class Cur:
        def __init__(self):
            self.sql = []
            self.description = [("id",), ("name",)]

        def execute(self, sql):
            self.sql.append(" ".join(sql.split()))

        def fetchall(self):
            last = self.sql[-1]
            if last.startswith("SHOW SCHEMAS"):
                return [("public",), ("information_schema",), ("pg_catalog",), ("sales",)]
            if last.startswith("SHOW TABLES"):
                return [("orders",), ("customers",)]
            if "information_schema.columns" in last:
                return [("id", "integer", "NO"), ("name", "varchar", "YES")]
            return [(1, "a"), (2, "b")]

    class Conn:
        def __init__(self):
            self.cur = Cur()

        def cursor(self):
            return self.cur

    conns = []

    def fake_conn(catalog=None, timeout=None, **kw):
        c = Conn()
        conns.append((catalog, c))
        return c
    monkeypatch.setattr("app.api.trino_util.trino_conn", fake_conn)
    entry = catalog_registry.CatalogEntry(
        name="src_crm", kind="trino_source", engine_catalog="src_crm",
        config={"connection_id": "c", "connector_type": "postgresql"})
    reader = catalog_backend.TrinoSourceReader(entry)
    assert reader.list_namespaces() == ["public", "sales"]
    assert reader.list_tables("public") == ["orders", "customers"]
    assert reader.get_columns("public", "orders") == [
        {"name": "id", "type": "integer", "nullable": False},
        {"name": "name", "type": "varchar", "nullable": True}]
    assert reader.preview("public", "orders", 10) == {"columns": ["id", "name"],
                                                       "rows": [[1, "a"], [2, "b"]]}
    assert all(cat == "src_crm" for cat, _ in conns)
    assert any(re.match(r"SELECT \* FROM src_crm\.public\.orders LIMIT 10$", c.cur.sql[-1])
               for _, c in conns)
    with pytest.raises(ValueError):
        reader.list_tables("public; DROP")
