"""Registering one catalog's Iceberg tables in another, through Trino — the exit path off
a provider catalog (Glue → an Iceberg REST catalog such as Polaris) without copying data.

Iceberg keeps a table's whole state in its metadata files in object storage; a catalog
only records where the current metadata file is. Trino's `register_table` procedure
records that location in the target catalog, so the same files answer from both."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import catalog_export as ce
from app import catalog_registry
from app.catalog_registry import CatalogEntry

META = "s3://lake/warehouse/raw/orders-1a2b/metadata/00003-9f.metadata.json"


class Cursor:
    """Answers the statements catalog_export documents, from a dict of catalogs."""

    def __init__(self, catalogs, counts=None, fail_register=None):
        self.catalogs = catalogs            # {catalog: {schema: {table: metadata_file}}}
        self.counts = counts or {}
        self.fail_register = fail_register
        self.executed, self._rows = [], []

    def execute(self, sql, params=None):
        self.executed.append(" ".join(sql.split()))
        s = self.executed[-1]
        if s.startswith("SHOW SCHEMAS FROM"):
            cat = s.split()[-1].strip('"')
            self._rows = [(x,) for x in self.catalogs.get(cat, {})]
        elif s.startswith("SHOW TABLES FROM"):
            cat, schema = [p.strip('"') for p in s.split()[-1].split(".")]
            self._rows = [(t,) for t in self.catalogs.get(cat, {}).get(schema, {})]
        elif "$metadata_log_entries" in s:
            ref = s.split(" FROM ")[1].split(" ORDER")[0]
            cat, schema, tbl = [p.strip('"') for p in ref.split('"."')]
            tbl = tbl.replace("$metadata_log_entries", "")
            self._rows = [(self.catalogs[cat][schema][tbl],)]
        elif s.startswith("CREATE SCHEMA IF NOT EXISTS"):
            self._rows = []
        elif s.startswith("CALL"):
            if self.fail_register:
                raise RuntimeError(self.fail_register)
            self._rows = []
        elif s.startswith("SELECT count(*) FROM"):
            self._rows = [(self.counts.get(s.split(" FROM ")[1], 0),)]
        else:
            raise AssertionError(s)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def test_the_table_location_and_metadata_file_come_from_the_latest_metadata_entry():
    assert ce.split_metadata_path(META) == ("s3://lake/warehouse/raw/orders-1a2b", "00003-9f.metadata.json")
    with pytest.raises(ValueError):
        ce.split_metadata_path("s3://lake/orders/data/x.parquet")


def test_the_plan_registers_missing_tables_and_skips_ones_the_target_already_has():
    cur = Cursor({"iceberg": {"raw": {"orders": META, "users": META.replace("orders", "users")},
                              "information_schema": {"tables": "x"}},
                  "catb": {"raw": {"users": "s3://elsewhere/metadata/1.metadata.json"}}})
    plan = ce.plan(cur, "iceberg", "catb")
    assert [(p.schema, p.table, p.action) for p in plan] == [
        ("raw", "orders", "register"), ("raw", "users", "exists")]
    assert plan[0].location == "s3://lake/warehouse/raw/orders-1a2b"
    assert plan[0].metadata_file == "00003-9f.metadata.json"
    assert not any(s.startswith(("CALL", "CREATE")) for s in cur.executed), "a plan changes nothing"


def test_the_plan_can_be_narrowed_to_a_schema_and_tables():
    cur = Cursor({"iceberg": {"raw": {"orders": META, "users": META}, "sales": {"x": META}}, "catb": {}})
    plan = ce.plan(cur, "iceberg", "catb", schema="raw", tables=["orders"])
    assert [(p.schema, p.table) for p in plan] == [("raw", "orders")]


def test_apply_creates_the_schema_registers_and_verifies_the_row_count():
    cur = Cursor({"iceberg": {"raw": {"orders": META}}, "catb": {}},
                 counts={'"iceberg"."raw"."orders"': 42, '"catb"."raw"."orders"': 42})
    out = ce.apply(cur, ce.plan(cur, "iceberg", "catb"), "iceberg", "catb")
    assert [(r.table, r.action, r.rows_source, r.rows_target) for r in out] == [("orders", "registered", 42, 42)]
    assert 'CREATE SCHEMA IF NOT EXISTS "catb"."raw"' in cur.executed
    call = next(s for s in cur.executed if s.startswith("CALL"))
    assert call == ('CALL "catb".system.register_table(schema_name => \'raw\', table_name => \'orders\', '
                    "table_location => 's3://lake/warehouse/raw/orders-1a2b', "
                    "metadata_file_name => '00003-9f.metadata.json')")


def test_a_count_mismatch_or_a_refusal_is_reported_per_table_not_raised():
    cur = Cursor({"iceberg": {"raw": {"orders": META}}, "catb": {}},
                 counts={'"iceberg"."raw"."orders"': 42, '"catb"."raw"."orders"': 0})
    (r,) = ce.apply(cur, ce.plan(cur, "iceberg", "catb"), "iceberg", "catb")
    assert r.action == "mismatch" and "42" in r.detail and "0" in r.detail
    cur = Cursor({"iceberg": {"raw": {"orders": META}}, "catb": {}},
                 fail_register="Location s3://lake/... is not in the list of allowed locations")
    (r,) = ce.apply(cur, ce.plan(cur, "iceberg", "catb"), "iceberg", "catb")
    assert r.action == "failed" and "allowed locations" in r.detail


def test_quoted_strings_cannot_break_out_of_the_call():
    assert ce.sql_string("a'b") == "'a''b'"
    with pytest.raises(ValueError):
        ce.ident("raw; DROP")


# ── the route ────────────────────────────────────────────────────────────────

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}


@pytest.fixture
def client(monkeypatch):
    from app.api import auth, catalog_admin
    reg = [CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True),
           CatalogEntry(name="lake", kind="polaris", engine_catalog="catb"),
           CatalogEntry(name="src_crm", kind="trino_source", engine_catalog="src_crm")]
    monkeypatch.setattr(catalog_registry, "entries", lambda include_disabled=False: reg)

    async def _load(pool, force=False, timeout=5.0):
        return reg
    monkeypatch.setattr(catalog_registry, "load", _load)

    links = []

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, sql, *args):
            assert "INSERT INTO catalog_table_links" in sql
            links.append(args)
            return "INSERT 0 1"

    class _Pool:
        def acquire(self):
            return _Conn()

    async def _pool():
        return _Pool()
    monkeypatch.setattr(catalog_admin, "_pool", _pool)
    audits = []

    async def _audit(pool, admin, event, name, details):
        audits.append((event, name, details))
    monkeypatch.setattr(catalog_admin, "_audit", _audit)
    cur = Cursor({"iceberg": {"raw": {"orders": META}}, "catb": {}},
                 counts={'"iceberg"."raw"."orders"': 7, '"catb"."raw"."orders"': 7})
    monkeypatch.setattr(ce, "_cursor", lambda: cur)
    app = FastAPI()
    app.include_router(catalog_admin.router, prefix="/api")

    async def _user():
        return dict(ADMIN)
    app.dependency_overrides[auth.require_user] = _user
    app.dependency_overrides[auth.require_admin] = _user
    c = TestClient(app)
    c.cur, c.audits, c.links = cur, audits, links
    return c


def test_the_route_plans_by_default_and_applies_only_when_asked(client):
    r = client.post("/api/catalogs/AwsDataCatalog/export", json={"target": "lake"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is False and body["tables"][0]["action"] == "register"
    assert not any(s.startswith("CALL") for s in client.cur.executed)
    r = client.post("/api/catalogs/AwsDataCatalog/export", json={"target": "lake", "apply": True})
    assert r.status_code == 200, r.text
    assert r.json()["tables"][0]["action"] == "registered"
    assert client.audits and client.audits[-1][0] == "catalog_exported"
    assert client.audits[-1][2]["target"] == "lake" and client.audits[-1][2]["registered"] == 1


def test_the_route_refuses_a_source_catalog_and_the_same_catalog(client):
    r = client.post("/api/catalogs/src_crm/export", json={"target": "lake"})
    assert r.status_code == 400 and "Iceberg" in r.json()["detail"]
    r = client.post("/api/catalogs/lake/export", json={"target": "lake"})
    assert r.status_code == 400
    r = client.post("/api/catalogs/nope/export", json={"target": "lake"})
    assert r.status_code == 404


def test_apply_records_the_target_as_a_read_only_mirror_by_default(client):
    r = client.post("/api/catalogs/AwsDataCatalog/export", json={"target": "lake", "apply": True})
    assert r.status_code == 200, r.text
    (row,) = client.links
    # mirror catalog/schema/table, owner catalog/schema/table, location, metadata file
    assert row[:6] == ("catb", "raw", "orders", "iceberg", "raw", "orders")
    assert row[6] == "s3://lake/warehouse/raw/orders-1a2b" and row[7] == "00003-9f.metadata.json"
    assert r.json()["mode"] == "mirror"


def test_move_makes_the_target_the_owner_and_the_source_the_mirror(client):
    r = client.post("/api/catalogs/AwsDataCatalog/export", json={"target": "lake", "apply": True, "mode": "move"})
    assert r.status_code == 200, r.text
    (row,) = client.links
    assert row[:6] == ("iceberg", "raw", "orders", "catb", "raw", "orders")


def test_a_plan_records_no_link(client):
    client.post("/api/catalogs/AwsDataCatalog/export", json={"target": "lake"})
    assert client.links == []


def test_the_plan_names_the_locations_a_target_must_allow(client):
    r = client.post("/api/catalogs/AwsDataCatalog/export", json={"target": "lake"})
    assert r.json()["allowed_locations_needed"] == ["s3://lake/warehouse/raw"]


def test_the_mirror_list_and_an_on_demand_check_are_admin_routes(client, monkeypatch):
    from app import mirror_freshness as mf
    from app.api import catalog_admin

    async def _check_all(pool, cursor_factory=None):
        return [mf.Result(mirror="catb.raw.orders", owner="iceberg.raw.orders", status="fresh", refreshed=True)]
    monkeypatch.setattr(mf, "check_all", _check_all)

    async def _list(pool):
        return [{"mirror": "catb.raw.orders", "owner": "iceberg.raw.orders", "status": "fresh"}]
    monkeypatch.setattr(catalog_admin, "_list_links", _list)
    r = client.get("/api/catalogs/mirrors")
    assert r.status_code == 200 and r.json()["mirrors"][0]["owner"] == "iceberg.raw.orders"
    r = client.post("/api/catalogs/mirrors/check")
    assert r.status_code == 200 and r.json()["results"][0]["refreshed"] is True


def test_export_and_mirrors_need_catalog_write_not_admin(client):
    """A data engineer (catalog:write) may export and see mirrors; a viewer may not.
    The routes declare the permission so the route inventory can see it."""
    from app.api import catalog_admin
    for route in catalog_admin.router.routes:
        if route.path in ("/catalogs/{name}/export", "/catalogs/mirrors", "/catalogs/mirrors/check"):
            guards = [getattr(d.call, "__datapond_authorization__", None) for d in route.dependant.dependencies]
            assert "catalog:write" in guards, (route.path, guards)
