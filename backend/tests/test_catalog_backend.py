import types


class _Field:
    def __init__(self, name, ftype, required):
        self.name = name; self.field_type = ftype; self.required = required


class _Schema:
    def __init__(self, fields): self.fields = fields


class _Snapshot:
    def __init__(self, summary): self.summary = summary


class _Arrow:
    def __init__(self, cols, rows): self.column_names = cols; self._rows = rows
    def to_pylist(self): return [dict(zip(self.column_names, r)) for r in self._rows]


class _Scan:
    # Mirrors pyiceberg: limit is a scan() kwarg, NOT a chainable .limit() method.
    def __init__(self, arrow): self._a = arrow
    def to_arrow(self): return self._a


class _Table:
    def __init__(self):
        self._schema = _Schema([_Field("id", "long", True), _Field("note", "string", False)])
        self.metadata = types.SimpleNamespace(location="s3://b/warehouse/db/t")
        self._snap = _Snapshot({"total-records": "42"})
        self._arrow = _Arrow(["id", "note"], [[1, "a"], [2, None]])
        self.scan_limit = None
    def schema(self): return self._schema
    def current_snapshot(self): return self._snap
    def scan(self, limit=None): self.scan_limit = limit; return _Scan(self._arrow)


class _FakeCatalog:
    def __init__(self): self.table = _Table()
    def list_namespaces(self, *a): return [("sales",), ("ops",)]
    def list_tables(self, ns): return [(ns, "orders")]
    def load_table(self, ident): return self.table


def test_reader_selection(monkeypatch):
    import app.api.catalog_backend as cb
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    assert cb.get_catalog_reader().__class__.__name__ == "GlueCatalogReader"
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "polaris")
    assert cb.get_catalog_reader().__class__.__name__ == "PolarisCatalogReader"


def test_get_table_details_uses_reader(monkeypatch):
    import asyncio
    import app.api.catalog as cat

    class _R:
        def get_columns(self, ns, t): return [{"name": "id", "type": "long", "nullable": False}]
        def get_location(self, ns, t): return "s3://b/t"
        def row_count(self, ns, t): return 7
    monkeypatch.setattr(cat, "get_catalog_reader", lambda: _R())
    res = asyncio.run(cat.get_table_details("sales", "orders"))
    assert res.columns[0].name == "id"
    assert res.location == "s3://b/t"
    assert res.row_count == 7


def test_glue_reader_methods(monkeypatch):
    import app.api.catalog_backend as cb
    fake = _FakeCatalog()
    monkeypatch.setattr(cb, "get_catalog", lambda: fake)
    r = cb.GlueCatalogReader()
    assert set(r.list_namespaces()) == {"sales", "ops"}
    assert r.list_tables("sales") == ["orders"]
    cols = r.get_columns("sales", "orders")
    assert cols[0] == {"name": "id", "type": "long", "nullable": False}
    assert cols[1]["nullable"] is True
    assert r.get_location("sales", "orders") == "s3://b/warehouse/db/t"
    assert r.row_count("sales", "orders") == 42
    prev = r.preview("sales", "orders", 100)
    assert prev["columns"] == ["id", "note"]
    assert prev["rows"] == [[1, "a"], [2, None]]
    assert fake.table.scan_limit == 100      # limit passed via scan(limit=), not .limit()


# ── readers are bound to one registry entry ──────────────────────────────────

import pytest

from app import catalog_registry as reg
from app.catalog_registry import CatalogEntry


@pytest.fixture
def two_polaris(monkeypatch):
    reg.set_entries([
        CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg",
                     config={"warehouse": "iceberg"}, is_default=True),
        CatalogEntry(name="finance", kind="polaris", engine_catalog="finance",
                     config={"warehouse": "finance_wh"}),
    ])
    import app.api.polaris_client as pc
    listing = {"iceberg": {"sales": ["orders"]}, "finance_wh": {"ledger": ["entries"]}}
    monkeypatch.setattr(pc, "list_catalogs", lambda: [{"name": n} for n in listing])
    monkeypatch.setattr(pc, "list_namespaces", lambda cat: list(listing[cat]))
    monkeypatch.setattr(pc, "list_tables", lambda cat, ns: listing[cat][ns])
    yield
    reg.reset()


def test_a_polaris_reader_lists_only_its_own_catalog(two_polaris):
    """It used to merge every Polaris catalog into one list, so `ledger` looked like a
    namespace of the default catalog — and a query against it ran in the wrong one."""
    import app.api.catalog_backend as cb
    assert cb.get_catalog_reader().list_namespaces() == ["sales"]
    fin = cb.get_catalog_reader("finance")
    assert fin.list_namespaces() == ["ledger"]
    assert fin.list_tables("ledger") == ["entries"]
    assert fin.entry.name == "finance"


def test_a_polaris_reader_reads_details_from_its_engine_catalog(two_polaris, monkeypatch):
    import app.api.catalog_backend as cb
    import app.api.trino_util as tu
    seen = {}

    class _Cur:
        def execute(self, sql): seen["sql"] = sql
        def fetchall(self): return [("amount", "decimal", "YES")]

    class _Conn:
        def cursor(self): return _Cur()

    def conn(catalog="iceberg", timeout=30):
        seen["catalog"] = catalog
        return _Conn()

    monkeypatch.setattr(tu, "trino_conn", conn)
    cols = cb.get_catalog_reader("finance").get_columns("ledger", "entries")
    assert cols == [{"name": "amount", "type": "decimal", "nullable": True}]
    assert seen["catalog"] == "finance"
    assert "finance.information_schema.columns" in seen["sql"]


def test_an_unknown_catalog_is_a_value_error(two_polaris):
    import app.api.catalog_backend as cb
    with pytest.raises(ValueError):
        cb.get_catalog_reader("nope")


def test_the_default_glue_reader_uses_the_shared_catalog(monkeypatch):
    import app.api.catalog_backend as cb
    reg.set_entries([CatalogEntry(name="AwsDataCatalog", kind="glue",
                                  engine_catalog="AwsDataCatalog", is_default=True)])
    try:
        fake = _FakeCatalog()
        monkeypatch.setattr(cb, "get_catalog", lambda: fake)
        r = cb.get_catalog_reader()
        assert isinstance(r, cb.GlueCatalogReader)
        assert set(r.list_namespaces()) == {"sales", "ops"}
    finally:
        reg.reset()


def test_a_second_glue_catalog_never_reads_the_default_one(monkeypatch):
    """A non-default Glue entry gets its own pyiceberg catalog built from its config —
    reading the shared default catalog under its name would be silently wrong."""
    import app.api.catalog_backend as cb
    import app.connectors.iceberg_catalog as ic
    reg.set_entries([
        CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="AwsDataCatalog",
                     is_default=True),
        CatalogEntry(name="partner", kind="glue", engine_catalog="partner",
                     config={"catalog_id": "123456789012", "warehouse": "s3://p/w"}),
    ])
    built = {}

    class _Glue:
        def __init__(self, name, **props):
            built.update(props)
        def list_namespaces(self, *a):
            return [("shared",)]

    import pyiceberg.catalog.glue as pg
    monkeypatch.setattr(pg, "GlueCatalog", _Glue)
    monkeypatch.setattr(cb, "get_catalog", lambda: (_ for _ in ()).throw(
        AssertionError("the default catalog must not answer for another")))
    ic.reset_catalog()
    try:
        assert cb.get_catalog_reader("partner").list_namespaces() == ["shared"]
        assert built["glue.id"] == "123456789012"
        assert built["warehouse"] == "s3://p/w"
    finally:
        reg.reset()
        ic.reset_catalog()
