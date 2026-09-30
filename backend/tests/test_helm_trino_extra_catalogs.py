"""Trino can query a registry catalog only when it has a catalog file for it.

A data_catalogs entry (app/catalog_registry.py) is listed and governed by DataPond,
but SQL against it runs on the engine, and Trino knows only the catalogs in its
catalog ConfigMap. `trino.extraCatalogs` renders one `<engine_catalog>.properties` per
entry next to iceberg.properties. Credentials come from Kubernetes Secrets through env
references; values never carry one.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm/datapond"


def render(tmp_path, extra_yaml=None, values="values-onprem.yaml", ok=True):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
           "-f", str(CHART / values), "--set", "trino.enabled=true"]
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


PARTNER = """
trino:
  extraCatalogs:
    - name: partner
      type: rest
      uri: https://glue.ap-northeast-2.amazonaws.com/iceberg
      warehouse: "123456789012"
      sigv4:
        enabled: true
        signingName: glue
      s3Region: ap-northeast-2
    - name: unity
      type: rest
      uri: https://dbc.cloud.databricks.com/api/2.1/unity-catalog/iceberg-rest
      warehouse: main
      tokenSecret: {name: unity-catalog, key: token}
    - name: open_catalog
      type: rest
      uri: https://acct.snowflakecomputing.com/polaris/api/catalog
      warehouse: analytics
      scope: PRINCIPAL_ROLE:ALL
      credentialSecret: {name: open-catalog, key: credential}
"""


def test_no_extra_catalogs_by_default(tmp_path):
    cm = doc(render(tmp_path), "ConfigMap", "trino-catalog")
    files = re.findall(r"^  ([a-z0-9_]+)\.properties: \|", cm, re.M)
    assert "iceberg" in files
    assert set(files) <= {"iceberg", "postgres"}


def test_each_listed_catalog_gets_its_own_file(tmp_path):
    cm = doc(render(tmp_path, PARTNER), "ConfigMap", "trino-catalog")
    for name in ("partner", "unity", "open_catalog"):
        assert f"  {name}.properties: |" in cm
    partner = cm.split("  partner.properties: |", 1)[1].split(".properties: |", 1)[0]
    assert "connector.name=iceberg" in partner
    assert "iceberg.catalog.type=rest" in partner
    assert "iceberg.rest-catalog.uri=https://glue.ap-northeast-2.amazonaws.com/iceberg" in partner
    assert "iceberg.rest-catalog.warehouse=123456789012" in partner
    assert "iceberg.rest-catalog.security=SIGV4" in partner
    assert "iceberg.rest-catalog.signing-name=glue" in partner
    assert "s3.region=ap-northeast-2" in partner
    # the in-cluster object store belongs to the default catalog, not another's
    assert "s3.endpoint" not in partner


def test_credentials_come_from_secrets_by_env_reference(tmp_path):
    rendered = render(tmp_path, PARTNER)
    cm = doc(rendered, "ConfigMap", "trino-catalog")
    assert "iceberg.rest-catalog.security=OAUTH2" in cm
    assert "iceberg.rest-catalog.oauth2.token=${ENV:TRINO_CATALOG_UNITY_TOKEN}" in cm
    assert ("iceberg.rest-catalog.oauth2.credential=${ENV:TRINO_CATALOG_OPEN_CATALOG_CREDENTIAL}"
            in cm)
    assert "iceberg.rest-catalog.oauth2.scope=PRINCIPAL_ROLE:ALL" in cm
    dep = doc(rendered, "Deployment", "trino")
    assert re.search(r"- name: TRINO_CATALOG_UNITY_TOKEN\n\s+valueFrom:\n\s+secretKeyRef:\n"
                     r"\s+name: unity-catalog\n\s+key: token", dep)
    assert re.search(r"- name: TRINO_CATALOG_OPEN_CATALOG_CREDENTIAL\n\s+valueFrom:\n"
                     r"\s+secretKeyRef:\n\s+name: open-catalog\n\s+key: credential", dep)


def test_an_extra_catalog_changes_the_pod_template_so_trino_restarts(tmp_path):
    """Trino reads catalog files at startup only. Without extra catalogs the pod
    template is as before, so upgrading an install that lists none restarts nothing."""
    plain = doc(render(tmp_path), "Deployment", "trino")
    assert "checksum/catalogs" not in plain
    extra = doc(render(tmp_path, PARTNER), "Deployment", "trino")
    one = doc(render(tmp_path, PARTNER.replace("warehouse: main", "warehouse: other")),
              "Deployment", "trino")
    a = re.search(r"checksum/catalogs: \"?([0-9a-f]+)", extra)
    b = re.search(r"checksum/catalogs: \"?([0-9a-f]+)", one)
    assert a and b and a.group(1) != b.group(1)


@pytest.mark.parametrize("entry,why", [
    ("{name: partner, type: rest, uri: https://x, credential: 'id:secret'}", "Secret"),
    ("{name: partner, type: rest, uri: https://x, token: abc}", "Secret"),
    ("{name: Partner, type: rest, uri: https://x}", "name"),
    ("{name: 'a-b', type: rest, uri: https://x}", "name"),
    ("{name: iceberg, type: rest, uri: https://x}", "iceberg"),
    ("{name: partner, type: hive, uri: https://x}", "rest"),
    ("{name: partner, type: rest}", "uri"),
])
def test_bad_entries_fail_the_render(tmp_path, entry, why):
    err = render(tmp_path, f"trino:\n  extraCatalogs:\n    - {entry}\n", ok=False)
    assert why in err


@pytest.mark.parametrize("values", ["values.yaml", "values-foundation.yaml",
                                    "values-prod-single.yaml", "values-sovereign-core.yaml"])
def test_profiles_without_trino_render_unchanged(tmp_path, values):
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond",
           "-f", str(CHART / values)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "TRINO_CATALOG_" not in out.stdout
