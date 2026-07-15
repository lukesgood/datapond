"""
Unit tests: Glue/Iceberg-native PII discovery for /governance/pii-report.

The PII scan was Trino-only, so on the live Athena/Glue foundation it returned
None ("not scanned"). _scan_pii_via_catalog enumerates namespaces/tables/columns
via the catalog reader (Glue Data Catalog metadata) and runs the column-name PII
detector — a real scan on the foundation. These tests pin: PII columns are found by
name, a clean catalog scans to [] (not None), and an unreachable catalog is None
(never fabricated).
"""
import sys
import types

import app.api.governance as gov


class _FakeReader:
    def __init__(self, tree, raise_on=None):
        # tree: {namespace: {table: [column_name, ...]}}
        self._tree = tree
        self._raise_on = raise_on or set()

    def list_namespaces(self):
        return list(self._tree.keys())

    def list_tables(self, ns):
        return list(self._tree[ns].keys())

    def get_columns(self, ns, tbl):
        if (ns, tbl) in self._raise_on:
            raise RuntimeError("boom")
        return [{"name": c, "type": "string", "nullable": True} for c in self._tree[ns][tbl]]


def _patch_reader(monkeypatch, reader_or_exc):
    """Inject a fake catalog_backend module so governance's lazy
    `from app.api.catalog_backend import get_catalog_reader` resolves to it."""
    fake = types.ModuleType("app.api.catalog_backend")
    if isinstance(reader_or_exc, Exception):
        def _get():
            raise reader_or_exc
    else:
        def _get():
            return reader_or_exc
    fake.get_catalog_reader = _get
    monkeypatch.setitem(sys.modules, "app.api.catalog_backend", fake)


def test_catalog_scan_finds_pii_by_column_name(monkeypatch):
    reader = _FakeReader({
        "sales": {"customers": ["id", "email", "phone_number"], "widgets": ["id", "sku"]},
    })
    _patch_reader(monkeypatch, reader)
    out = gov._scan_pii_via_catalog()
    assert out is not None
    tables = {e.table for e in out}
    assert tables == {"sales.customers"}          # widgets has no PII-named cols
    cols = {c.column for e in out for c in e.pii_columns}
    assert "email" in cols and "phone_number" in cols


def test_catalog_scan_clean_returns_empty_not_none(monkeypatch):
    _patch_reader(monkeypatch, _FakeReader({"s": {"t": ["id", "sku", "qty"]}}))
    out = gov._scan_pii_via_catalog()
    assert out == []                              # scanned, nothing found (NOT None)


def test_catalog_scan_unreachable_returns_none(monkeypatch):
    _patch_reader(monkeypatch, RuntimeError("glue down"))
    assert gov._scan_pii_via_catalog() is None    # not scanned -> None, no fabrication


def test_catalog_scan_skips_unreadable_table(monkeypatch):
    # one table errors on get_columns -> skipped, the rest still scanned
    reader = _FakeReader(
        {"s": {"good": ["email"], "bad": ["x"]}},
        raise_on={("s", "bad")},
    )
    _patch_reader(monkeypatch, reader)
    out = gov._scan_pii_via_catalog()
    assert out is not None and {e.table for e in out} == {"s.good"}


def test_scan_dispatches_to_catalog_when_glue(monkeypatch):
    monkeypatch.setenv("ICEBERG_CATALOG_BACKEND", "glue")
    _patch_reader(monkeypatch, _FakeReader({"s": {"t": ["email"]}}))
    out = gov._scan_pii_tables()
    assert out is not None and out[0].table == "s.t"
