"""Admins add, change and remove data catalogs from the console.

P1 made the catalog a registry row, but the only way to add one was SQL. These routes
are that SQL with its rules written down: a catalog's name is what SQL calls it and
must stay unambiguous; exactly one catalog is the default, and it can be neither
disabled nor removed; a catalog a row-level or masking policy names cannot be removed
out from under the policy; a credential is write-only and stored encrypted.
"""
import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import catalog_registry as reg
from app.api import auth, catalog_admin as ca
from app.api import catalog_backend as cb

ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
SECRET = "client-id:very-secret-value"


class _DB:
    """data_catalogs, system_settings, the two policy tables and auth_audit_log — only
    as far as the routes use them. The one-default unique index is enforced."""

    def __init__(self):
        self.catalogs = {}
        self.settings = {}
        self.rls, self.masks = [], []
        self.audit = []
        self.grants = []              # (catalog, kind, principal)
        self.users = {}               # id -> {username, email, auth_method}
        self.grants_table = True      # False: a database before migration 0021

    def add(self, name, kind="polaris", engine=None, config=None, default=False,
            enabled=True, secret_ref=None):
        self.catalogs[name] = {"name": name, "kind": kind, "engine_catalog": engine or name,
                               "config": json.dumps(config or {}), "secret_ref": secret_ref,
                               "is_default": default, "enabled": enabled}

    def check(self):
        assert sum(1 for r in self.catalogs.values() if r["is_default"]) <= 1, \
            "unique index data_catalogs_one_default violated"


class _UndefinedTable(Exception):
    sqlstate = "42P01"


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self, db):
        self.db = db

    def transaction(self):
        return _Tx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        if "FROM catalog_grants" in sql:
            if not self.db.grants_table:
                raise _UndefinedTable('relation "catalog_grants" does not exist')
            out = []
            for cat, kind, principal in sorted(self.db.grants):
                if cat != args[0]:
                    continue
                u = self.db.users.get(principal, {}) if kind == "user" else {}
                out.append({"principal_kind": kind, "principal": principal,
                            "created_at": None, "username": u.get("username"),
                            "email": u.get("email"), "auth_method": u.get("auth_method")})
            return out
        if "FROM users" in sql:
            return [{"id": i} for i in args[0] if i in self.db.users]
        if "FROM data_catalogs" in sql:
            rows = sorted(self.db.catalogs.values(),
                          key=lambda r: (not r["is_default"], r["name"]))
            return [dict(r) for r in rows]
        if "FROM system_settings" in sql:
            return [{"key": k, "value": v} for k, v in self.db.settings.items()
                    if k in args[0]]
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "SELECT name FROM data_catalogs WHERE name" in sql:
            return {"name": args[0]} if args[0] in self.db.catalogs else None
        if "rls_policies" in sql:
            names = set(args[0])
            return {"rls": sum(1 for c in self.db.rls if c.lower() in names),
                    "masks": sum(1 for c in self.db.masks if c.lower() in names)}
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        db = self.db
        if "INSERT INTO data_catalogs" in sql and "NOT EXISTS" in sql:
            if not db.catalogs:
                db.add(args[0], kind=args[1], engine=args[2], config=json.loads(args[3]),
                       default=True)
        elif "INSERT INTO data_catalogs" in sql:
            name, kind, engine, config, secret_ref, is_default, enabled = args
            assert name not in db.catalogs
            db.add(name, kind, engine, json.loads(config), is_default, enabled, secret_ref)
        elif "SET is_default = false" in sql:
            for r in db.catalogs.values():
                if r["name"] != args[0]:
                    r["is_default"] = False
        elif sql.lstrip().startswith("UPDATE data_catalogs"):
            name, engine, config, secret_ref, is_default, enabled = args
            db.catalogs[name].update(engine_catalog=engine, config=config,
                                     secret_ref=secret_ref, is_default=is_default,
                                     enabled=enabled)
        elif "DELETE FROM data_catalogs" in sql:
            db.catalogs.pop(args[0], None)
            db.grants = [g for g in db.grants if g[0] != args[0]]   # ON DELETE CASCADE
        elif "DELETE FROM catalog_grants" in sql:
            db.grants = [g for g in db.grants if g[0] != args[0]]
        elif "INSERT INTO catalog_grants" in sql:
            assert args[0] in db.catalogs, "catalog_grants.catalog_name FK"
            db.grants.append((args[0], args[1], args[2]))
        elif "INSERT INTO system_settings" in sql:
            db.settings[args[0]] = args[1]
        elif "DELETE FROM system_settings" in sql:
            db.settings.pop(args[0], None)
        elif "INSERT INTO auth_audit_log" in sql:
            db.audit.append({"event": args[0], "resource": args[3],
                             "details": json.loads(args[4])})
        else:
            raise AssertionError(sql)
        db.check()
        return "OK"


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _Conn(self.db)


