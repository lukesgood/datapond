"""Pod CPU and memory reach the Infrastructure list and the pod table (they showed N/A)."""
import asyncio

import pytest

from app.api import services
from tests.test_service_status_job_pods import MIGRATE, SERVING, _Core, _FakeK8s, _pod


class _Metrics:
    def __init__(self, items=None, error=None):
        self.items, self.error, self.calls = items or [], error, []

    def list_namespaced_custom_object(self, group, version, ns, plural, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return {"items": self.items}


def _m(name, *containers):
    return {"metadata": {"name": name},
            "containers": [{"usage": {"cpu": c, "memory": m}} for c, m in containers]}


@pytest.mark.parametrize("raw,nano", [("250m", 250_000_000), ("1500000n", 1_500_000), ("2", 2_000_000_000), ("40u", 40_000)])
def test_cpu_units(raw, nano):
    assert services._parse_cpu_nano(raw) == nano


@pytest.mark.parametrize("raw,b", [("512Ki", 512 * 1024), ("300Mi", 300 * 1024 ** 2), ("1Gi", 1024 ** 3), ("1000k", 1_000_000), ("123", 123)])
def test_memory_units(raw, b):
    assert services._parse_mem_bytes(raw) == b


def test_pod_usage_sums_containers(monkeypatch):
    monkeypatch.setattr(services, "custom_api", _Metrics([_m("backend-a", ("60m", "200Mi"), ("10m", "100Mi"))]))
    assert services.pod_usage("app=backend") == {"backend-a": {"cpu_m": 70, "memory_mi": 300}}


def test_pod_usage_is_empty_without_metrics_server(monkeypatch):
    monkeypatch.setattr(services, "custom_api", _Metrics(error=RuntimeError("404 metrics.k8s.io")))
    assert services.pod_usage() == {}


def test_pod_table_carries_usage_and_skips_job_pods(monkeypatch):
    monkeypatch.setattr(services, "core_v1", _Core(SERVING + [MIGRATE]))
    monkeypatch.setattr(services, "custom_api", _Metrics([_m("backend-a", ("70m", "300Mi"))]))
    pods = asyncio.new_event_loop().run_until_complete(services.get_service_pods("backend"))
    assert [(p.name, p.cpu_m, p.memory_mi) for p in pods] == [("backend-a", 70, 300), ("backend-b", None, None)]


def test_services_list_reports_replicas_and_summed_usage(monkeypatch):
    import main
    monkeypatch.setattr(main, "k8s_client", _FakeK8s([_pod("backend-a"), _pod("backend-b", ready=False), MIGRATE]))
    monkeypatch.setattr(main, "_service_registry", lambda: [{"name": "backend", "app": "backend", "kind": "pod"},
                                                            {"name": "Amazon S3", "kind": "managed"}])
    monkeypatch.setattr(main, "pod_usage", lambda: {"backend-a": {"cpu_m": 70, "memory_mi": 300},
                                                    "backend-b": {"cpu_m": 5, "memory_mi": 280}})
    backend, s3 = main._compute_services_sync()
    assert (backend.ready, backend.replicas, backend.cpu_m, backend.memory_mi) == (1, 2, 75, 580)
    assert (s3.replicas, s3.cpu_m) == (None, None)


def test_services_list_leaves_usage_empty_without_metrics(monkeypatch):
    import main
    monkeypatch.setattr(main, "k8s_client", _FakeK8s(SERVING))
    monkeypatch.setattr(main, "_service_registry", lambda: [{"name": "backend", "app": "backend", "kind": "pod"}])
    monkeypatch.setattr(main, "pod_usage", lambda: {})
    [backend] = main._compute_services_sync()
    assert (backend.ready, backend.replicas, backend.cpu_m) == (2, 2, None)
