"""The chart side of the catalog exit path: Trino may register tables on every Iceberg
catalog it renders, and a Polaris catalog can be told to accept tables stored outside its
own base location (a Glue warehouse, another catalog's) — Polaris refuses them otherwise."""
import re

from tests.test_helm_trino_extra_catalogs import render, doc

GLUE = """
catalog: { backend: glue, glueWarehouse: "s3://b/warehouse" }
externalDatabase: { host: db.example }
ingress: { domain: d.example }
"""
EXTRA = """
trino:
  extraCatalogs:
    - name: catb
      type: rest
      uri: http://polaris.datapond.svc.cluster.local:8181/api/catalog
      warehouse: catb
polaris:
  extraCatalogNames: [catb]
  storage:
    extraAllowedLocations: ["s3://legacy/warehouse", "s3://iceberg/warehouse"]
"""


def _catalog_file(out, name):
    cm = doc(out, "ConfigMap", "trino-catalog")
    m = re.search(rf"  {re.escape(name)}\.properties: \|\n((?:    .*\n)+)", cm)
    assert m, cm[:600]
    return m.group(1)


def test_register_table_is_enabled_on_glue_polaris_and_extra_catalogs(tmp_path):
    assert "iceberg.register-table-procedure.enabled=true" in _catalog_file(
        render(tmp_path, GLUE, values="values-prod-single.yaml"), "iceberg")
    out = render(tmp_path, EXTRA)
    assert "iceberg.register-table-procedure.enabled=true" in _catalog_file(out, "iceberg")
    assert "iceberg.register-table-procedure.enabled=true" in _catalog_file(out, "catb")


def test_polaris_catalogs_accept_the_extra_allowed_locations(tmp_path):
    job = doc(render(tmp_path, EXTRA), "Job", "polaris-catalog-init")
    extra = r',\\"s3://legacy/warehouse\\",\\"s3://iceberg/warehouse\\"'
    # the primary catalog, every extra catalog, and the storage re-sync of an existing one
    assert job.count('allowedLocations\\":[\\"$BASELOC\\"' + extra.replace("\\\\", "\\")) == 1, job[:3000]
    assert job.count('allowedLocations\\":[\\"$LOC\\"' + extra.replace("\\\\", "\\")) == 1
    assert job.count('allowedLocations\\":[\\"$1\\"' + extra.replace("\\\\", "\\")) == 1


def test_without_extra_locations_the_job_is_unchanged(tmp_path):
    job = doc(render(tmp_path, None), "Job", "polaris-catalog-init")
    assert 'allowedLocations\\":[\\"$BASELOC\\"]' in job


def test_polaris_feature_flags_for_in_place_registration_are_opt_in(tmp_path):
    """Registering a table that lives outside a Polaris catalog's own layout needs
    Polaris feature flags (unstructured/external table locations; overlapping catalog
    locations when two catalogs share a store). They widen what a writer may do, so they
    are never on by default — only through polaris.extraFeatures."""
    dep = doc(render(tmp_path, None), "Deployment", "polaris")
    assert "ALLOW_UNSTRUCTURED_TABLE_LOCATION" not in dep and "ALLOW_OVERLAPPING_CATALOG_URLS" not in dep
    dep = doc(render(tmp_path, EXTRA + "  extraFeatures:\n    ALLOW_UNSTRUCTURED_TABLE_LOCATION: true\n"
                                     "    ALLOW_OVERLAPPING_CATALOG_URLS: true\n"), "Deployment", "polaris")
    assert '-Dpolaris.features."ALLOW_UNSTRUCTURED_TABLE_LOCATION"=true' in dep
    assert '-Dpolaris.features."ALLOW_OVERLAPPING_CATALOG_URLS"=true' in dep


def test_a_feature_key_that_is_not_an_identifier_is_refused(tmp_path):
    err = render(tmp_path, EXTRA + "  extraFeatures:\n    'BAD KEY\"': true\n", ok=False)
    assert "extraFeatures" in err


def test_polaris_does_not_purge_files_on_drop_when_it_shares_locations(tmp_path):
    """A table registered in place keeps its files where its owner wrote them; a DROP
    through Polaris with purge on would delete the owner's data."""
    dep = doc(render(tmp_path, None), "Deployment", "polaris")
    assert '-Dpolaris.features."DROP_WITH_PURGE_ENABLED"=true' in dep, "own-files-only profiles keep purge"
    dep = doc(render(tmp_path, EXTRA), "Deployment", "polaris")
    assert '-Dpolaris.features."DROP_WITH_PURGE_ENABLED"=false' in dep
