"""Trino can run with workers: the coordinator plus `trino.workers.replicas` worker pods
that read the same catalogs. Off by default — the single-node reference runs one pod."""
import yaml

from tests.test_helm_trino_extra_catalogs import render

WORKERS = """
trino:
  workers:
    replicas: 2
networkPolicy:
  enabled: true
"""


def _docs(out):
    return [d for d in yaml.safe_load_all(out) if d]


def _get(out, kind, name):
    return next((d for d in _docs(out) if d["kind"] == kind and d["metadata"]["name"] == name), None)


def test_without_workers_nothing_changes(tmp_path):
    out = render(tmp_path, None)
    assert _get(out, "Deployment", "trino-worker") is None
    assert "node-scheduler.include-coordinator=true" in _get(out, "ConfigMap", "trino-config")["data"]["config.properties"]


def test_workers_join_the_coordinator_and_read_the_same_catalogs(tmp_path):
    out = render(tmp_path, WORKERS)
    w = _get(out, "Deployment", "trino-worker")
    assert w["spec"]["replicas"] == 2
    pod = w["spec"]["template"]
    assert pod["metadata"]["labels"]["app"] == "trino-worker", "the coordinator Service must not select workers"
    cfg = _get(out, "ConfigMap", "trino-worker-config")["data"]
    assert "coordinator=false" in cfg["config.properties"]
    assert "discovery.uri=http://trino:8080" in cfg["config.properties"]
    assert "node.id=${ENV:HOSTNAME}" in cfg["node.properties"], "every worker needs its own node id"
    vols = {v["name"]: v for v in pod["spec"]["volumes"]}
    assert vols["trino-config"]["configMap"]["name"] == "trino-worker-config"
    sources = vols["trino-catalog"]["projected"]["sources"]
    assert {"configMap": {"name": "trino-catalog"}} in sources
    assert any(s.get("secret", {}).get("name") == "trino-source-catalogs" for s in sources)
    c = pod["spec"]["containers"][0]
    assert {"secretRef": {"name": "trino-source-credentials", "optional": True}} in c["envFrom"]
    coord = _get(out, "ConfigMap", "trino-config")["data"]["config.properties"]
    assert "node-scheduler.include-coordinator=false" in coord, "with workers the coordinator only plans"


def test_the_backend_may_restart_the_workers_and_they_reach_instance_metadata(tmp_path):
    out = render(tmp_path, WORKERS)
    backend = _get(out, "Deployment", "backend")
    env = {e["name"]: e.get("value") for c in backend["spec"]["template"]["spec"]["containers"]
           for e in c.get("env", []) if c["name"] == "backend"}
    assert env.get("TRINO_WORKER_DEPLOYMENT") == "trino-worker"
    role = next(d for d in _docs(out) if d["kind"] == "Role" and "deployments" in str(d))
    names = [n for r in role["rules"] if "deployments" in r.get("resources", []) and "patch" in r["verbs"]
             for n in r.get("resourceNames", [])]
    assert "trino-worker" in names
    np = next(d for d in _docs(out) if d["kind"] == "NetworkPolicy"
              and d["metadata"]["name"].endswith("allow-metadata-for-aws-callers"))
    assert "trino-worker" in np["spec"]["podSelector"]["matchExpressions"][0]["values"]


def test_no_worker_env_without_workers(tmp_path):
    backend = _get(render(tmp_path, None), "Deployment", "backend")
    names = [e["name"] for c in backend["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])]
    assert "TRINO_WORKER_DEPLOYMENT" not in names
