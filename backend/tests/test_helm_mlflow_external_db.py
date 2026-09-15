"""MLflow runs on the deployment's database and can keep its UI off the public ingress.

The template hard-coded `postgresql://…@postgres:5432/mlflow` and `s3://mlflow-artifacts`,
so on the AWS reference (Aurora, no in-cluster postgres, no MinIO) enabling the add-on
rendered a server that could not start. And it always published MLflow's UI at /mlflow,
though MLflow has no authentication of its own.
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm/datapond"


def render(*sets, values=None):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond"]
    if values:
        cmd += ["-f", str(CHART / values)]
    for s in sets:
        cmd += ["--set-string" if s.startswith("mlflow.artifactRoot=") else "--set", s]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"helm template failed:\n{result.stderr}"
    return result.stdout


def doc(rendered, kind, name):
    for part in rendered.split("\n---"):
        if re.search(rf"^kind: {kind}$", part, re.M) and re.search(rf"^  name: {re.escape(name)}$", part, re.M):
            return part
    raise AssertionError(f"no {kind} named {name}")


def env_value(rendered, name):
    m = re.search(rf"- name: {name}\n\s+value: \"?([^\"\n]*)\"?", rendered)
    return m.group(1) if m else None


AWS = ("mlflow.enabled=true", "externalDatabase.host=aurora.example.internal")


def test_on_an_external_database_mlflow_uses_it_and_creates_its_database():
    dep = doc(render(*AWS, values="values-prod-single.yaml"), "Deployment", "mlflow")
    assert "@aurora.example.internal:5432/mlflow?sslmode=require" in dep
    assert "@postgres:5432" not in dep
    assert "- name: ensure-mlflow-db" in dep and "CREATE DATABASE mlflow" in dep
    assert "psycopg2-binary==2.9.9" in dep


def test_the_artifact_root_follows_values():
    dep = doc(render(*AWS, "mlflow.artifactRoot=s3://datapond-iceberg/mlflow-artifacts", values="values-prod-single.yaml"),
              "Deployment", "mlflow")
    assert '--default-artifact-root "s3://datapond-iceberg/mlflow-artifacts"' in dep


def test_the_ui_route_can_be_withheld_while_the_add_on_runs():
    rendered = render(*AWS, "mlflow.ingress.enabled=false", values="values-prod-single.yaml")
    assert "path: /mlflow" not in doc(rendered, "Ingress", "datapond-ingress")
    assert env_value(rendered, "FEATURE_MLFLOW") == "true"
    assert env_value(rendered, "FEATURE_MLFLOW_UI") == "false"


def test_the_ui_route_is_published_by_default_as_before():
    rendered = render("mlflow.enabled=true")
    assert "path: /mlflow" in doc(rendered, "Ingress", "datapond-ingress")
    assert env_value(rendered, "FEATURE_MLFLOW_UI") == "true"
    assert "@postgres:5432/mlflow?sslmode=disable" in doc(rendered, "Deployment", "mlflow")


def test_mlflow_off_publishes_no_ui():
    rendered = render("mlflow.enabled=false")
    assert env_value(rendered, "FEATURE_MLFLOW_UI") == "false"
