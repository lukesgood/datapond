"""`polaris.extraCatalogNames` makes the catalog-init Job create more than one Polaris
catalog (the multi-catalog CI job needs two). Empty — the default — must render the Job
exactly as before, and a Trino extra catalog may reuse the Polaris client secret through
`credentialSecret.clientId`."""
import re
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "helm/datapond"
JOB = "polaris-catalog-init"


def render(*sets, values=("values-onprem.yaml",), ok=True, files=()):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond"]
    for v in values:
        cmd += ["-f", str(CHART / v)]
    for f in files:
        cmd += ["-f", str(f)]
    for s in sets:
        cmd += ["--set", s]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stderr
        return r.stdout
    assert r.returncode != 0, "helm template should have failed"
    return r.stderr


def render_json(setting):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
           "-f", str(CHART / "values-onprem.yaml"), "--set-json", setting]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def init_job(rendered):
    for part in rendered.split("\n---"):
        if re.search(rf"^  name: {JOB}$", part, re.M):
            return part
    raise AssertionError("catalog-init Job not rendered")


def test_default_renders_the_job_unchanged():
    default = init_job(render())
    assert "init_extra" not in default
    assert init_job(render_json("polaris.extraCatalogNames=[]")) == default
    assert 'echo "Polaris catalog init complete."' in default


def test_extra_names_create_catalogs_with_their_own_location():
    job = init_job(render("polaris.extraCatalogNames={catb,catc}"))
    assert 'init_extra "catb"' in job and 'init_extra "catc"' in job
    assert 's3://iceberg/catalogs/$N' in job
    # The primary flow is still there, before the extras.
    assert job.index("Creating catalog '$CATALOG'") < job.index("init_extra()")
    assert job.index('init_extra "catc"') < job.index('echo "Polaris catalog init complete."')


@pytest.mark.parametrize("bad", ["Catb", "1cat", "cat-b", "iceberg"])
def test_bad_or_duplicate_names_are_refused(bad):
    err = render(f"polaris.extraCatalogNames={{{bad}}}", ok=False)
    assert "extraCatalogNames" in err


def test_trino_extra_catalog_reuses_the_polaris_client_secret():
    out = render(
        "trino.extraCatalogs[0].name=catb",
        "trino.extraCatalogs[0].uri=http://polaris.datapond.svc.cluster.local:8181/api/catalog",
        "trino.extraCatalogs[0].warehouse=catb",
        "trino.extraCatalogs[0].credentialSecret.name=datapond-secrets",
        "trino.extraCatalogs[0].credentialSecret.key=POLARIS_CLIENT_SECRET",
        "trino.extraCatalogs[0].credentialSecret.clientId=polaris-client",
        "trino.enabled=true")
    assert "oauth2.credential=polaris-client:${ENV:TRINO_CATALOG_CATB_CREDENTIAL}" in out
    # Without a client id the env var still carries the whole `id:secret`.
    out = render(
        "trino.extraCatalogs[0].name=catb",
        "trino.extraCatalogs[0].uri=https://example.com/api/catalog",
        "trino.extraCatalogs[0].credentialSecret.name=s",
        "trino.extraCatalogs[0].credentialSecret.key=k",
        "trino.enabled=true")
    assert "oauth2.credential=${ENV:TRINO_CATALOG_CATB_CREDENTIAL}" in out


def test_ci_overlay_renders_both_catalogs():
    out = render(values=("values-ephemeral.yaml", "ci/values-multicatalog.yaml"))
    assert 'init_extra "catb"' in init_job(out)
    assert "catb.properties: |" in out and "iceberg.properties: |" in out
    assert "replicas: 1" in out
