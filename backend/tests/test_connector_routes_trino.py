"""Creating, re-configuring and deleting a Trino-backed connection registers its
catalog, projects it into Trino and tells the console the engine is restarting
(Phase 2 plan, Task 5). The pool, the projection, the probe and the registry refresh
are replaced; the routes and the registration module run for real."""
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, catalog_admin, connectors
from app.connectors import probe, trino_catalogs
from app.connectors.base import ConnectionTestResult

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}


class _DB:
    def __init__(self):
        self.connections, self.catalogs, self.grants, self.members, self.audit = [], [], [], [], []

    def catalog_rows(self):
        return [dict(c) for c in self.catalogs]

    def connection_rows(self):
        return [dict(c) for c in self.connections]

    def seed_connection(self, *, name, connector_type, catalog=None, owner_id=None):
        cid = str(uuid.uuid4())
        self.connections.append({"id": cid, "name": name, "connector_type": connector_type,
                                 "owner_id": owner_id, "config_encrypted": connectors.vault.encrypt_credentials(
                                     {"host": "h", "port": 5432, "database": "d",
                                      "username": "u", "password": "p"})})
        if catalog:
            self.catalogs.append({"name": catalog, "kind": "trino_source", "engine_catalog": catalog,
                                  "config": {"connection_id": cid, "connector_type": connector_type}})
        return cid


