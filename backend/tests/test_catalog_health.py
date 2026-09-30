"""Per-catalog health for the Services page (multi-catalog P2, deferred until now).

`GET /api/catalogs/health` probes each enabled registry catalog with the same code as
the admin Test button, with a short deadline, off the event loop and concurrently: a
catalog that hangs or fails never holds up or hides the others. Results are cached
for HEALTH_TTL_SECONDS. A catalog the caller may not use is not listed.
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import catalog_access
from app import catalog_registry as reg
from app.api import auth, catalog_admin as ca
from app.api import catalog_backend as cb
from app.catalog_registry import CatalogEntry

ALICE = {"id": "11111111-1111-1111-1111-111111111111", "username": "alice", "role": "viewer"}
BOB = {"id": "22222222-2222-2222-2222-222222222222", "username": "bob", "role": "viewer"}
SECRET = "client-id:very-secret-value"


class _Reader:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def list_namespaces(self):
        self.behaviour["calls"] = self.behaviour.get("calls", 0) + 1
        if self.behaviour.get("sleep"):
            time.sleep(self.behaviour["sleep"])
        if self.behaviour.get("error"):
            raise RuntimeError(self.behaviour["error"])
        return ["a", "b"]


@pytest.fixture
def world(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="lake", kind="iceberg_rest", engine_catalog="lake",
                     secret_ref="catalog_secret.lake"),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance"),
        CatalogEntry(name="old", kind="polaris", engine_catalog="old", enabled=False),
    ])
    catalog_access.set_grants({"finance": [("user", BOB["id"])]})
    behaviours = {"iceberg": {}, "lake": {}, "finance": {}, "old": {}}
    monkeypatch.setattr(cb, "reader_for_entry", lambda e: _Reader(behaviours[e.name]))
    monkeypatch.setattr(reg, "secret_for", lambda e: SECRET if e.name == "lake" else None)
    ca.reset_health_cache()
    yield behaviours
    reg.reset()
    catalog_access.reset()
    ca.reset_health_cache()


def _client(user):
    app = FastAPI()
    app.include_router(ca.router, prefix="/api")

    async def _user():
        return user
    app.dependency_overrides[auth.require_user] = _user
    return TestClient(app)


def _by_name(user):
    r = _client(user).get("/api/catalogs/health")
    assert r.status_code == 200, r.text
    return {c["name"]: c for c in r.json()["catalogs"]}


def test_each_enabled_catalog_reports_its_status_and_latency(world):
    out = _by_name(BOB)
    assert set(out) == {"iceberg", "lake", "finance"}          # the disabled one is not
    assert all(c["status"] == "reachable" and c["error"] is None for c in out.values())
    assert all(isinstance(c["latency_ms"], int) for c in out.values())
    assert out["iceberg"]["is_default"] is True


def test_a_hidden_catalog_is_not_listed(world):
    assert set(_by_name(ALICE)) == {"iceberg", "lake"}


def test_one_failing_catalog_does_not_hide_the_others_and_is_sanitised(world):
    world["lake"]["error"] = f"401 https://u:p@catalog.example.com credential={SECRET}"
    r = _client(BOB).get("/api/catalogs/health")
    out = {c["name"]: c for c in r.json()["catalogs"]}
    assert out["lake"]["status"] == "error" and "401" in out["lake"]["error"]
    for leaked in (SECRET, "very-secret-value", "u:p@"):
        assert leaked not in r.text
    assert out["iceberg"]["status"] == out["finance"]["status"] == "reachable"


def test_a_hung_catalog_times_out_without_holding_the_others(world, monkeypatch):
    monkeypatch.setattr(ca, "HEALTH_TIMEOUT_SECONDS", 0.2)
    world["lake"]["sleep"] = 1.0
    world["finance"]["sleep"] = 0.1
    import asyncio

    async def _timed():
        started = time.monotonic()
        body = await ca.catalogs_health(user=BOB)
        return time.monotonic() - started, body
    # Timed inside the loop: the abandoned worker thread finishes its sleep after the
    # answer went out (a test client's loop teardown would wait for it).
    elapsed, body = asyncio.run(_timed())
    assert elapsed < 0.9                              # concurrent, bounded by the deadline
    out = {c["name"]: c for c in body["catalogs"]}
    assert out["lake"]["status"] == "error" and "0.2" in out["lake"]["error"]
    assert out["finance"]["status"] == "reachable"


def test_results_are_cached(world, monkeypatch):
    _by_name(BOB)
    _by_name(ALICE)
    assert world["iceberg"]["calls"] == 1
    monkeypatch.setattr(ca, "HEALTH_TTL_SECONDS", 0)
    _by_name(BOB)
    assert world["iceberg"]["calls"] == 2


def test_it_needs_catalog_read(world):
    nobody = {"id": ALICE["id"], "username": "x", "role": "viewer", "permissions": []}
    assert _client(nobody).get("/api/catalogs/health").status_code == 403
