import sys, types


def _install_fake_pyiceberg(monkeypatch):
    """Fake pyiceberg.catalog.glue.GlueCatalog + pyiceberg.catalog.rest.RestCatalog
    so we can assert which backend get_catalog() builds without real AWS/Polaris."""
    made = {}
    glue_mod = types.ModuleType("pyiceberg.catalog.glue")
    rest_mod = types.ModuleType("pyiceberg.catalog.rest")

    class GlueCatalog:
        def __init__(self, name, **props): made["kind"] = "glue"; made["props"] = props

    class RestCatalog:
        def __init__(self, name, **props): made["kind"] = "rest"; made["props"] = props

    glue_mod.GlueCatalog = GlueCatalog
    rest_mod.RestCatalog = RestCatalog
    monkeypatch.setitem(sys.modules, "pyiceberg.catalog.glue", glue_mod)
    monkeypatch.setitem(sys.modules, "pyiceberg.catalog.rest", rest_mod)
    return made


def test_get_catalog_builds_glue_when_backend_glue(monkeypatch):
    made = _install_fake_pyiceberg(monkeypatch)
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    monkeypatch.setenv("GLUE_WAREHOUSE", "s3://datapond-iceberg/warehouse")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    import app.connectors.iceberg_catalog as ic
    ic.reset_catalog()
    ic.get_catalog()
    assert made["kind"] == "glue"
    assert made["props"]["warehouse"] == "s3://datapond-iceberg/warehouse"
    assert made["props"]["glue.region"] == "us-east-1"


def test_get_catalog_defaults_to_polaris(monkeypatch):
    made = _install_fake_pyiceberg(monkeypatch)
    monkeypatch.delenv("ICEBERG_CATALOG_BACKEND", raising=False)
    import app.connectors.iceberg_catalog as ic
    ic.reset_catalog()
    ic.get_catalog()
    assert made["kind"] == "rest"