class _Conn:
    def __init__(self, db):
        self.db = db

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _conn(self, cid):
        return next((c for c in self.db.connections if str(c["id"]) == str(cid)), None)

    def _cat_of(self, cid):
        return next((c for c in self.db.catalogs if c["config"].get("connection_id") == str(cid)), None)

    async def fetch(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT name, engine_catalog FROM data_catalogs"):
            return [{"name": c["name"], "engine_catalog": c["engine_catalog"]} for c in self.db.catalogs]
        if s.startswith("SELECT user_id FROM connector_members"):
            return [{"user_id": m["user_id"]} for m in self.db.members if m["connection_id"] == str(args[0])]
        raise AssertionError(f"fetch: {s}")

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        if "FROM connector_connections r" in s:            # source_access.resolve
            c = self._conn(args[0])
            return {"id": uuid.UUID(c["id"]), "owner_id": c["owner_id"], "member_role": None} if c else None
        if s.startswith("SELECT name, connector_type, config_encrypted"):
            c = self._conn(args[0])
            return dict(c) if c else None
        raise AssertionError(f"fetchrow: {s}")

    async def fetchval(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT engine_catalog FROM data_catalogs WHERE kind = 'trino_source'"):
            c = self._cat_of(args[0])
            return c["engine_catalog"] if c else None
        if s.startswith("SELECT owner_id FROM connector_connections"):
            c = self._conn(args[0])
            return c["owner_id"] if c else None
        if s.startswith("DELETE FROM data_catalogs WHERE kind = 'trino_source'"):
            c = self._cat_of(args[0])
            if not c:
                return None
            self.db.catalogs.remove(c)
            return c["engine_catalog"]
        if s.startswith("SELECT last_checked_at"):
            return None
        raise AssertionError(f"fetchval: {s}")

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO connector_connections"):
            self.db.connections.append({"id": args[0], "name": args[1], "connector_type": args[2],
                                        "config_encrypted": args[3], "owner_id": args[7]})
            return "INSERT 0 1"
        if s.startswith("INSERT INTO data_catalogs"):
            self.db.catalogs.append({"name": args[0], "kind": args[1], "engine_catalog": args[2],
                                     "config": json.loads(args[3])})
            return "INSERT 0 1"
        if s.startswith("DELETE FROM catalog_grants"):
            self.db.grants = [g for g in self.db.grants if g[0] != args[0]]
            return "DELETE 0"
        if s.startswith("INSERT INTO catalog_grants"):
            self.db.grants.append((args[0], "user", args[1]))
            return "INSERT 0 1"
        if s.startswith("DELETE FROM connector_connections"):
            before = len(self.db.connections)
            self.db.connections = [c for c in self.db.connections if str(c["id"]) != str(args[0])]
            return f"DELETE {before - len(self.db.connections)}"
        if s.startswith("UPDATE connector_connections"):
            return "UPDATE 1"
        if s.startswith("INSERT INTO auth_audit_log"):
            self.db.audit.append((args[0], args[3], json.loads(args[4])))
            return "INSERT 0 1"
        raise AssertionError(f"execute: {s}")


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _Conn(self.db)


class _Project:
    def __init__(self):
        self.calls = 0

    async def __call__(self, pool, kube=None, *, restart_if_changed=True):
        self.calls += 1
        return {"changed": True, "catalogs": ["src_sales_db"]}


@pytest.fixture
def fake_pool(monkeypatch):
    db = _DB()

    async def _get():
        return _Pool(db)
    monkeypatch.setattr(connectors, "get_db_pool", _get)

    async def _refresh(pool, name):
        pass
    monkeypatch.setattr(catalog_admin, "_refresh", _refresh)
    monkeypatch.setattr(probe, "test", lambda t, cfg, timeout=10.0: ConnectionTestResult(success=True, message="ok"))
    monkeypatch.setenv("TRINO_SOURCE_CATALOGS_SECRET", "trino-source-catalogs")
    monkeypatch.setenv("TRINO_SOURCE_CREDENTIALS_SECRET", "trino-source-credentials")
    return db


@pytest.fixture
def fake_project(monkeypatch):
    p = _Project()
    monkeypatch.setattr(trino_catalogs, "project", p)
    return p


@pytest.fixture
def client(fake_pool):
    app = FastAPI()
    app.include_router(connectors.router, prefix="/api")

    async def _user():
        return dict(ADMIN)
    app.dependency_overrides[auth.require_user] = _user
    return TestClient(app)


def test_create_registers_a_catalog_and_reports_the_restart(client, fake_pool, fake_project):
    r = client.post("/api/connectors/create", json={
        "name": "Sales DB", "connector_type": "postgresql",
        "config": {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "p"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["catalog"] == "src_sales_db" and body["engine_restarting"] is True
    assert fake_project.calls == 1
    assert fake_pool.catalog_rows()[0]["config"]["connection_id"] == body["id"]
    assert fake_pool.grants == [("src_sales_db", "user", ADMIN["id"])]
    assert ("catalog_created", "src_sales_db", {"via": "connection", "connection_id": body["id"],
                                                "connector_type": "postgresql"}) in \
        [(e, n, {k: d[k] for k in ("via", "connection_id", "connector_type")}) for e, n, d in fake_pool.audit]


def test_a_database_url_payload_is_stored_as_postgresql(client, fake_pool, fake_project):
    r = client.post("/api/connectors/create", json={
        "name": "Fin", "connector_type": "database_url",
        "config": {"database_url": "postgresql://u:p@h:5432/fin"}})
    assert r.status_code == 200, r.text
    assert r.json()["connector_type"] == "postgresql"
    row = fake_pool.connection_rows()[0]
    assert row["connector_type"] == "postgresql"
    stored = connectors.vault.decrypt_credentials(row["config_encrypted"])
    assert stored["host"] == "h" and stored["database"] == "fin" and "database_url" not in stored


def test_a_source_that_fails_its_test_is_still_created_with_status_error(client, fake_pool, fake_project, monkeypatch):
    monkeypatch.setattr(probe, "test", lambda t, cfg, timeout=10.0: ConnectionTestResult(success=False, message="refused"))
    r = client.post("/api/connectors/create", json={
        "name": "Down", "connector_type": "mysql",
        "config": {"host": "h", "port": 3306, "database": "d", "username": "u", "password": "p"}})
    assert r.status_code == 200 and r.json()["status"] == "error"
    assert r.json()["catalog"] == "src_down" and fake_project.calls == 1


def test_delete_unregisters_and_projects(client, fake_pool, fake_project):
    cid = fake_pool.seed_connection(name="Sales DB", connector_type="postgresql", catalog="src_sales_db")
    r = client.delete(f"/api/connectors/{cid}")
    assert r.status_code == 200, r.text
    assert fake_pool.catalog_rows() == [] and fake_pool.connection_rows() == []
    assert fake_project.calls == 1 and r.json()["engine_restarting"] is True
    assert any(e == "catalog_deleted" and n == "src_sales_db" for e, n, _ in fake_pool.audit)


def test_reconfiguring_a_trino_source_projects_again(client, fake_pool, fake_project, monkeypatch):
    cid = fake_pool.seed_connection(name="Sales DB", connector_type="postgresql", catalog="src_sales_db")

    async def _check(connection_id):
        return {"success": True, "message": "ok", "status": "active"}
    monkeypatch.setattr(connectors, "_check_connection", _check)
    r = client.patch(f"/api/connectors/{cid}", json={"config": {"password": "new"}})
    assert r.status_code == 200, r.text
    assert fake_project.calls == 1 and r.json()["engine_restarting"] is True


def test_rest_connections_do_not_touch_the_engine(client, fake_pool, fake_project, monkeypatch):
    from app.connectors.rest import RestConnector

    async def ok(self):
        return ConnectionTestResult(success=True, message="ok")
    monkeypatch.setattr(RestConnector, "test_connection", ok)
    r = client.post("/api/connectors/create", json={
        "name": "Feed", "connector_type": "rest_api", "config": {"base_url": "https://example.test/x"}})
    assert r.status_code == 200, r.text
    assert r.json()["catalog"] is None and r.json()["engine_restarting"] is False
    assert fake_project.calls == 0 and fake_pool.catalog_rows() == []


def test_available_connectors_offer_the_five_engine_types_and_not_database_url(client):
    ids = {c["id"]: c for c in client.get("/api/connectors/available").json()}
    assert {"postgresql", "mysql", "sqlserver", "oracle", "mongodb"} <= {
        k for k, v in ids.items() if v.get("supported")}
    assert "database_url" not in ids
    assert ids["mongodb"]["engine"] == "trino" and ids["rest_api"].get("engine") == "python"
    assert "password" in ids["oracle"]["config_schema"]


def test_the_test_route_normalises_database_url_and_uses_the_probe(client, monkeypatch):
    seen = []

    def fake_test(t, cfg, timeout=10.0):
        seen.append((t.value, cfg.host, cfg.database))
        return ConnectionTestResult(success=True, message="ok")
    monkeypatch.setattr(probe, "test", fake_test)
    r = client.post("/api/connectors/test", json={"connector_type": "database_url",
                    "config": {"database_url": "mysql://u:p@h/db"}})
    assert r.json()["success"] is True and seen == [("mysql", "h", "db")]


def test_introspect_lists_tables_and_columns_through_the_probe(client, monkeypatch):
    from app.connectors.base import ColumnSchema
    monkeypatch.setattr(probe, "list_tables", lambda t, cfg, timeout=10.0: ["public.orders"])
    monkeypatch.setattr(probe, "columns", lambda t, cfg, table, timeout=10.0: [
        ColumnSchema(name="id", type="integer", nullable=False)])
    r = client.post("/api/connectors/introspect", json={"connector_type": "sqlserver",
                    "config": {"host": "h", "port": 1433, "database": "d", "username": "u", "password": "p"}})
    assert r.status_code == 200, r.text
    assert r.json()["tables"] == [{"name": "public.orders", "row_count": None,
                                   "columns": [{"name": "id", "type": "integer", "nullable": False}]}]
