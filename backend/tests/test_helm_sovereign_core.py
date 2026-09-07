"""values-sovereign-core.yaml renders the Portable Core plus MinIO and Ollama, nothing
else, and identifies itself as a supported starter. Offline render, no cluster."""
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm" / "datapond"
VALUES = CHART / "values-sovereign-core.yaml"


def _render():
    r = subprocess.run(["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
                        "--values", str(VALUES)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _names(manifest, kind):
    return set(re.findall(rf"\nkind: {kind}\nmetadata:\n\s*name: (\S+)\n", manifest))


def test_profile_identity():
    v = yaml.safe_load(VALUES.read_text())
    p = v["product"]["profile"]
    assert p["id"] == "sovereign-core"
    assert p["label"] == "Sovereign Core"
    assert p["maturity"] == "supported-starter"


def test_every_addon_is_explicitly_false():
    v = yaml.safe_load(VALUES.read_text())
    for k in ("airflow", "spark", "polaris", "risingwave", "openmetadata", "jupyter",
              "mlflow", "trino", "vllm"):
        assert v[k]["enabled"] is False, k


def test_local_paths_are_on_and_consistent():
    v = yaml.safe_load(VALUES.read_text())
    assert v["minio"]["enabled"] is True
    assert v["ollama"]["enabled"] is True
    assert v["storage"]["endpoint"] == "minio:9000"
    assert v["ai"]["provider"] == "ollama"
    assert v["ai"]["egressPolicy"] == "local-only"
    assert v["ai"]["embedDim"] == 1024
    assert v["ollama"]["embedModel"] == "bge-m3"
    assert v["ollama"].get("embedLitellmName", "embed") == v["ai"].get("embedModel", "embed")
    assert "catalog" not in v, "a catalog backend would turn Sources/Catalog back on"


def test_render_has_core_minio_ollama_and_no_addons():
    m = _render()
    deployments = _names(m, "Deployment")
    statefulsets = _names(m, "StatefulSet")
    assert {"backend", "frontend", "litellm"} <= deployments
    assert "minio" in deployments | statefulsets
    assert "ollama" in deployments | statefulsets
    for absent in ("trino", "polaris", "airflow-webserver", "risingwave-frontend",
                   "openmetadata-server", "jupyterlab", "mlflow", "spark-master"):
        assert absent not in deployments | statefulsets, absent


def test_render_hides_data_navigation():
    m = _render()
    for flag in ("FEATURE_TRINO", "FEATURE_POLARIS", "FEATURE_GLUE", "FEATURE_ATHENA"):
        assert re.search(rf"name: {flag}\n\s+value: \"false\"", m), flag
    assert re.search(r"name: FEATURE_OLLAMA\n\s+value: \"true\"", m)
    assert re.search(r"name: AI_EGRESS_POLICY\n\s+value: \"local-only\"", m)


def test_backend_autoscaling_capped_for_single_node():
    # Base chart default is 10 (multi-node assumption). This profile is a single-node
    # starter, so cap it — an uncapped HPA can schedule more backend pods than a
    # single node has room for.
    m = _render()
    hpas = list(yaml.safe_load_all(m))
    backend_hpa = next(d for d in hpas if d and d.get("kind") == "HorizontalPodAutoscaler"
                        and d["spec"]["scaleTargetRef"]["name"] == "backend")
    assert backend_hpa["spec"]["maxReplicas"] == 3


def test_render_has_no_rls_claim():
    # No query engine in this profile, so FEATURE_RLS must not claim enforcement over
    # a surface that does not exist (templates/backend-deployment.yaml:365-375, gated
    # on governance.rls.enabled via `dig "enabled" false`, defaults false when the
    # governance key is absent).
    v = yaml.safe_load(VALUES.read_text())
    assert "governance" not in v
    m = _render()
    assert re.search(r"name: FEATURE_RLS\n\s+value: \"false\"", m)
