"""Every label the chart renders is a string, in every profile.

The Trino pod label `version: {{ .Values.trino.image.tag }}` rendered the pinned tag
"482" as the number 482, and the API server refuses a Deployment whose label is not a
string ("cannot unmarshal number into ... labels of type string"). Every profile with
Trino on (onprem, quicktest, dev, prod) could not create Trino at all; the two-catalog
CI install was the first fresh install to get that far.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
PROFILES = [None, "values-onprem.yaml", "values-quicktest.yaml", "values-dev.yaml",
            "values-prod.yaml", "values-foundation.yaml", "values-prod-single.yaml",
            "values-sovereign-core.yaml", "values-aws.yaml"]


def _labels(doc):
    yield doc.get("metadata", {}).get("labels") or {}
    spec = doc.get("spec")
    if isinstance(spec, dict):
        tmpl = spec.get("template")
        if isinstance(tmpl, dict):
            yield (tmpl.get("metadata") or {}).get("labels") or {}
        jt = spec.get("jobTemplate")
        if isinstance(jt, dict):
            yield from _labels(jt)


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p or "base")
def test_no_label_renders_as_a_number(profile):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond"]
    if profile:
        cmd += ["-f", str(CHART / profile)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    bad = []
    for doc in yaml.safe_load_all(r.stdout):
        if not isinstance(doc, dict):
            continue
        for labels in _labels(doc):
            bad += [(doc["kind"], doc["metadata"]["name"], k, v)
                    for k, v in labels.items() if not isinstance(v, str)]
    assert bad == []
