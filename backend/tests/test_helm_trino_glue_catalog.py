"""The AWS Single-Node Reference runs Trino in-cluster over the Glue catalog.

Athena was the engine on `catalog.backend=glue` until 2.4. Now every profile runs the
same engine: the chart renders a Glue-typed Iceberg catalog for Trino when the catalog
backend is Glue, turns Trino on in values-prod-single.yaml, and derives nothing from
the backend any more — QUERY_ENGINE is Trino everywhere, and a glue deployment whose
stored values still say trino.enabled=false refuses to render rather than producing
a backend with no engine. Design: docs/superpowers/specs/2026-11-09-trino-unified-engine-and-connectors-design.md
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm/datapond"


def render(tmp_path, extra_yaml=None, values="values-prod-single.yaml", ok=True):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
           "-f", str(CHART / values)]
    if extra_yaml is not None:
        f = tmp_path / "extra.yaml"
        f.write_text(extra_yaml)
        cmd += ["-f", str(f)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if ok:
        assert result.returncode == 0, f"helm template failed:\n{result.stderr}"
        return result.stdout
    assert result.returncode != 0, "helm template should have failed"
    return result.stderr


def doc(rendered, kind, name):
    for part in rendered.split("\n---"):
        if re.search(rf"^kind: {kind}$", part, re.M) and \
                re.search(rf"^  name: {re.escape(name)}$", part, re.M):
            return part
    raise AssertionError(f"no {kind} named {name}")


def test_prod_single_renders_trino_with_a_glue_catalog(tmp_path):
    out = render(tmp_path)
    cm = doc(out, "ConfigMap", "trino-catalog")
    assert "iceberg.catalog.type=glue" in cm
    assert "hive.metastore.glue.region=us-east-1" in cm
    assert "hive.metastore.glue.default-warehouse-dir=s3://datapond-iceberg/warehouse" in cm
    assert "fs.native-s3.enabled=true" in cm
    assert "rest-catalog" not in cm and "jdbc-catalog" not in cm
    doc(out, "Deployment", "trino")  # Trino is on without any --set


def test_backend_engine_env_is_trino_on_every_profile(tmp_path):
    for values in ("values-prod-single.yaml", "values-onprem.yaml", "values-foundation.yaml"):
        out = render(tmp_path, values=values)
        be = doc(out, "Deployment", "backend")
        assert re.search(r"name: QUERY_ENGINE\n\s+value: \"trino\"", be), values
        assert re.search(r"name: RLS_DEFAULT_CATALOG\n\s+value: \"iceberg\"", be), values
        assert re.search(r"name: RLS_DEFAULT_SCHEMA\n\s+value: \"default\"", be), values
        assert "ATHENA" not in out, values


def test_trino_may_reach_imds_on_the_aws_reference(tmp_path):
    np = doc(render(tmp_path), "NetworkPolicy", "datapond-allow-metadata-for-aws-callers")
    assert re.search(r"values: \[backend, litellm, trino\]", np)


def test_glue_backend_without_trino_refuses_to_render(tmp_path):
    err = render(tmp_path, extra_yaml="trino:\n  enabled: false\n", ok=False)
    assert "needs Trino" in err


def test_chart_values_carry_no_athena_keys():
    # Keys only: a comment may still say "Athena removed"; a value may not.
    for values in ("values-prod-single.yaml", "values.yaml"):
        keys = [ln for ln in (CHART / values).read_text().splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        assert not [ln for ln in keys if "athena" in ln.split("#")[0].lower()], values
