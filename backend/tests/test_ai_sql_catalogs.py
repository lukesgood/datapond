"""The AI SQL prompt lists every catalog's tables under the name SQL must use.

It printed one engine prefix for every table the reader returned — with a second
catalog, the model was told finance's tables lived in the default catalog and wrote
SQL that read (or failed to find) the wrong table.
"""
from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry


class _R:
    def __init__(self, tree):
        self.tree = tree

    def list_namespaces(self):
        return list(self.tree)

    def list_tables(self, ns):
        return self.tree[ns]

    def get_columns(self, ns, t):
        return [{"name": "id", "type": "bigint"}]


def test_each_catalog_is_listed_with_its_engine_name(monkeypatch):
    import app.api.catalog_backend as cb
    from app.api import ai_sql

    readers = {"iceberg": _R({"sales": ["orders"]}), "finance": _R({"ledger": ["entries"]})}
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg", is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance_trino"),
    ])
    monkeypatch.setattr(cb, "get_catalog_reader", lambda name=None: readers[reg.resolve(name).name])
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    try:
        text = ai_sql._fetch_schema_context()
    finally:
        reg.reset()
    assert "iceberg.sales.orders: id (bigint)" in text
    assert "finance_trino.ledger.entries: id (bigint)" in text
    assert "(catalog: finance_trino)" in text


def test_a_single_catalog_prompt_is_unchanged(monkeypatch):
    import app.api.catalog_backend as cb
    from app.api import ai_sql

    monkeypatch.setenv("QUERY_ENGINE", "athena")
    monkeypatch.setattr(cb, "get_catalog_reader", lambda name=None: _R({"sales": ["orders"]}))
    text = ai_sql._fetch_schema_context()
    assert text == ("Available tables (catalog: AwsDataCatalog):\n"
                    "  AwsDataCatalog.sales.orders: id (bigint)")