@pytest.fixture
def db(monkeypatch):
    reg.reset()
    cb.reset_rest_cache()
    d = _DB()
    d.add("iceberg", kind="polaris", config={"warehouse": "iceberg"}, default=True)

    async def _pool():
        return _Pool(d)
    monkeypatch.setattr(ca, "_pool", _pool)
    yield d
    reg.reset()
    cb.reset_rest_cache()


def _client(user=ADMIN):
    app = FastAPI()
    app.include_router(ca.router, prefix="/api")

    async def _user():
        return user
    app.dependency_overrides[auth.require_user] = _user
    return TestClient(app)


REST = {"name": "lake", "kind": "iceberg_rest",
        "config": {"uri": "https://catalog.example.com/api/catalog", "warehouse": "wh"}}


# ── listing ──────────────────────────────────────────────────────────────────

def test_list_shows_entries_without_secrets(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"], secret_ref="catalog_secret.lake")
    db.settings["catalog_secret.lake"] = "ciphertext"
    r = _client().get("/api/catalogs")
    assert r.status_code == 200, r.text
    rows = {c["name"]: c for c in r.json()["catalogs"]}
    assert rows["lake"]["has_secret"] is True and rows["iceberg"]["has_secret"] is False
    assert rows["iceberg"]["is_default"] is True
    assert "ciphertext" not in r.text and "secret_ref" not in r.text


def test_list_is_readable_with_catalog_read(db):
    viewer = {"id": ADMIN["id"], "username": "v", "role": "viewer"}
    assert _client(viewer).get("/api/catalogs").status_code == 200


# ── who may change catalogs ──────────────────────────────────────────────────

@pytest.mark.parametrize("principal", [
    {"id": ADMIN["id"], "username": "bot", "role": "admin", "auth_method": "service"},
    {"id": ADMIN["id"], "username": "agent", "role": "admin", "oauth": True},
])
def test_delegated_credentials_cannot_change_catalogs(db, principal):
    c = _client(principal)
    assert c.post("/api/catalogs", json=REST).status_code == 403
    assert c.patch("/api/catalogs/iceberg", json={"enabled": True}).status_code == 403
    assert c.delete("/api/catalogs/iceberg").status_code == 403
    assert c.post("/api/catalogs/iceberg/test").status_code == 403
    assert list(db.catalogs) == ["iceberg"]


def test_non_admins_cannot_change_catalogs(db):
    viewer = {"id": ADMIN["id"], "username": "v", "role": "viewer"}
    assert _client(viewer).post("/api/catalogs", json=REST).status_code == 403


# ── create ───────────────────────────────────────────────────────────────────

def test_create_stores_the_secret_encrypted_and_audits_without_it(db):
    r = _client().post("/api/catalogs", json={**REST, "secret": SECRET})
    assert r.status_code == 201, r.text
    assert SECRET not in r.text and r.json()["has_secret"] is True
    row = db.catalogs["lake"]
    assert row["secret_ref"] == "catalog_secret.lake"
    assert row["engine_catalog"] == "lake" and row["is_default"] is False
    stored = db.settings["catalog_secret.lake"]
    assert SECRET not in stored and SECRET not in row["config"]
    from app.connectors.vault import CredentialVault
    assert CredentialVault().decrypt_credentials(stored)["v"] == SECRET
    assert db.audit[-1]["event"] == "catalog_created"
    assert db.audit[-1]["resource"] == "lake"
    assert SECRET not in json.dumps(db.audit)
    # the registry was refreshed, so the new entry is readable immediately
    assert reg.resolve("lake").kind == "iceberg_rest"
    assert reg.secret_for(reg.resolve("lake")) == SECRET


@pytest.mark.parametrize("body,status,fragment", [
    ({**REST, "name": "bad-name"}, 400, "name"),
    ({**REST, "name": "x" * 65}, 400, "name"),
    ({**REST, "kind": "hive"}, 400, "kind"),
    ({**REST, "engine_catalog": "a.b"}, 400, "engine_catalog"),
    ({**REST, "config": {"uri": "http://catalog.example.com"}}, 400, "https"),
    ({**REST, "config": {**REST["config"], "token": "t"}}, 400, "token"),
    ({"name": "g", "kind": "glue", "config": {"region": "us-east-1"}, "secret": "x"}, 400,
     "secret"),
    ({**REST, "name": "ICEBERG"}, 409, "iceberg"),
    ({**REST, "engine_catalog": "Iceberg"}, 409, "iceberg"),
    ({**REST, "is_default": True, "enabled": False}, 409, "default"),
])
def test_create_validates(db, body, status, fragment):
    r = _client().post("/api/catalogs", json=body)
    assert r.status_code == status, r.text
    assert fragment.lower() in r.json()["detail"].lower()
    assert list(db.catalogs) == ["iceberg"]
    assert not db.audit


def test_http_is_allowed_for_an_in_cluster_catalog(db):
    body = {**REST, "config": {"uri": "http://polaris.other.svc.cluster.local:8181/api/catalog"}}
    assert _client().post("/api/catalogs", json=body).status_code == 201


def test_a_new_default_clears_the_old_one_in_one_transaction(db):
    r = _client().post("/api/catalogs", json={**REST, "is_default": True})
    assert r.status_code == 201, r.text
    assert db.catalogs["lake"]["is_default"] and not db.catalogs["iceberg"]["is_default"]


def test_the_first_catalog_added_to_an_empty_registry_does_not_displace_the_env_default(
        db, monkeypatch):
    """Until startup seeds it, an empty table means "the env default". Adding a
    non-default catalog to it must not make that catalog the default by being the
    only row."""
    db.catalogs.clear()
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "polaris")
    monkeypatch.delenv("QUERY_ENGINE", raising=False)
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    assert _client().post("/api/catalogs", json=REST).status_code == 201
    assert db.catalogs["iceberg"]["is_default"] and not db.catalogs["lake"]["is_default"]


