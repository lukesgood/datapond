"""The backend can connect as a role that does not own the audit tables.

Migration 0012 creates it; this is the wiring that lets a deployment use it. Unset must
render exactly what it rendered before — the cutover is an operator's decision, not a
chart upgrade's.
"""
import re
import subprocess
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"


def render(*sets):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond"]
    for s in sets:
        cmd += ["--set", s]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def backend_deployment(rendered: str) -> str:
    for part in rendered.split("\n---"):
        if re.search(r"^kind: Deployment$", part, re.M) and re.search(r"^  name: backend$", part, re.M):
            return part
    raise AssertionError("no backend Deployment")


def test_unset_keeps_the_single_credential():
    dep = backend_deployment(render())
    assert "$(POSTGRES_USER):$(POSTGRES_PASSWORD)@" in dep
    assert "APP_DB_USER" not in dep


def test_half_configured_is_ignored_rather_than_half_applied():
    """A user with no password key would render a URL with an empty password."""
    dep = backend_deployment(render("externalDatabase.appUser=datapond_app"))
    assert "$(POSTGRES_USER):$(POSTGRES_PASSWORD)@" in dep and "APP_DB_USER" not in dep


def test_both_set_switches_the_runtime_url_only():
    dep = backend_deployment(render(
        "externalDatabase.appUser=datapond_app",
        "externalDatabase.appPasswordSecretKey=APP_DB_PASSWORD"))
    assert "$(APP_DB_USER):$(APP_DB_PASSWORD)@" in dep
    assert "- name: APP_DB_USER" in dep and "APP_DB_PASSWORD" in dep
    # the owning credential stays available to the app's other consumers
    assert "- name: POSTGRES_USER" in dep


def test_the_migration_job_keeps_the_owning_credential():
    rendered = render(
        "externalDatabase.appUser=datapond_app",
        "externalDatabase.appPasswordSecretKey=APP_DB_PASSWORD")
    job = [p for p in rendered.split("\n---") if re.search(r"^kind: Job$", p, re.M)
           and "migrate" in p]
    assert job, "no migrate Job rendered"
    assert "APP_DB_USER" not in job[0], "migrations must run as the owning role"
