"""Polaris on the AWS reference: its metadata lives in the same Aurora as the backend
(externalDatabase), over TLS, with the backend's credentials — the chart assumed the
in-cluster PostgreSQL in every Polaris template. Needed to run Polaris next to Glue (the
catalog export target). The in-cluster path is unchanged."""
import yaml

from tests.test_helm_trino_extra_catalogs import render

GLUE_POLARIS = """
catalog: { backend: glue, glueWarehouse: "s3://b/warehouse" }
externalDatabase: { host: db.example.rds.amazonaws.com }
ingress: { domain: d.example }
polaris:
  enabled: true
  storage: { defaultBaseLocation: "s3://b/polaris" }
networkPolicy: { enabled: true }
"""


def _docs(out):
    return [d for d in yaml.safe_load_all(out) if d]


def _get(out, kind, name_prefix):
    return next(d for d in _docs(out) if d["kind"] == kind and d["metadata"]["name"].startswith(name_prefix))


def _env(container):
    return {e["name"]: e for e in container.get("env", [])}


def test_polaris_uses_the_external_database_over_tls_with_the_backend_credentials(tmp_path):
    out = render(tmp_path, GLUE_POLARIS, values="values-prod-single.yaml")
    for kind, name in (("Deployment", "polaris"), ("Job", "polaris-bootstrap")):
        spec = _get(out, kind, name)["spec"]["template"]["spec"]
        main = spec["containers"][0]
        env = _env(main)
        assert env["QUARKUS_DATASOURCE_JDBC_URL"]["value"] == \
            "jdbc:postgresql://db.example.rds.amazonaws.com:5432/polaris_catalog?sslmode=require"
        assert env["QUARKUS_DATASOURCE_USERNAME"]["valueFrom"]["secretKeyRef"]["key"] == "POSTGRES_USER"
        init = spec["initContainers"][0]
        script = " ".join(init["command"])
        assert "-h db.example.rds.amazonaws.com" in script and '-U "$POSTGRES_USER"' in script
        assert _env(init)["PGSSLMODE"]["value"] == "require"


def test_polaris_may_reach_instance_metadata_on_aws(tmp_path):
    """Polaris reads a registered table's metadata file from S3 with the node's role."""
    out = render(tmp_path, GLUE_POLARIS, values="values-prod-single.yaml")
    np = next(d for d in _docs(out) if d["kind"] == "NetworkPolicy"
              and d["metadata"]["name"].endswith("allow-metadata-for-aws-callers"))
    assert "polaris" in np["spec"]["podSelector"]["matchExpressions"][0]["values"]


def test_polaris_next_to_glue_brings_no_local_warehouse_volume(tmp_path):
    out = render(tmp_path, GLUE_POLARIS, values="values-prod-single.yaml")
    assert not any(d["kind"] == "PersistentVolumeClaim" and d["metadata"]["name"] == "iceberg-warehouse-pvc"
                   for d in _docs(out))


def test_the_in_cluster_path_is_unchanged(tmp_path):
    out = render(tmp_path, None)
    env = _env(_get(out, "Deployment", "polaris")["spec"]["template"]["spec"]["containers"][0])
    assert env["QUARKUS_DATASOURCE_JDBC_URL"]["value"] == "jdbc:postgresql://postgres:5432/polaris_catalog"
