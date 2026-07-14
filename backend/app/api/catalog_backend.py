"""Catalog-read backend abstraction. Selected by ICEBERG_CATALOG_BACKEND
(glue = AWS Glue via the shared pyiceberg catalog; polaris = existing Polaris
HTTP + Trino). Keeps catalog.py / queries.py engine-agnostic."""
import os
import logging

logger = logging.getLogger(__name__)


def get_catalog():  # thin indirection so tests can monkeypatch the import site
    from app.connectors.iceberg_catalog import get_catalog as _gc
    return _gc()


class GlueCatalogReader:
    """Reads catalog metadata straight from the shared pyiceberg GlueCatalog —
    list / load_table / schema / scan / snapshot. No Trino, no separate boto3 client."""

    def list_namespaces(self):
        return [".".join(ns) for ns in get_catalog().list_namespaces()]

    def list_tables(self, namespace):
        return [t[-1] for t in get_catalog().list_tables(namespace)]

    def _load(self, namespace, table):
        return get_catalog().load_table(f"{namespace}.{table}")

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
        arrow = self._load(namespace, table).scan().limit(min(limit, 500)).to_arrow()
        cols = list(arrow.column_names)
        rows = [[d.get(c) for c in cols] for d in arrow.to_pylist()]
        return {"columns": cols, "rows": rows}


class PolarisCatalogReader:
    """Existing Polaris HTTP listing + Trino detail reads, wrapped behind the
    CatalogReader interface so the endpoints stay backend-agnostic."""

    def list_namespaces(self):
        from app.api.polaris_client import list_catalogs, list_namespaces
        out = []
        for pcat in list_catalogs():
            try:
                out.extend(list_namespaces(pcat["name"]))
            except Exception:
                continue
        return out

    def list_tables(self, namespace):
        from app.api.polaris_client import list_catalogs, list_tables
        out = []
        for pcat in list_catalogs():
            try:
                out.extend(list_tables(pcat["name"], namespace))
            except Exception:
                continue
        return out

    def get_columns(self, namespace, table, catalog="iceberg"):
        from app.api.trino_util import trino_conn
        cur = trino_conn(catalog=catalog, timeout=15).cursor()
        cur.execute(
            f"SELECT column_name, data_type, is_nullable FROM {catalog}.information_schema.columns "
            f"WHERE table_schema='{namespace}' AND table_name='{table}' ORDER BY ordinal_position")
        return [{"name": r[0], "type": r[1], "nullable": (r[2].upper() == "YES")} for r in cur.fetchall()]

    def get_location(self, namespace, table, catalog="iceberg"):
        import re
        from app.api.trino_util import trino_conn
        try:
            cur = trino_conn(catalog=catalog, timeout=15).cursor()
            cur.execute(f"SHOW CREATE TABLE {catalog}.{namespace}.{table}")
            ddl = cur.fetchone()[0]
            m = re.search(r"location\s*=\s*'([^']+)'", ddl, re.IGNORECASE)
            return m.group(1) if m else None
        except Exception:
            return None

    def row_count(self, namespace, table, catalog="iceberg"):
        from app.api.trino_util import trino_conn
        try:
            cur = trino_conn(catalog=catalog, timeout=15).cursor()
            cur.execute(f"SELECT COUNT(*) FROM {catalog}.{namespace}.{table}")
            return cur.fetchone()[0]
        except Exception:
            return None

    def preview(self, namespace, table, limit, catalog="iceberg"):
        from app.api.trino_util import trino_conn
        cur = trino_conn(catalog=catalog, timeout=15).cursor()
        cur.execute(f"SELECT * FROM {catalog}.{namespace}.{table} LIMIT {min(limit, 500)}")
        rows_raw = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return {"columns": cols, "rows": [list(r) for r in rows_raw]}


def get_catalog_reader():
    backend = os.getenv("ICEBERG_CATALOG_BACKEND", "polaris").strip().lower()
    return GlueCatalogReader() if backend == "glue" else PolarisCatalogReader()
