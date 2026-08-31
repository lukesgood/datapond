"""The backend Role has to cover what the backend actually calls.

`events` was missing. Two features depended on it — the Services page's event list and
the system event collector — and both failed the same way: a 403 the code turned into
an empty result, so the UI showed "no events" for a cluster that had produced
thousands. Valkey crash-looped 158 times over three days behind that empty list.
"""
import re
from pathlib import Path

ROLE = (Path(__file__).resolve().parents[2]
        / "helm/datapond/templates/rbac-backend.yaml").read_text()


def _read_resources() -> set:
    """Resources the Role grants get/list on, from its read rule."""
    granted = set()
    for resources, verbs in re.findall(
            r'resources:\s*\[([^\]]*)\]\s*\n\s*verbs:\s*\[([^\]]*)\]', ROLE):
        if "list" in verbs:
            granted |= {r.strip().strip('"') for r in resources.split(",")}
    return granted


def test_the_backend_may_list_events():
    assert "events" in _read_resources(), (
        "list_namespaced_event 403s without it — silently, as an empty event list")


def test_the_backend_may_still_list_what_the_services_page_needs():
    """The read rule is shared; adding to it must not drop from it."""
    assert {"pods", "pods/log", "services"} <= _read_resources()
