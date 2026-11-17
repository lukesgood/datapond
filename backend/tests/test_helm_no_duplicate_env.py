"""No container in any profile renders the same env name twice.

Kubernetes tolerated it (the last entry wins), but Helm 4 installs with server-side
apply, which refuses the Deployment outright: "duplicate entries for key
[name=\"ENVIRONMENT\"]". The base values carried ENVIRONMENT in backend.env while the
template already set it, so every fresh install in CI failed once the runners moved
to Helm 4 (2026-11-18). jupyter.env and values-onprem's backend.env had the same
shape. This renders each profile, plus the CI overlays, and checks every container.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
PROFILES = [
    ["values-quicktest.yaml"], ["values-onprem.yaml"], ["values-aws.yaml"], ["values-dev.yaml"],
    ["values-prod.yaml"], ["values-foundation.yaml"], ["values-prod-single.yaml"],
    ["values-sovereign-core.yaml"],
    ["values-quicktest.yaml", "values-ephemeral.yaml"],
    ["values-sovereign-core.yaml", "values-ephemeral.yaml"],
    ["values-quicktest.yaml", "values-ephemeral.yaml", "ci/values-multicatalog.yaml"],
]


def _pod_specs(doc):
    spec = doc.get("spec") or {}
    if "jobTemplate" in spec:
        spec = spec["jobTemplate"].get("spec") or {}
    tpl = (spec.get("template") or {}).get("spec")
    return [tpl] if tpl else []


@pytest.mark.parametrize("files", PROFILES, ids=lambda f: "+".join(f))
def test_no_duplicate_env_names(files):
    args = [a for f in files for a in ("-f", str(CHART / f))]
    out = subprocess.run(["helm", "template", "datapond", str(CHART), "--namespace", "datapond", *args],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    dupes = []
    for doc in yaml.safe_load_all(out.stdout):
        if not doc:
            continue
        for pod in _pod_specs(doc):
            for c in (pod.get("containers") or []) + (pod.get("initContainers") or []):
                names = [e["name"] for e in c.get("env") or []]
                d = sorted({n for n in names if names.count(n) > 1})
                if d:
                    dupes.append(f"{doc['kind']}/{doc['metadata']['name']}/{c['name']}: {d}")
    assert not dupes, dupes