def test_the_default_glue_catalog_cannot_be_read_via_rest(db):
    db.catalogs.clear()
    db.add("AwsDataCatalog", kind="glue", config={"warehouse": "s3://b/w"}, default=True)
    r = _client().patch("/api/catalogs/AwsDataCatalog",
                        json={"config": {"warehouse": "s3://b/w", "via_rest": True,
                                         "region": "us-east-1", "catalog_id": "123456789012"}})
    assert r.status_code == 400 and "via_rest" in r.json()["detail"]


# ── update ───────────────────────────────────────────────────────────────────

def test_patch_sets_default_and_clears_the_previous(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    r = _client().patch("/api/catalogs/lake", json={"is_default": True})
    assert r.status_code == 200, r.text
    assert db.catalogs["lake"]["is_default"] and not db.catalogs["iceberg"]["is_default"]
    assert db.audit[-1]["event"] == "catalog_updated"
    assert db.audit[-1]["details"]["changed"] == ["is_default"]


def test_the_default_cannot_be_disabled_or_undefaulted(db):
    c = _client()
    r = c.patch("/api/catalogs/iceberg", json={"enabled": False})
    assert r.status_code == 409 and "default" in r.json()["detail"]
    r = c.patch("/api/catalogs/iceberg", json={"is_default": False})
    assert r.status_code == 409
    assert db.catalogs["iceberg"]["enabled"] and db.catalogs["iceberg"]["is_default"]


def test_a_disabled_catalog_cannot_become_default_unless_enabled_too(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"], enabled=False)
    c = _client()
    assert c.patch("/api/catalogs/lake", json={"is_default": True}).status_code == 409
    r = c.patch("/api/catalogs/lake", json={"is_default": True, "enabled": True})
    assert r.status_code == 200, r.text


def test_patch_secret_null_clears_it_and_absent_leaves_it(db):
    c = _client()
    c.post("/api/catalogs", json={**REST, "secret": SECRET})
    assert c.patch("/api/catalogs/lake", json={"enabled": False}).status_code == 200
    assert db.catalogs["lake"]["secret_ref"] == "catalog_secret.lake"
    r = c.patch("/api/catalogs/lake", json={"secret": None})
    assert r.status_code == 200 and r.json()["has_secret"] is False
    assert db.catalogs["lake"]["secret_ref"] is None
    assert "catalog_secret.lake" not in db.settings
    assert db.audit[-1]["details"]["secret"] == "cleared"


def test_patch_cannot_change_the_kind(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    assert _client().patch("/api/catalogs/lake", json={"kind": "glue"}).status_code == 422


def test_patch_validates_config_for_the_entrys_kind(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    r = _client().patch("/api/catalogs/lake", json={"config": {"region": "us-east-1"}})
    assert r.status_code == 400


def test_renaming_the_engine_catalog_of_a_policy_target_is_refused(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    db.rls.append("LAKE")
    r = _client().patch("/api/catalogs/lake", json={"engine_catalog": "lake2"})
    assert r.status_code == 409 and "1 row-level" in r.json()["detail"]


def test_patch_unknown_catalog_is_404(db):
    assert _client().patch("/api/catalogs/nope", json={"enabled": True}).status_code == 404


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_removes_the_catalog_and_its_secret(db):
    c = _client()
    c.post("/api/catalogs", json={**REST, "secret": SECRET})
    r = c.delete("/api/catalogs/lake")
    assert r.status_code == 200, r.text
    assert "lake" not in db.catalogs and "catalog_secret.lake" not in db.settings
    assert db.audit[-1]["event"] == "catalog_deleted"
    with pytest.raises(reg.UnknownCatalog):
        reg.resolve("lake")


def test_the_default_cannot_be_deleted(db):
    r = _client().delete("/api/catalogs/iceberg")
    assert r.status_code == 409 and "default" in r.json()["detail"]
    assert "iceberg" in db.catalogs


def test_a_catalog_a_policy_names_cannot_be_deleted(db):
    """rls_policies.catalog_name holds the engine's name for the catalog, in whatever
    case it was typed; the check is case-insensitive and names the count."""
    db.add("lake", kind="iceberg_rest", engine="LakeEngine", config=REST["config"])
    db.rls += ["lakeengine", "LAKEENGINE"]
    db.masks.append("Lake")
    r = _client().delete("/api/catalogs/lake")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "2 row-level" in detail and "1 masking" in detail
    assert "lake" in db.catalogs


def test_a_policy_on_another_catalog_does_not_block_delete(db):
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    db.rls.append("iceberg")
    assert _client().delete("/api/catalogs/lake").status_code == 200


def test_delete_unknown_is_404(db):
    assert _client().delete("/api/catalogs/nope").status_code == 404


# ── test connection ──────────────────────────────────────────────────────────

class _FakeRest:
    def __init__(self, n):
        self.n = n

    def list_namespaces(self, *a):
        return [(f"ns{i}",) for i in range(self.n)]


def test_test_lists_the_first_20_namespaces(db, monkeypatch):
    db.add("lake", kind="iceberg_rest", config=REST["config"], enabled=False)
    monkeypatch.setattr(cb, "_new_rest_catalog", lambda props: _FakeRest(25))
    r = _client().post("/api/catalogs/lake/test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and len(body["namespaces"]) == 20
    assert body["namespace_count"] == 25 and body["error"] is None


def test_test_returns_a_sanitised_error(db, monkeypatch):
    c = _client()
    c.post("/api/catalogs", json={**REST, "secret": SECRET})

    def _fail(props):
        raise RuntimeError(f"401 https://u:p@catalog.example.com credential={props['credential']}")
    monkeypatch.setattr(cb, "_new_rest_catalog", _fail)
    r = c.post("/api/catalogs/lake/test")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False
    assert "401" in body["error"]
    for leaked in (SECRET, "very-secret-value", "u:p@"):
        assert leaked not in r.text


def test_test_gives_up_after_the_deadline(db, monkeypatch):
    import time as _t
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    monkeypatch.setattr(ca, "TEST_TIMEOUT_SECONDS", 0.2)

    def _slow(props):
        _t.sleep(1)
        return _FakeRest(1)
    monkeypatch.setattr(cb, "_new_rest_catalog", _slow)
    body = _client().post("/api/catalogs/lake/test").json()
    assert body["ok"] is False and "0.2" in body["error"]


def test_test_forgets_a_remembered_failure(db, monkeypatch):
    """An admin who fixed the catalog and presses Test must see it tried again, not
    the failure remembered from a minute ago."""
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    monkeypatch.setattr(cb, "_new_rest_catalog",
                        lambda p: (_ for _ in ()).throw(ConnectionError("down")))
    c = _client()
    assert c.post("/api/catalogs/lake/test").json()["ok"] is False
    monkeypatch.setattr(cb, "_new_rest_catalog", lambda props: _FakeRest(2))
    assert c.post("/api/catalogs/lake/test").json()["ok"] is True


# ── system settings never shows catalog secrets ──────────────────────────────

def test_system_settings_listing_skips_catalog_secrets(monkeypatch):
    from app.api import system_settings as ss

    class _SConn(_Conn):
        async def fetchval(self, sql, *a):
            return "system_settings"

        async def fetch(self, sql, *a):
            return [{"key": "catalog_secret.lake", "value": "ciphertext"},
                    {"key": "ai.provider", "value": json.dumps("litellm")}]

    class _SPool:
        def acquire(self):
            return _SConn(None)

    async def _gp():
        return _SPool()
    monkeypatch.setattr(ss, "get_db_pool", _gp)
    out = asyncio.run(ss.get_system_settings())
    assert out == {"settings": {"ai.provider": "litellm"}}


# ── grants (multi-catalog P3) ─────────────────────────────────────────────────

ALICE_ID = "11111111-1111-1111-1111-111111111111"
BOT_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def people(db):
    db.users[ALICE_ID] = {"username": "alice", "email": "a@x", "auth_method": "local"}
    db.users[BOT_ID] = {"username": "bot", "email": "b@x", "auth_method": "service"}
    db.add("lake", kind="iceberg_rest", config=REST["config"])
    return db


def test_a_catalog_nobody_was_granted_is_open(people):
    r = _client().get("/api/catalogs/lake/grants")
    assert r.status_code == 200, r.text
    assert r.json() == {"catalog": "lake", "restricted": False, "grants": []}


def test_put_replaces_the_grants_and_audits_the_difference(people):
    from app import catalog_access
    catalog_access.set_grants({})
    r = _client().put("/api/catalogs/lake/grants", json={"grants": [
        {"kind": "user", "principal": ALICE_ID},
        {"kind": "user", "principal": BOT_ID.upper()},
        {"kind": "role", "principal": "auditor"},
        {"kind": "role", "principal": "auditor"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restricted"] is True
    got = {(g["kind"], g["principal"]) for g in body["grants"]}
    assert got == {("user", ALICE_ID), ("user", BOT_ID), ("role", "auditor")}
    bot = next(g for g in body["grants"] if g["principal"] == BOT_ID)
    assert bot["service_account"] is True and bot["username"] == "bot"
    assert people.audit[-1]["event"] == "catalog_grants_changed"
    assert people.audit[-1]["details"]["restricted"] is True
    assert len(people.audit[-1]["details"]["added"]) == 3
    # The grants cache was dropped, so the next caller reads the new list.
    assert catalog_access._state["grants"] is None

    r = _client().put("/api/catalogs/lake/grants", json={"grants": [
        {"kind": "role", "principal": "auditor"}]})
    assert {(g["kind"], g["principal"]) for g in r.json()["grants"]} == {("role", "auditor")}
    assert sorted(people.audit[-1]["details"]["removed"]) == [
        f"user:{ALICE_ID}", f"user:{BOT_ID}"]


def test_an_empty_list_reopens_the_catalog(people):
    people.grants.append(("lake", "role", "auditor"))
    r = _client().put("/api/catalogs/lake/grants", json={"grants": []})
    assert r.json()["restricted"] is False and people.grants == []


@pytest.mark.parametrize("grant,fragment", [
    ({"kind": "role", "principal": "superuser"}, "not a role"),
    ({"kind": "user", "principal": "alice"}, "not one"),
    ({"kind": "user", "principal": "99999999-9999-9999-9999-999999999999"}, "No user"),
])
def test_unknown_principals_are_refused(people, grant, fragment):
    r = _client().put("/api/catalogs/lake/grants", json={"grants": [grant]})
    assert r.status_code == 400 and fragment in r.json()["detail"]
    assert people.grants == []


def test_a_bad_kind_is_refused(people):
    r = _client().put("/api/catalogs/lake/grants",
                      json={"grants": [{"kind": "group", "principal": "x"}]})
    assert r.status_code == 422


def test_grants_of_an_unknown_catalog_are_404(people):
    assert _client().get("/api/catalogs/nope/grants").status_code == 404
    assert _client().put("/api/catalogs/nope/grants", json={"grants": []}).status_code == 404


@pytest.mark.parametrize("principal", [
    {"id": ADMIN["id"], "username": "bot", "role": "admin", "auth_method": "service"},
    {"id": ADMIN["id"], "username": "agent", "role": "admin", "oauth": True},
    {"id": ADMIN["id"], "username": "v", "role": "viewer"},
])
def test_only_a_signed_in_admin_reads_or_changes_grants(people, principal):
    c = _client(principal)
    assert c.get("/api/catalogs/lake/grants").status_code == 403
    assert c.put("/api/catalogs/lake/grants", json={"grants": []}).status_code == 403


def test_before_migration_0021_grants_read_as_none_and_cannot_be_written(people):
    people.grants_table = False
    assert _client().get("/api/catalogs/lake/grants").json()["restricted"] is False
    r = _client().put("/api/catalogs/lake/grants",
                      json={"grants": [{"kind": "role", "principal": "auditor"}]})
    assert r.status_code == 409 and "0021" in r.json()["detail"]


def test_deleting_a_catalog_deletes_its_grants(people):
    people.grants.append(("lake", "role", "auditor"))
    assert _client().delete("/api/catalogs/lake").status_code == 200
    assert people.grants == []
