"""Request-level authorization acceptance tests without live infrastructure."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import ai_backends, auth, storage, system_settings


async def _viewer():
    return {"id": "00000000-0000-0000-0000-000000000002", "username": "viewer", "role": "viewer"}


async def _admin():
    return {"id": "00000000-0000-0000-0000-000000000001", "username": "admin", "role": "admin"}


def _admin_probe(user: dict = Depends(auth.require_admin)):
    return {"role": user["role"]}


def _internal_probe(user: dict = Depends(auth.require_user_or_internal)):
    return {"username": user["username"], "internal": bool(user.get("internal"))}


def _probe_app(user_dependency=None) -> FastAPI:
    app = FastAPI()
    app.get("/admin-probe")(_admin_probe)
    app.post("/api/connectors/{connection_id}/sync")(_internal_probe)
    app.post("/api/ai/collections/{name}/ingest-source")(_internal_probe)
    app.post("/api/not-allowed")(_internal_probe)
    if user_dependency is not None:
        app.dependency_overrides[auth.require_user] = user_dependency
    return app


def test_admin_dependency_denies_viewer_and_accepts_admin():
    with TestClient(_probe_app(_viewer)) as client:
        response = client.get("/admin-probe")
        assert response.status_code == 403
        assert response.json() == {"detail": "Admin required"}

    with TestClient(_probe_app(_admin)) as client:
        response = client.get("/admin-probe")
        assert response.status_code == 200
        assert response.json() == {"role": "admin"}


def test_internal_key_is_accepted_only_on_exact_callback_routes(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "acceptance-secret")
    headers = {"X-Internal-Key": "acceptance-secret"}

    with TestClient(_probe_app()) as client:
        connector = client.post("/api/connectors/c-1/sync", headers=headers)
        ingest = client.post("/api/ai/collections/kb/ingest-source", headers=headers)
        denied = client.post("/api/not-allowed", headers=headers)
        suffix = client.post("/api/connectors/c-1/sync/extra", headers=headers)

    for response in (connector, ingest):
        assert response.status_code == 200
        assert response.json() == {"username": "system", "internal": True}
    assert denied.status_code == 401
    assert suffix.status_code == 404


def test_wrong_or_empty_internal_key_fails_closed(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "acceptance-secret")
    with TestClient(_probe_app()) as client:
        wrong = client.post(
            "/api/connectors/c-1/sync",
            headers={"X-Internal-Key": "wrong"},
        )
        missing = client.post("/api/connectors/c-1/sync")
    assert wrong.status_code == 401
    assert missing.status_code == 401


@pytest.mark.parametrize(
    ("router", "method", "path"),
    [
        (ai_backends.router, "GET", "/settings/ai/backends"),
        (storage.router, "POST", "/storage/buckets/acceptance-test"),
        (system_settings.router, "GET", "/settings/system"),
    ],
)
def test_real_global_admin_routes_reject_viewer_before_side_effects(router, method, path):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.require_user] = _viewer
    with TestClient(app) as client:
        response = client.request(method, path)
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin required"}
