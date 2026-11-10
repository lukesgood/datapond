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


# ── one ConfigMap, one name, three places that have to agree ───────────────

TEMPLATES = Path(__file__).resolve().parents[2] / "helm/datapond/templates"
TRINO = (TEMPLATES / "trino-deployment.yaml").read_text()
BACKEND_DEPLOY = (TEMPLATES / "backend-deployment.yaml").read_text()
VALUES = (Path(__file__).resolve().parents[2] / "helm/datapond/values.yaml").read_text()

ACL_NAME_SOURCE = ".Values.trino.rls.configMapName"


def test_the_role_pins_the_configmap_the_chart_actually_creates():
    """RLS Layer 2 writes one ConfigMap, and three places name it: the template that
    creates it, the Role that permits writing it, and the env the backend reads it
    from. The Role used to read `.Values.governance.trinoAclConfigMap`, a key that
    appears in no values file — so it always resolved to the default. Rename the
    ConfigMap through the documented knob and the Role stays pinned to the old name:
    policy writes take a 403 from the API server and Trino's access-control rules
    quietly stop being updated.
    """
    import yaml

    values = yaml.safe_load(VALUES)
    assert ((values.get("trino") or {}).get("rls") or {}).get("configMapName"), (
        "the documented knob moved — this test names the wrong values path")
    assert ACL_NAME_SOURCE in TRINO, "the ConfigMap is created from a different key"
    assert ACL_NAME_SOURCE in ROLE, (
        "the Role names the ACL ConfigMap from a key the chart does not use")
    assert "governance.trinoAclConfigMap" not in ROLE, (
        "that key exists in no values file — it can only ever resolve to the default")


def test_the_backend_is_told_which_configmap_to_write():
    """governance.py reads TRINO_ACL_CONFIGMAP and defaults to `trino-access-control`.
    Unset, a renamed ConfigMap is never written at all — the backend updates a name
    nothing reads, and the failure is silent in the other direction too."""
    assert "TRINO_ACL_CONFIGMAP" in BACKEND_DEPLOY
    env = BACKEND_DEPLOY.split("TRINO_ACL_CONFIGMAP", 1)[1][:200]
    assert ACL_NAME_SOURCE in env, "the env does not come from the same values key"


# ── Trino source catalogs: two Secrets, get/patch, nothing wider ────────────

def _rendered_role():
    import subprocess
    import yaml
    chart = Path(__file__).resolve().parents[2] / "helm/datapond"
    out = subprocess.run(["helm", "template", "datapond", str(chart), "--namespace", "datapond",
                          "-f", str(chart / "values-onprem.yaml"), "--set", "trino.enabled=true"],
                         capture_output=True, text=True, check=True).stdout
    for d in yaml.safe_load_all(out):
        if d and d.get("kind") == "Role" and d["metadata"]["name"] == "datapond-backend-reader":
            return d
    raise AssertionError("no backend Role rendered")


def _secret_rules(role):
    return [r for r in role["rules"] if "secrets" in r.get("resources", [])]


def test_the_backend_may_patch_exactly_the_two_source_catalog_secrets():
    rules = _secret_rules(_rendered_role())
    assert rules, "no secrets rule: the backend cannot project source catalogs"
    for r in rules:
        assert set(r["verbs"]) <= {"get", "patch"}, r
        assert set(r.get("resourceNames", [])) == {"trino-source-catalogs",
                                                   "trino-source-credentials"}, r


def test_the_backend_may_not_list_or_read_other_secrets():
    for r in _secret_rules(_rendered_role()):
        assert "list" not in r["verbs"] and "watch" not in r["verbs"]
        assert r.get("resourceNames"), "an unscoped secrets rule reads every Secret"
