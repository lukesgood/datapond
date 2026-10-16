"""Per-agent catalog access: the Agents page asks "may this agent use this catalog, and
why", and the answer must come from the rule enforcement uses (app/catalog_access.py),
not from a second implementation of it."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import catalog_access, catalog_registry as reg
from app.api import auth, service_account_routes as sar
from app.catalog_access import CatalogAccess
from app.catalog_registry import CatalogEntry

_REAL_REQUIRE_ADMIN = auth.require_admin
ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ACCT = "22222222-2222-2222-2222-222222222222"


def _entry(name="finance"):
    return CatalogEntry(name=name, kind="polaris", engine_catalog=name)


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("grants,expected", [
    ({}, "open"),
    ({"finance": [("user", ACCT.upper())]}, "user"),
    ({"finance": [("role", "ai_engineer")]}, "role"),
    ({"finance": [("user", ACCT), ("role", "ai_engineer")]}, "user"),
    ({"finance": [("user", "99999999-9999-9999-9999-999999999999"), ("role", "viewer")]}, None),
])
def test_via_precedence(grants, expected):
    catalog_access.set_grants(grants)
    access = CatalogAccess(grants=catalog_access._state["grants"], user_id=ACCT,
                           role="ai_engineer")
    assert access.via(_entry()) == expected
    assert access.allows(_entry()) is (expected is not None)
    assert access.allows("finance") is (expected is not None)


def test_via_for_exempt_and_unreadable_grants():
    assert CatalogAccess(exempt=True).via(_entry()) == "exempt"
    assert CatalogAccess(grants=None, user_id=ACCT, role="viewer").via(_entry()) is None


# ── the route ────────────────────────────────────────────────────────────────

def _app():
    app = FastAPI()
    app.include_router(sar.router, prefix="/api")

    async def _override():
        return ADMIN
    app.dependency_overrides[_REAL_REQUIRE_ADMIN] = _override
    return app


class _Conn:
    def __init__(self, account_row):
        self.account_row = account_row

    async def fetchrow(self, sql, *args):
        return self.account_row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _patch(monkeypatch, account_row):
    async def _pool():
        return _Pool(_Conn(account_row))
    monkeypatch.setattr(sar, "_get_pool", _pool)


@pytest.fixture(autouse=True)
def _registry():
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        _entry("finance"),
        _entry("hr"),
    ])
    yield
    reg.reset()
    catalog_access.reset()


def test_catalogs_listing(monkeypatch):
    _patch(monkeypatch, {"id": ACCT, "role": "ai_engineer"})
    other = "99999999-9999-9999-9999-999999999999"

    async def _grants(**kw):
        return {"finance": frozenset({("user", ACCT)}), "hr": frozenset({("user", other)})}
    monkeypatch.setattr(catalog_access, "load_grants", _grants)

    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/catalogs")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["account_id"] == ACCT
    assert d["catalogs"] == [
        {"catalog": "iceberg", "restricted": False, "allowed": True, "via": "open"},
        {"catalog": "finance", "restricted": True, "allowed": True, "via": "user"},
        {"catalog": "hr", "restricted": True, "allowed": False, "via": None},
    ]


def test_catalogs_grants_unavailable_is_503(monkeypatch):
    _patch(monkeypatch, {"id": ACCT, "role": "ai_engineer"})

    async def _boom(**kw):
        raise catalog_access.GrantsUnavailable("db down")
    monkeypatch.setattr(catalog_access, "load_grants", _boom)

    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/catalogs")
    assert r.status_code == 503
    assert r.json()["detail"] == "Catalog grants are unavailable."


def test_catalogs_404_for_non_service(monkeypatch):
    _patch(monkeypatch, None)
    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/catalogs")
    assert r.status_code == 404
    assert r.json()["detail"] == "Unknown service account."


def test_a_malformed_id_is_404_without_touching_the_database(monkeypatch):
    async def _boom():
        raise AssertionError("must not reach the database")
    monkeypatch.setattr(sar, "_get_pool", _boom)
    r = TestClient(_app()).get("/api/service-accounts/not-a-uuid/catalogs")
    assert r.status_code == 404
