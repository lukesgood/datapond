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
    res = asyncio.get_event_loop().run_until_complete(cat.get_table_details("sales", "orders"))
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
