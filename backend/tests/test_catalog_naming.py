"""The catalog name shown in the UI must be the one the engine will accept.

Observed live: Catalog table cards read `iceberg.planlab` while the Analytics schema
tree read `AwsDataCatalog` — the same deployment, two different answers. A user who
copies the name from the card writes a query the engine cannot resolve.
"""
import app.api.catalog as catalog


def test_tables_are_labelled_with_the_engines_catalog(monkeypatch):
    import asyncio

    class _Reader:
        def list_namespaces(self): return ["planlab"]
        def list_tables(self, ns): return ["orders"]

    # The engine decides the name; the registry's env default derives it from there.
    monkeypatch.setenv("QUERY_ENGINE", "athena")
    monkeypatch.setattr(catalog, "get_catalog_reader", lambda *a: _Reader())

    res = asyncio.run(catalog.list_all_tables())

    assert res.tables[0].catalog == "AwsDataCatalog"


def test_trino_deployments_still_read_iceberg(monkeypatch):
    import asyncio

    class _Reader:
        def list_namespaces(self): return ["sales"]
        def list_tables(self, ns): return ["orders"]

    monkeypatch.setenv("QUERY_ENGINE", "trino")
    monkeypatch.delenv("TRINO_CATALOG", raising=False)
    monkeypatch.setattr(catalog, "get_catalog_reader", lambda *a: _Reader())

    assert asyncio.run(catalog.list_all_tables()).tables[0].catalog == "iceberg"
