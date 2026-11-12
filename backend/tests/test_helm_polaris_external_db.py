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


def test_the_catalog_is_created_on_native_s3_too(tmp_path):
    """The catalog-init Job rendered only with MinIO, so Polaris beside Glue started with
    no catalog ("Unable to find warehouse", live rehearsal 2026-11-12). On native S3 it
    sends the region and uses the node's credentials (credential subscoping is skipped
    without an endpoint)."""
    out = render(tmp_path, GLUE_POLARIS.replace("  enabled: true\n", "  enabled: true\n  catalogName: lake\n", 1), values="values-prod-single.yaml")
    job = _get(out, "Job", "polaris-catalog-init")
    script = " ".join(job["spec"]["template"]["spec"]["containers"][0]["command"])
    env = _env(job["spec"]["template"]["spec"]["containers"][0])
    assert env["CATALOG"]["value"] == "lake" and env["BASELOC"]["value"] == "s3://b/polaris"
    assert '\\"region\\":\\"us-east-1\\"' in script, script[:2000]
    assert "endpoint" not in script.split("storageConfigInfo")[1][:300]


def test_every_polaris_replica_signs_tokens_with_one_shared_key(tmp_path):
    """Default token keys are per process: with two replicas a token issued by one was
    refused by the other — DataPond's Polaris browser answered 401 on the live node
    (2026-11-12). A symmetric key from datapond-secrets, the same for every replica."""
    out = render(tmp_path, GLUE_POLARIS + "\n", values="values-prod-single.yaml")
    env = _env(_get(out, "Deployment", "polaris")["spec"]["template"]["spec"]["containers"][0])
    assert env["POLARIS_AUTHENTICATION_TOKEN_BROKER_TYPE"]["value"] == "symmetric-key"
    ref = env["POLARIS_AUTHENTICATION_TOKEN_BROKER_SYMMETRIC_KEY_SECRET"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "datapond-secrets", "key": "POLARIS_TOKEN_KEY"}
    secret = next(d for d in _docs(out) if d["kind"] == "Secret" and d["metadata"]["name"] == "datapond-secrets")
    data = secret.get("stringData") or secret.get("data") or {}
    assert len(str(data.get("POLARIS_TOKEN_KEY", ""))) >= 32
    java_opts = env.get("JAVA_OPTS_APPEND", {}).get("value", "")
    assert "symmetric-key.secret" not in java_opts, "the key never sits in the JVM arguments"
