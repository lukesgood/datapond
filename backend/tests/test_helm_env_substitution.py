"""Every $(VAR) in a container's env must be resolvable by that container.

kubelet expands $(VAR) only against variables defined EARLIER in the SAME container's
env list. A reference to a variable that is defined later, or only on a sibling
container, is not an error at apply time — the literal string "$(VAR)" is passed
through instead.

This is not hypothetical. The first WORM cutover put APP_DB_USER/APP_DB_PASSWORD on
the wait-for-schema init container only, while both containers rendered the app-role
DATABASE_URL. The backend came up and authenticated against Aurora as a user literally
named "$(APP_DB_USER)", which failed as a password error — a message that points at
credentials, not at templating.

test_helm_app_db_role.py asserts what the URL says. This asserts that what it says can
actually be resolved, which is the half that was missing.
"""
import re
import subprocess
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
REF = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")

CUTOVER = ("externalDatabase.appUser=datapond_app",
           "externalDatabase.appPasswordSecretKey=APP_DB_PASSWORD")


def render(*sets):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond"]
    for s in sets:
        cmd += ["--set", s]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def containers(rendered):
    """(kind/name, container name, env list) for every container in every workload."""
    for doc in yaml.safe_load_all(rendered):
        if not doc or doc.get("kind") not in ("Deployment", "StatefulSet", "Job", "CronJob"):
            continue
        spec = doc["spec"].get("template", {}).get("spec")
        if spec is None:  # CronJob nests one level deeper
            spec = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        owner = f'{doc["kind"]}/{doc["metadata"]["name"]}'
        for key in ("initContainers", "containers"):
            for c in spec.get(key) or []:
                yield owner, c.get("name", "?"), c.get("env") or []


def unresolvable(rendered):
    """Every (owner, container, var, referencing var) that kubelet cannot expand."""
    bad = []
    for owner, name, env in containers(rendered):
        defined = {}
        for i, e in enumerate(env):
            for ref in REF.findall(e.get("value") or ""):
                if defined.get(ref, len(env)) >= i:
                    bad.append((owner, name, ref, e["name"]))
            defined.setdefault(e["name"], i)
    return bad


def test_default_render_resolves_every_reference():
    assert unresolvable(render()) == []


def test_cutover_render_resolves_every_reference():
    """The regression: APP_DB_USER referenced by a container that never defined it."""
    assert unresolvable(render(*CUTOVER)) == []


def test_both_containers_define_the_app_role_before_using_it():
    found = {}
    for owner, name, env in containers(render(*CUTOVER)):
        if owner != "Deployment/backend":
            continue
        order = [e["name"] for e in env]
        if "DATABASE_URL" not in order:
            continue
        url = next(e["value"] for e in env if e["name"] == "DATABASE_URL")
        if "APP_DB_USER" not in url:
            continue
        found[name] = order
        for var in ("APP_DB_USER", "APP_DB_PASSWORD"):
            assert var in order, f"{name} uses {var} without defining it"
            assert order.index(var) < order.index("DATABASE_URL"), \
                f"{name} defines {var} after DATABASE_URL"
    assert len(found) == 2, f"expected the init container and the backend, got {sorted(found)}"
