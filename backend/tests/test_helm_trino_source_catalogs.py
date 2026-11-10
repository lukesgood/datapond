"""A connection the backend projects into Trino needs two Secrets the backend may patch,
a catalog directory that sees them, and an env the passwords arrive through
(docs/superpowers/plans/2026-11-10-trino-connectors-phase2.md, Task 2)."""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm/datapond"


def render(values="values-onprem.yaml", *sets):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
           "-f", str(CHART / values)]
    for s in sets:
        cmd += ["--set", s]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"helm template failed:\n{result.stderr}"
    return result.stdout


def doc(rendered, kind, name):
    for part in rendered.split("\n---"):
        if re.search(rf"^kind: {kind}$", part, re.M) and \
                re.search(rf"^  name: {re.escape(name)}$", part, re.M):
            return part
    raise AssertionError(f"no {kind} named {name}")


ON = ("values-onprem.yaml", "trino.enabled=true")


def test_both_secrets_render_empty_when_trino_is_on():
    out = render(*ON)
    for name in ("trino-source-catalogs", "trino-source-credentials"):
        part = doc(out, "Secret", name)
        assert "ENCRYPTION_KEY" not in part
        assert not re.search(r"^data:\s*\n\s+\S", part, re.M), "a fresh install renders no data"


def test_nothing_renders_when_trino_is_off():
    out = render("values-foundation.yaml")
    assert "trino-source-catalogs" not in out and "trino-source-credentials" not in out


def test_trino_catalog_dir_is_projected_from_configmap_and_secret():
    dep = doc(render(*ON), "Deployment", "trino")
    assert "projected:" in dep
    assert re.search(r"configMap:\s*\n\s+name: trino-catalog\s*$", dep, re.M)
    assert re.search(r"secret:\s*\n\s+name: trino-source-catalogs\s*\n\s+optional: true", dep)
    assert "mountPath: /etc/trino/catalog\n" in dep


def test_trino_gets_the_credentials_as_env():
    dep = doc(render(*ON), "Deployment", "trino")
    assert re.search(r"envFrom:\s*\n\s+- secretRef:\s*\n\s+name: trino-source-credentials\s*\n\s+optional: true", dep)


def test_backend_learns_the_secret_and_deployment_names():
    dep = doc(render(*ON), "Deployment", "backend")
    for k, v in (("TRINO_SOURCE_CATALOGS_SECRET", "trino-source-catalogs"),
                 ("TRINO_SOURCE_CREDENTIALS_SECRET", "trino-source-credentials"),
                 ("TRINO_DEPLOYMENT", "trino")):
        assert re.search(rf"name: {k}\s*\n\s+value: \"?{v}\"?", dep), k


def test_backend_env_is_absent_when_trino_is_off():
    assert "TRINO_SOURCE_CATALOGS_SECRET" not in render("values-foundation.yaml")


def test_the_prod_single_reference_renders_them():
    out = render("values-prod-single.yaml")
    doc(out, "Secret", "trino-source-catalogs")
    assert "TRINO_SOURCE_CATALOGS_SECRET" in doc(out, "Deployment", "backend")


def test_secret_names_follow_the_values_knob():
    out = render(*ON, "trino.sourceCatalogs.catalogsSecret=my-cats",
                 "trino.sourceCatalogs.credentialsSecret=my-creds")
    doc(out, "Secret", "my-cats")
    doc(out, "Secret", "my-creds")
    dep = doc(out, "Deployment", "trino")
    assert "name: my-cats" in dep and "name: my-creds" in dep
    role = doc(out, "Role", "datapond-backend-reader")
    assert "my-cats" in role and "my-creds" in role
