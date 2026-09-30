"""Catalog-read backend abstraction, one reader per registry entry
(app/catalog_registry.py): glue = AWS Glue via pyiceberg; polaris = Polaris HTTP
listing + Trino detail reads. Keeps catalog.py / queries.py engine-agnostic.

A reader reads exactly one catalog. The Polaris reader used to merge every Polaris
catalog into one list, which made a namespace of catalog B look like one of A."""
import os
import logging
import re
import threading
import time

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


# ── Iceberg REST ─────────────────────────────────────────────────────────────
#
# One reader for every catalog that speaks the Iceberg REST protocol: Polaris, Unity
# Catalog, Snowflake Open Catalog, Nessie, S3 Tables (SigV4, signing name s3tables)
# and Glue's own endpoint (SigV4, signing name glue, warehouse = account id) — the
# last two measured against a real account before this was written (spec §5).
#
# A catalog that does not answer must not stall a listing of every catalog, so each
# HTTP call carries a timeout, and a catalog that failed to build is not retried for
# REST_FAILURE_TTL_SECONDS: listings skip it (the P1 pattern) instead of waiting on it
# once per request.

REST_TIMEOUT_SECONDS = 10
REST_CACHE_TTL_SECONDS = 300
REST_FAILURE_TTL_SECONDS = 30

_rest_lock = threading.Lock()
_rest_cache: dict = {}      # entry name -> (fingerprint, catalog, built_at)
_rest_failures: dict = {}   # entry name -> (fingerprint, failed_at, sanitised message)


def reset_rest_cache(name=None) -> None:
    """Forget built REST catalogs (all, or one entry's) and remembered failures."""
    with _rest_lock:
        if name is None:
            _rest_cache.clear()
            _rest_failures.clear()
        else:
            _rest_cache.pop(name, None)
            _rest_failures.pop(name, None)


_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@")
_KEYED_VALUE = re.compile(
    r"(?i)\b(token|access_token|refresh_token|credential|client_secret|secret|password|"
    r"x-amz-signature|x-amz-security-token|signature)(\s*[=:]\s*)[^\s&,;\"']+")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")


def sanitize_error(text, secrets=()) -> str:
    """An error message fit to log and to show an admin: the credential, userinfo in
    URLs, `token=`/`credential=` values and Authorization values are cut out."""
    msg = str(text)
    for s in secrets or ():
        if s:
            msg = msg.replace(s, "[redacted]")
            for part in str(s).split(":"):
                if len(part) >= 4:
                    msg = msg.replace(part, "[redacted]")
    msg = _URL_USERINFO.sub(r"\1[redacted]@", msg)
    msg = _KEYED_VALUE.sub(r"\1\2[redacted]", msg)
    msg = _BEARER.sub(r"\1 [redacted]", msg)
    return msg[:500]


def _bound_session(session, timeout):
    """Give a requests session a default timeout (requests has none): pyiceberg never
    passes one, and a catalog that accepts the connection and never answers would
    hold the calling thread for good. An explicit timeout still wins."""
    original = session.request

    def request(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return original(method, url, **kwargs)
    session.request = request
    return session


def _new_rest_catalog(props):
    """Build a pyiceberg RestCatalog whose every HTTP call — including the /config
    fetch and the OAuth token exchange the constructor makes — has a timeout."""
    from pyiceberg.catalog.rest import RestCatalog

    class _BoundedRestCatalog(RestCatalog):
        def _config_headers(self, session):
            # The first thing _create_session does with a new session, before any call.
            _bound_session(session, (5, REST_TIMEOUT_SECONDS))
            return super()._config_headers(session)

    return _BoundedRestCatalog(name="datapond-rest", **props)


def rest_properties(entry, secret):
    """pyiceberg properties for an iceberg_rest entry, or a glue entry with via_rest."""
    cfg = entry.config or {}
    props = {}
    if entry.kind == "glue":
        region = cfg.get("region") or os.getenv("S3_REGION", "us-east-1")
        props.update({
            "uri": f"https://glue.{region}.amazonaws.com/iceberg",
            "warehouse": str(cfg.get("catalog_id") or cfg.get("warehouse") or ""),
            "rest.sigv4-enabled": "true",
            "rest.signing-name": "glue",
            "rest.signing-region": region,
            "s3.region": region,
        })
    else:
        props["uri"] = cfg["uri"]
        for key in ("warehouse", "scope", "prefix"):
            if cfg.get(key):
                props[key] = str(cfg[key])
        if cfg.get("sigv4"):
            props["rest.sigv4-enabled"] = "true"
            props["rest.signing-name"] = str(cfg.get("signing_name") or "execute-api")
            if cfg.get("signing_region"):
                props["rest.signing-region"] = str(cfg["signing_region"])
                props["s3.region"] = str(cfg["signing_region"])
    if secret:
        # OAuth client credentials are `id:secret`; anything else is a bearer token.
        if ":" in secret:
            props["credential"] = secret
        else:
            props["token"] = secret
    return props


def _fingerprint(props) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(props, sort_keys=True).encode()).hexdigest()


