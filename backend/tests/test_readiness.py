"""Readiness has to mean something.

Both probes pointed at `/health`, which returned `{"status": "healthy"}`
unconditionally. That is a liveness check — is the process running — being used to
answer a different question: should this pod receive traffic. So a backend whose
schema bootstrap had failed, or whose database was unreachable, went Ready and
served requests it could not fulfil. Every schema bootstrap in this application is
best-effort and swallows its exception, which makes the partial-schema case the
likely one rather than the exotic one.

These tests cover the decision only. No pool, no HTTP.
"""
import pytest

from app.readiness import Readiness


@pytest.fixture
def r():
    return Readiness(required={"base_schema", "rls_schema"})


def test_a_fresh_process_is_not_ready():
    """Nothing has reported yet, so there is no evidence the schema is in place.
    Starting from ready would serve traffic during the window that matters most."""
    assert Readiness(required={"base_schema"}).status()["ready"] is False


def test_ready_once_every_required_bootstrap_succeeded(r):
    r.record("base_schema", ok=True)
    r.record("rls_schema", ok=True)
    assert r.status()["ready"] is True


def test_not_ready_while_one_is_outstanding(r):
    r.record("base_schema", ok=True)
    assert r.status()["ready"] is False


def test_a_failed_bootstrap_keeps_the_pod_out_of_service(r):
    r.record("base_schema", ok=True)
    r.record("rls_schema", ok=False, detail="relation does not exist")
    assert r.status()["ready"] is False


def test_the_status_says_which_one_failed_and_why(r):
    r.record("rls_schema", ok=False, detail="relation does not exist")
    status = r.status()
    assert "rls_schema" in status["failed"]
    assert "relation does not exist" in status["detail"]["rls_schema"]


def test_an_optional_bootstrap_does_not_hold_the_pod_back(r):
    """Add-on schemas belong to features the deployment may not have enabled.
    Blocking on them would make an optional component mandatory."""
    r.record("base_schema", ok=True)
    r.record("rls_schema", ok=True)
    r.record("webauthn_schema", ok=False, detail="package not installed")
    assert r.status()["ready"] is True


def test_a_retry_can_clear_an_earlier_failure(r):
    r.record("base_schema", ok=False, detail="connection refused")
    r.record("base_schema", ok=True)
    r.record("rls_schema", ok=True)
    assert r.status()["ready"] is True
    assert r.status()["failed"] == []


def test_the_report_lists_what_is_still_outstanding(r):
    r.record("base_schema", ok=True)
    assert r.status()["pending"] == ["rls_schema"]


# ── the endpoint ──────────────────────────────────────────────────────────────

def test_the_readiness_endpoint_answers_503_when_not_ready(monkeypatch):
    """A probe that returns 200 with `"ready": false` in the body is a probe
    Kubernetes reads as healthy. The status code is the whole contract."""
    import asyncio

    import main
    from fastapi import Response

    async def _not_ready():
        return {"ready": False, "failed": ["base_schema"], "pending": [], "detail": {}}

    monkeypatch.setattr(main, "_readiness_payload", _not_ready)
    response = Response()
    body = asyncio.run(main.readiness_check(response))
    assert response.status_code == 503
    assert body["failed"] == ["base_schema"]


def test_the_readiness_endpoint_answers_200_when_ready(monkeypatch):
    import asyncio

    import main
    from fastapi import Response

    async def _ready():
        return {"ready": True, "failed": [], "pending": [], "detail": {}}

    monkeypatch.setattr(main, "_readiness_payload", _ready)
    response = Response()
    asyncio.run(main.readiness_check(response))
    assert response.status_code != 503


def test_the_probe_targets_the_readiness_path_not_the_liveness_one():
    """Both probes pointed at /health, so readiness never meant anything."""
    from pathlib import Path
    chart = (Path(__file__).resolve().parents[2]
             / "helm/datapond/templates/backend-deployment.yaml").read_text()
    readiness_block = chart.split("readinessProbe:", 1)[1][:400]
    assert "path: /health/ready" in readiness_block
