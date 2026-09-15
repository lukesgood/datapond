"""A finished migrate Job does not make its workload unhealthy.

After each deploy the live Overview said "Needs attention: backend" while both backend
pods were Running and Ready. The migrate Job's pod shares the app=backend label, ends in
phase Succeeded (never Ready), and is kept for an hour; the status checks counted it.
"""
import asyncio
from types import SimpleNamespace

from app.api import services


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _pod(name, phase="Running", ready=True, owner="ReplicaSet"):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, owner_references=[SimpleNamespace(kind=owner)] if owner else None,
                                 labels={"app": "backend"}, creation_timestamp=None),
        status=SimpleNamespace(phase=phase, conditions=[SimpleNamespace(type="Ready", status="True" if ready else "False")],
                               container_statuses=None, pod_ip=None),
        spec=SimpleNamespace(node_name="n1", containers=[]),
    )


SERVING = [_pod("backend-a"), _pod("backend-b")]
MIGRATE = _pod("backend-migrate-26", phase="Succeeded", ready=False, owner="Job")


class _Core:
    def __init__(self, items):
        self.items = items

    def list_namespaced_pod(self, namespace=None, label_selector=None):
        return SimpleNamespace(items=self.items)


def test_job_pods_are_not_workload_pods():
    assert [p.metadata.name for p in services.workload_pods(SERVING + [MIGRATE])] == ["backend-a", "backend-b"]
    assert services.workload_pods([_pod("bare", owner=None)])[0].metadata.name == "bare"


def test_health_ignores_a_finished_migrate_job(monkeypatch):
    monkeypatch.setattr(services, "core_v1", _Core(SERVING + [MIGRATE]))
    out = _run(services.get_service_health("backend"))
    assert (out.status, out.pods_ready, out.pods_total) == ("healthy", 2, 2)


def test_health_still_reports_a_serving_pod_that_is_not_ready(monkeypatch):
    monkeypatch.setattr(services, "core_v1", _Core([_pod("backend-a"), _pod("backend-b", ready=False), MIGRATE]))
    out = _run(services.get_service_health("backend"))
    assert (out.status, out.pods_ready, out.pods_total) == ("degraded", 1, 2)


def test_only_job_pods_means_no_workload_pods(monkeypatch):
    monkeypatch.setattr(services, "core_v1", _Core([MIGRATE]))
    assert _run(services.get_service_health("backend")).status == "unknown"


# ── GET /api/services (main._compute_services_sync) — what the Overview reads ──

class _FakeK8s:
    def __init__(self, pods):
        self._pods = pods

    def _get_all_pods_cached(self):
        return self._pods

    def _is_pod_ready(self, pod):
        return services.is_pod_ready(pod)


def test_the_services_list_calls_backend_healthy_beside_a_finished_migrate_job(monkeypatch):
    import main
    # Replace the name, not attributes on it: main.k8s_client is a proxy that loads the
    # cluster config the moment an attribute is read.
    monkeypatch.setattr(main, "k8s_client", _FakeK8s(SERVING + [MIGRATE]))
    monkeypatch.setattr(main, "_service_registry", lambda: [{"name": "backend", "app": "backend", "kind": "pod"}])
    [backend] = main._compute_services_sync()
    assert backend.status == "healthy"


def test_the_services_list_still_flags_a_serving_pod_that_is_down(monkeypatch):
    import main
    monkeypatch.setattr(main, "k8s_client", _FakeK8s([_pod("backend-a"), _pod("backend-b", ready=False), MIGRATE]))
    monkeypatch.setattr(main, "_service_registry", lambda: [{"name": "backend", "app": "backend", "kind": "pod"}])
    [backend] = main._compute_services_sync()
    assert backend.status == "unhealthy"
