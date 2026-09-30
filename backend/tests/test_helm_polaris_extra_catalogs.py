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


def test_catalogs_on_minio_use_its_endpoint_path_style():
    """Polaris' FileIO would address MinIO as iceberg.minio (virtual host), which only
    k3s's CoreDNS override resolves; the two-catalog CI install on kind failed every
    commit with UnknownHostException. Both catalog payloads now name the endpoint and
    ask for path-style access, and each payload is still valid JSON."""
    import json
    job = init_job(render("polaris.extraCatalogNames={catb}"))
    payloads = re.findall(r'-d "(\{\s*\\"catalog\\".*?\}\}\})"', job, re.S)
    assert len(payloads) == 2, payloads
    for raw in payloads:
        body = json.loads(raw.replace('\\"', '"').replace("$BASELOC", "s3://x").replace("$LOC", "s3://x")
                          .replace("$CATALOG", "c").replace("$N", "n"))
        sc = body["catalog"]["storageConfigInfo"]
        assert sc["pathStyleAccess"] is True and sc["endpoint"].startswith("http://minio")
        assert sc["stsUnavailable"] is True


def test_minio_turns_credential_subscoping_on_and_native_s3_keeps_it_off():
    """pathStyleAccess is read only on Polaris' credential path, which the skip flag
    bypasses; with it on, the server's FileIO got table properties alone and addressed
    MinIO virtual-host style. S3-compatible storage turns the flag off (and marks the
    store as having no STS); native S3 keeps today's behaviour."""
    on_minio = render()
    assert '"SKIP_CREDENTIAL_SUBSCOPING_INDIRECTION"=false' in on_minio
    native = render("storage.endpoint=")
    assert '"SKIP_CREDENTIAL_SUBSCOPING_INDIRECTION"=true' in native


def test_an_existing_catalog_gets_the_storage_config_on_upgrade():
    import json
    job = init_job(render("polaris.extraCatalogNames={catb}"))
    assert '[ "$code" = "409" ] && sync_storage "$CATALOG" "$BASELOC"' in job
    assert '[ "$code" = "409" ] && sync_storage "$N" "$LOC"' in job
    raw = re.search(r'-d "(\{\\"currentEntityVersion\\".*?\}\})"\)', job, re.S).group(1)
    body = json.loads(raw.replace('\\"', '"').replace("$V", "3").replace("$1", "s3://x"))
    sc = body["storageConfigInfo"]
    assert body["currentEntityVersion"] == 3
    assert sc["pathStyleAccess"] is True and sc["stsUnavailable"] is True


def test_an_extra_catalog_on_minio_names_its_endpoint_and_path_style():
    """The default iceberg.properties set s3.endpoint and path-style for MinIO; an extra
    catalog did not, so Trino could not check a new table's location in it. Both are
    opt-in per catalog, since an AWS-backed REST catalog needs neither."""
    import json as _json
    cat = {"name": "catb", "uri": "http://polaris.datapond.svc.cluster.local:8181/api/catalog",
           "warehouse": "catb"}
    plain = render_json("trino.extraCatalogs=" + _json.dumps([cat]))
    assert "s3.path-style-access" not in plain.split("catb.properties")[1].split(".properties")[0]
    on_minio = render_json("trino.extraCatalogs=" + _json.dumps(
        [{**cat, "s3Endpoint": "http://minio:9000", "s3PathStyleAccess": True}]))
    block = on_minio.split("catb.properties")[1]
    assert "s3.endpoint=http://minio:9000" in block and "s3.path-style-access=true" in block
    bad = subprocess.run(
        ["helm", "template", "datapond", str(CHART), "-f", str(CHART / "values-onprem.yaml"),
         "--set-json", "trino.extraCatalogs=" + _json.dumps([{**cat, "s3Endpoint": "http://u:p@minio:9000"}])],
        capture_output=True, text=True)
    assert bad.returncode != 0 and "s3Endpoint" in bad.stderr
