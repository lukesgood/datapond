"""Catalog-read backend abstraction, one reader per registry entry
(app/catalog_registry.py): glue = AWS Glue via pyiceberg; polaris = Polaris HTTP
listing + Trino detail reads. Keeps catalog.py / queries.py engine-agnostic.

A reader reads exactly one catalog. The Polaris reader used to merge every Polaris
catalog into one list, which made a namespace of catalog B look like one of A."""
import os
import logging
import re

logger = logging.getLogger(__name__)


def get_catalog():  # thin indirection so tests can monkeypatch the import site
    from app.connectors.iceberg_catalog import get_catalog as _gc
    return _gc()


def _default_entry():
    from app.catalog_registry import default_entry
    return default_entry()


class GlueCatalogReader:
    """Reads catalog metadata straight from pyiceberg's GlueCatalog — list /
    load_table / schema / scan / snapshot. No Trino, no separate boto3 client.
    The default entry reads the shared catalog; another entry reads its own."""

    def __init__(self, entry=None):
        self.entry = entry or _default_entry()

    def _catalog(self):
        if self.entry.is_default:
            return get_catalog()
        from app.connectors.iceberg_catalog import get_catalog_for
        return get_catalog_for(self.entry)

    def list_namespaces(self):
        return [".".join(ns) for ns in self._catalog().list_namespaces()]

    def list_tables(self, namespace):
        return [t[-1] for t in self._catalog().list_tables(namespace)]

    def _load(self, namespace, table):
        return self._catalog().load_table(f"{namespace}.{table}")

    def get_columns(self, namespace, table):
        return [
            {"name": f.name, "type": str(f.field_type), "nullable": not f.required}
            for f in self._load(namespace, table).schema().fields
        ]

    def get_location(self, namespace, table):
        try:
            return self._load(namespace, table).metadata.location
        except Exception:
            return None

    def row_count(self, namespace, table):
        snap = self._load(namespace, table).current_snapshot()
        if snap and getattr(snap, "summary", None) and "total-records" in snap.summary:
            return int(snap.summary["total-records"])
        return None

    def preview(self, namespace, table, limit):
        # pyiceberg limit is a scan() kwarg — there is no chainable .limit().
        arrow = self._load(namespace, table).scan(limit=min(limit, 500)).to_arrow()
        cols = list(arrow.column_names)
        rows = [[d.get(c) for c in cols] for d in arrow.to_pylist()]
        return {"columns": cols, "rows": rows}


# Trino takes these names inside SQL text, so only a bare identifier gets there. A
# namespace or table name is caller input — the catalog routes, and the MCP tool that
# describes a table — and a quote in one of them was a UNION into any other table.
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def safe_identifier(value) -> str:
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ValueError(f"Not a bare identifier: {value!r}")
    return value


class PolarisCatalogReader:
    """Polaris HTTP listing of one Polaris catalog (the entry's `warehouse`) + Trino
    detail reads against the entry's engine catalog."""

    def __init__(self, entry=None):
        self.entry = entry or _default_entry()
        self.polaris_catalog = (self.entry.config or {}).get("warehouse") or self.entry.name
        self.engine_catalog = safe_identifier(self.entry.engine_catalog)

    def list_namespaces(self):
        from app.api import polaris_client
        return list(polaris_client.list_namespaces(self.polaris_catalog))

    def list_tables(self, namespace):
        from app.api import polaris_client
        return list(polaris_client.list_tables(self.polaris_catalog, namespace))

    def get_columns(self, namespace, table, catalog=None):
        catalog = catalog or self.engine_catalog
        for name in (namespace, table, catalog):
            safe_identifier(name)
        from app.api.trino_util import trino_conn
        cur = trino_conn(catalog=catalog, timeout=15).cursor()
        cur.execute(
            f"SELECT column_name, data_type, is_nullable FROM {catalog}.information_schema.columns "
            f"WHERE table_schema='{namespace}' AND table_name='{table}' ORDER BY ordinal_position")
        return [{"name": r[0], "type": r[1], "nullable": (r[2].upper() == "YES")} for r in cur.fetchall()]

    def get_location(self, namespace, table, catalog=None):
        catalog = catalog or self.engine_catalog
        for name in (namespace, table, catalog):
            safe_identifier(name)
        from app.api.trino_util import trino_conn
        try:
            cur = trino_conn(catalog=catalog, timeout=15).cursor()
            cur.execute(f"SHOW CREATE TABLE {catalog}.{namespace}.{table}")
            ddl = cur.fetchone()[0]
            m = re.search(r"location\s*=\s*'([^']+)'", ddl, re.IGNORECASE)
            return m.group(1) if m else None
        except Exception:
            return None

    def row_count(self, namespace, table, catalog=None):
        catalog = catalog or self.engine_catalog
        for name in (namespace, table, catalog):
            safe_identifier(name)
        from app.api.trino_util import trino_conn
        try:
            cur = trino_conn(catalog=catalog, timeout=15).cursor()
            cur.execute(f"SELECT COUNT(*) FROM {catalog}.{namespace}.{table}")
            return cur.fetchone()[0]
        except Exception:
            return None

    def preview(self, namespace, table, limit, catalog=None):
        catalog = catalog or self.engine_catalog
        for name in (namespace, table, catalog):
            safe_identifier(name)
        from app.api.trino_util import trino_conn
        cur = trino_conn(catalog=catalog, timeout=15).cursor()
        cur.execute(f"SELECT * FROM {catalog}.{namespace}.{table} LIMIT {min(limit, 500)}")
        rows_raw = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return {"columns": cols, "rows": [list(r) for r in rows_raw]}


def get_catalog_reader(catalog=None):
    """The reader for registry entry `catalog` (name or engine catalog name; None is
    the default). Raises ValueError (UnknownCatalog) for a catalog the registry does
    not have enabled — routes turn that into a 400."""
    from app.catalog_registry import resolve
    entry = resolve(catalog)
    if entry.kind == "glue":
        return GlueCatalogReader(entry)
    if entry.kind == "polaris":
        return PolarisCatalogReader(entry)
    raise ValueError(f"catalog '{entry.name}' ({entry.kind}) has no reader yet")