def uses_rest(entry) -> bool:
    if entry.kind == "iceberg_rest":
        return True
    # The default Glue entry stays on the Glue API: writes share its catalog, and the
    # Glue API is what reads Lake Formation resource links and catalog ids today.
    return entry.kind == "glue" and bool((entry.config or {}).get("via_rest")) \
        and not entry.is_default


def get_rest_catalog(entry):
    """The cached RestCatalog for `entry`, rebuilt when its config or secret changes
    or after REST_CACHE_TTL_SECONDS. A build that failed is remembered briefly and
    re-raised without another network attempt."""
    from app import catalog_registry
    secret = catalog_registry.secret_for(entry)
    props = rest_properties(entry, secret)
    fp = _fingerprint(props)
    now = time.monotonic()
    with _rest_lock:
        hit = _rest_cache.get(entry.name)
        if hit and hit[0] == fp and now - hit[2] < REST_CACHE_TTL_SECONDS:
            return hit[1]
        failed = _rest_failures.get(entry.name)
        if failed and failed[0] == fp and now - failed[1] < REST_FAILURE_TTL_SECONDS:
            raise CatalogUnavailable(failed[2])
    try:
        cat = _new_rest_catalog(props)
    except Exception as e:
        msg = sanitize_error(f"catalog '{entry.name}' unavailable: {e}", [secret])
        logger.warning("[catalogs] %s", msg)
        with _rest_lock:
            _rest_failures[entry.name] = (fp, now, msg)
        raise CatalogUnavailable(msg) from None
    with _rest_lock:
        _rest_cache[entry.name] = (fp, cat, now)
        _rest_failures.pop(entry.name, None)
    return cat


class CatalogUnavailable(RuntimeError):
    """A catalog that could not be reached; the message is already sanitised."""


def _is_network_error(e) -> bool:
    if isinstance(e, (ConnectionError, TimeoutError)):
        return True
    try:
        import requests
        return isinstance(e, (requests.ConnectionError, requests.Timeout))
    except ImportError:
        return False


class IcebergRestReader:
    """Reads one Iceberg REST catalog. Tables are keyed by the namespace asked for,
    never the identifier's own: Glue's REST endpoint answers a resource-link namespace
    with identifiers under the namespace the link points at (spec §5)."""

    def __init__(self, entry):
        self.entry = entry

    def __repr__(self):
        return f"IcebergRestReader({self.entry.name!r})"

    def _catalog(self):
        return get_rest_catalog(self.entry)

    def _call(self, fn, *args):
        from app import catalog_registry
        try:
            return fn(*args)
        except CatalogUnavailable:
            raise
        except Exception as e:
            msg = sanitize_error(f"catalog '{self.entry.name}': {e}",
                                 [catalog_registry.secret_for(self.entry)])
            if _is_network_error(e):
                # Built once, unreachable now: stop waiting on it for a while too.
                with _rest_lock:
                    hit = _rest_cache.pop(self.entry.name, None)
                    if hit:
                        _rest_failures[self.entry.name] = (hit[0], time.monotonic(), msg)
                logger.warning("[catalogs] %s", msg)
            raise CatalogUnavailable(msg) from None

    @staticmethod
    def _ns(namespace):
        return tuple(str(namespace).split("."))

    def list_namespaces(self):
        cat = self._catalog()
        return [".".join(ns) for ns in self._call(cat.list_namespaces)]

    def list_tables(self, namespace):
        cat = self._catalog()
        return [t[-1] for t in self._call(cat.list_tables, self._ns(namespace))]

    def _load(self, namespace, table):
        cat = self._catalog()
        return self._call(cat.load_table, (*self._ns(namespace), table))

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
        arrow = self._load(namespace, table).scan(limit=min(limit, 500)).to_arrow()
        cols = list(arrow.column_names)
        rows = [[d.get(c) for c in cols] for d in arrow.to_pylist()]
        return {"columns": cols, "rows": rows}


def reader_for_entry(entry):
    """The reader for one registry entry, enabled or not (the admin test route tries a
    disabled entry before an admin enables it)."""
    if uses_rest(entry):
        return IcebergRestReader(entry)
    if entry.kind == "glue":
        return GlueCatalogReader(entry)
    if entry.kind == "polaris":
        return PolarisCatalogReader(entry)
    raise ValueError(f"catalog '{entry.name}' ({entry.kind}) has no reader")


def get_catalog_reader(catalog=None):
    """The reader for registry entry `catalog` (name or engine catalog name; None is
    the default). Raises ValueError (UnknownCatalog) for a catalog the registry does
    not have enabled — routes turn that into a 400."""
    from app.catalog_registry import resolve
    return reader_for_entry(resolve(catalog))
