"""The local Iceberg warehouse volume exists only where something writes to it.

With the Glue catalog Trino's warehouse is S3 (`catalog.glueWarehouse`); the AWS
reference still rendered a 50 GiB `iceberg-warehouse-pvc` and mounted it into Trino,
empty since the 2.4 cutover (checked on the live node 2026-11-12). Polaris, and Jupyter's
DuckDB notebooks, do use it."""
import yaml

from tests.test_helm_trino_extra_catalogs import render

GLUE = """
catalog: { backend: glue, glueWarehouse: "s3://b/warehouse" }
externalDatabase: { host: db.example }
ingress: { domain: d.example }
"""


def _docs(out):
    return [d for d in yaml.safe_load_all(out) if d]


def _pvc(out):
    return [d for d in _docs(out) if d["kind"] == "PersistentVolumeClaim"
            and d["metadata"]["name"] == "iceberg-warehouse-pvc"]


def _trino_volumes(out):
    dep = next(d for d in _docs(out) if d["kind"] == "Deployment" and d["metadata"]["name"] == "trino")
    spec = dep["spec"]["template"]["spec"]
    mounts = [m["name"] for c in spec["containers"] for m in c.get("volumeMounts", [])]
    return [v["name"] for v in spec.get("volumes", [])], mounts


def test_the_glue_profile_has_no_local_warehouse_volume(tmp_path):
    out = render(tmp_path, GLUE, values="values-prod-single.yaml")
    assert _pvc(out) == []
    volumes, mounts = _trino_volumes(out)
    assert "iceberg-warehouse" not in volumes and "iceberg-warehouse" not in mounts


def test_polaris_keeps_its_warehouse_volume(tmp_path):
    out = render(tmp_path, None, values="values-onprem.yaml")
    assert len(_pvc(out)) == 1
    volumes, mounts = _trino_volumes(out)
    assert "iceberg-warehouse" in volumes and "iceberg-warehouse" in mounts


def test_jupyter_on_glue_still_gets_the_volume_it_mounts(tmp_path):
    out = render(tmp_path, GLUE + "jupyter: { enabled: true }\n", values="values-prod-single.yaml")
    assert len(_pvc(out)) == 1
