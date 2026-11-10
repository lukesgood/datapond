"""Trino-backed sources: the names and the catalog file.

A connection of a Trino-backed type (PostgreSQL, MySQL, SQL Server, Oracle, MongoDB) is a
Trino catalog `src_<slug>`. Everything here is pure: the slug the catalog is named with,
the environment variable its password arrives through, the `<catalog>.properties` text
Trino reads at startup, and the normalisation of the legacy `database_url` payload into
the PostgreSQL/MySQL form. The password never appears in the properties text; Trino
substitutes `${ENV:...}` from the credentials Secret (app/connectors/trino_catalogs.py).

Property names are Trino 482's: the JDBC connectors take `connection-url`,
`connection-user`, `connection-password`; MongoDB takes `mongodb.connection-url`, whose
userinfo is percent-encoded, so the stored env value for MongoDB is the quoted password.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import quote_plus, unquote, urlsplit

from pydantic import Field

from .base import ConnectorConfig, ConnectorType

TRINO_ENGINE_TYPES = frozenset({
    ConnectorType.POSTGRESQL, ConnectorType.MYSQL, ConnectorType.SQLSERVER,
    ConnectorType.ORACLE, ConnectorType.MONGODB,
})

CATALOG_PREFIX = "src_"
MAX_CATALOG_LEN = 32
# Trino catalog names the chart already renders; a source may not shadow them.
RESERVED_CATALOGS = frozenset({"iceberg", "postgres", "system", "jmx", "memory", "tpch"})

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DEFAULT_PORT = {ConnectorType.POSTGRESQL: 5432, ConnectorType.MYSQL: 3306}


def engine_of(t: ConnectorType) -> str:
    """"trino" for a type whose source is read by a Trino connector, "python" otherwise.
    `database_url` is "trino" because it normalises to PostgreSQL or MySQL."""
    if t in TRINO_ENGINE_TYPES or t == ConnectorType.DATABASE_URL:
        return "trino"
    return "python"


def source_slug(name: str) -> str:
    """`src_<slug>` from a connection name: NFKD-folded ASCII, lowercase, runs of anything
    but [a-z0-9] become one underscore, trimmed, the whole at most 32 characters. A name
    with no ASCII letters or digits gets a stable 8-hex suffix instead."""
    folded = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")
    if not slug:
        slug = hashlib.sha1(str(name or "").encode("utf-8")).hexdigest()[:8]
    return (CATALOG_PREFIX + slug)[:MAX_CATALOG_LEN].rstrip("_")


def unique_slug(base: str, taken: Iterable[str]) -> str:
    """`base`, or `base_2`, `base_3`, … until it clashes with nothing in `taken`
    (case-insensitive); the result stays within 32 characters."""
    used = {str(t).lower() for t in taken}
    if base.lower() not in used:
        return base
    n = 2
    while True:
        suffix = f"_{n}"
        candidate = base[:MAX_CATALOG_LEN - len(suffix)].rstrip("_") + suffix
        if candidate.lower() not in used:
            return candidate
        n += 1


def credential_env(catalog: str) -> str:
    """The environment variable Trino reads the catalog's password from."""
    body = catalog[len(CATALOG_PREFIX):] if catalog.startswith(CATALOG_PREFIX) else catalog
    return f"SRC_{body.upper()}_PASSWORD"


class TrinoSourceConfig(ConnectorConfig):
    """One Trino-backed connection as the console submits it."""
    host: str
    port: int
    database: str = ""
    username: str
    password: str
    ssl: bool = False
    schema_name: Optional[str] = Field(default=None, alias="schema")
    auth_source: str = "admin"          # MongoDB authSource
    catalog: Optional[str] = None       # src_<slug>, set once the connection exists

    model_config = {"populate_by_name": True}


def _safe(field: str, value, *, allow_empty: bool = False) -> str:
    text = "" if value is None else str(value)
    if text == "" and allow_empty:
        return text
    if not _SAFE_VALUE.match(text):
        raise ValueError(f"{field} may not contain spaces, quotes, slashes or line breaks: "
                         f"only letters, digits, '.', '_' and '-'.")
    return text


def _port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError("port must be a number.")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535.")
    return port


def render_catalog_properties(t: ConnectorType, catalog: str, config: dict) -> str:
    """The `<catalog>.properties` text for one connection. The password is referenced as
    `${ENV:<credential_env(catalog)>}` and never written here."""
    if t not in TRINO_ENGINE_TYPES:
        raise ValueError(f"{t.value} is not read through a Trino connector.")
    host = _safe("host", config.get("host"))
    port = _port(config.get("port"))
    database = _safe("database", config.get("database"), allow_empty=(t == ConnectorType.MYSQL))
    ssl = bool(config.get("ssl"))
    env = "${ENV:" + credential_env(catalog) + "}"

    if t == ConnectorType.MONGODB:
        # The user travels inside a URL, percent-encoded, so any printable text is fine.
        user = str(config.get("username") or "")
        if not user or _CONTROL.search(user):
            raise ValueError("username is required and may not contain control characters.")
        auth_source = _safe("auth_source", config.get("auth_source") or "admin")
        url = (f"mongodb://{quote_plus(user)}:{env}@{host}:{port}/{database}"
               f"?authSource={auth_source}" + ("&tls=true" if ssl else ""))
        lines = ["connector.name=mongodb", f"mongodb.connection-url={url}"]
        return "\n".join(lines) + "\n"

    user = _safe("username", config.get("username"))
    if t == ConnectorType.POSTGRESQL:
        if not database:
            raise ValueError("database is required for PostgreSQL.")
        url = f"jdbc:postgresql://{host}:{port}/{database}" + ("?sslmode=require" if ssl else "")
        name, extra = "postgresql", []
    elif t == ConnectorType.MYSQL:
        url = f"jdbc:mysql://{host}:{port}" + ("?sslMode=REQUIRED" if ssl else "")
        name, extra = "mysql", []
    elif t == ConnectorType.SQLSERVER:
        if not database:
            raise ValueError("database is required for SQL Server.")
        url = (f"jdbc:sqlserver://{host}:{port};databaseName={database};"
               f"encrypt={'true' if ssl else 'false'};trustServerCertificate=true")
        name, extra = "sqlserver", []
    else:  # ORACLE — `database` is the service name
        if not database:
            raise ValueError("database (the Oracle service name) is required.")
        url = f"jdbc:oracle:thin:@{host}:{port}/{database}"
        name, extra = "oracle", ["oracle.number.default-scale=10",
                                 "oracle.number.rounding-mode=HALF_UP"]
    lines = [f"connector.name={name}", f"connection-url={url}",
             f"connection-user={user}", f"connection-password={env}", *extra]
    return "\n".join(lines) + "\n"


def credential_value(t: ConnectorType, config: dict) -> str:
    """What the credentials Secret stores under `credential_env(catalog)`: the password,
    percent-encoded for MongoDB because it travels inside a URL there."""
    password = str(config.get("password") or "")
    return quote_plus(password) if t == ConnectorType.MONGODB else password


def normalise_type_and_config(t: ConnectorType, config: dict) -> Tuple[ConnectorType, dict]:
    """A `database_url` payload becomes the PostgreSQL or MySQL form; every other type
    passes through with `port` coerced to int. Unknown URL schemes are refused."""
    config = dict(config or {})
    if t != ConnectorType.DATABASE_URL:
        if "port" in config and config["port"] not in (None, ""):
            config["port"] = _port(config["port"])
        return t, config
    url = str(config.get("database_url") or "").strip()
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0].lower()
    kind = {"postgresql": ConnectorType.POSTGRESQL, "postgres": ConnectorType.POSTGRESQL,
            "mysql": ConnectorType.MYSQL}.get(scheme)
    if kind is None:
        raise ValueError("database_url must be a postgresql:// or mysql:// URL; other databases "
                         "are added as their own source type.")
    if not parts.hostname:
        raise ValueError("database_url has no host.")
    out: Dict[str, object] = {
        "host": parts.hostname,
        "port": parts.port or _DEFAULT_PORT[kind],
        "database": parts.path.lstrip("/"),
        "username": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "ssl": "sslmode=require" in (parts.query or "") or "ssl=true" in (parts.query or ""),
    }
    for key in ("name", "description", "tags"):
        if key in config:
            out[key] = config[key]
    return kind, out


# ── the connector ─────────────────────────────────────────────────────────────
#
# One class for the five types. With `config.catalog` set (the connection exists and its
# catalog is projected) every read goes through Trino; before that, tables and columns
# come from the driver probe so the wizard can finish. The test always uses the driver:
# it answers "is the password right" even while Trino is restarting.

import asyncio  # noqa: E402
from typing import Any, List  # noqa: E402

import logging  # noqa: E402
from datetime import datetime  # noqa: E402

from .base import (  # noqa: E402
    BaseConnector, ColumnSchema, ConnectionTestResult, SyncJobStatus, SyncMode, SyncStatus, TableSchema)

logger = logging.getLogger(__name__)

_IDENT = re.compile(r"^[A-Za-z0-9_$]+$")


def _ident(value: str) -> str:
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ValueError(f"Not a bare identifier: {value!r}")
    return value


class TrinoSourceConnector(BaseConnector):
    def __init__(self, config: TrinoSourceConfig):
        super().__init__(config)
        self.config: TrinoSourceConfig = config
        self.source_type: ConnectorType = ConnectorType(config.connector_type)
        self._connect = None            # tests inject; default is trino_util.trino_conn

    # Trino access
    def _cursor(self, timeout: int = 30):
        connect = self._connect
        if connect is None:
            from app.api.trino_util import trino_conn
            connect = trino_conn
        return connect(catalog=self.catalog, timeout=timeout).cursor()

    @property
    def catalog(self) -> Optional[str]:
        return _ident(self.config.catalog) if self.config.catalog else None

    def _split(self, table_name: str):
        from . import probe
        schema, name = probe.split_table(self.source_type, self.config, table_name)
        return _ident(schema), _ident(name)

    async def test_connection(self) -> ConnectionTestResult:
        from . import probe
        return await probe.atest(self.source_type, self.config)

    def _tables_via_trino(self) -> List[str]:
        from app.api.catalog_backend import SOURCE_SYSTEM_SCHEMAS
        cur = self._cursor()
        cur.execute(f"SHOW SCHEMAS FROM {self.catalog}")
        schemas = [r[0] for r in cur.fetchall() if r[0] and r[0].lower() not in SOURCE_SYSTEM_SCHEMAS]
        out: List[str] = []
        for schema in schemas:
            if not _IDENT.match(schema):
                continue
            cur = self._cursor()
            cur.execute(f"SHOW TABLES FROM {self.catalog}.{schema}")
            out.extend(f"{schema}.{r[0]}" for r in cur.fetchall())
        return out

    async def get_tables(self) -> List[str]:
        from . import probe
        if not self.catalog:
            return await probe.alist_tables(self.source_type, self.config)
        return await asyncio.to_thread(self._tables_via_trino)

    def _columns_via_trino(self, schema: str, name: str) -> List[ColumnSchema]:
        cur = self._cursor()
        cur.execute(
            f"SELECT column_name, data_type, is_nullable FROM {self.catalog}.information_schema.columns "
            f"WHERE table_schema='{schema}' AND table_name='{name}' ORDER BY ordinal_position")
        return [ColumnSchema(name=r[0], type=r[1], nullable=(str(r[2]).upper() == "YES"))
                for r in cur.fetchall()]

    async def get_schema(self, table_name: str) -> TableSchema:
        from . import probe
        schema, name = self._split(table_name)
        if not self.catalog:
            cols = await probe.acolumns(self.source_type, self.config, f"{schema}.{name}")
        else:
            cols = await asyncio.to_thread(self._columns_via_trino, schema, name)
        return TableSchema(table_name=table_name, columns=cols, row_count=None)

    def _read_via_trino(self, schema: str, name: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        cur = self._cursor()
        sql = f"SELECT * FROM {self.catalog}.{schema}.{name}"
        if offset:
            sql += f" OFFSET {int(offset)}"
        sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    async def read_data(self, table_name: str, limit: int = 1000, offset: int = 0,
                        **kwargs) -> List[Dict[str, Any]]:
        schema, name = self._split(table_name)
        if not self.catalog:
            raise RuntimeError("This source is not queryable yet: its Trino catalog is still "
                               "being projected. Try again in a minute.")
        return await asyncio.to_thread(self._read_via_trino, schema, name,
                                       max(1, min(int(limit), 10000)), max(0, int(offset)))

    # ── sync: Trino copies the source into Iceberg ───────────────────────────

    def _target(self, source_table: str, target_table: Optional[str]):
        from . import trino_sync
        return trino_sync.target_ref(source_table, target_table)

    def _source_columns(self, cur, schema: str, name: str):
        cur.execute(
            f"SELECT column_name, data_type, is_nullable FROM {self.catalog}.information_schema.columns "
            f"WHERE table_schema='{schema}' AND table_name='{name}' ORDER BY ordinal_position")
        return [(r[0], r[1]) for r in cur.fetchall()]

    @staticmethod
    def _target_columns(cur, target):
        cur.execute(
            f"SELECT column_name, data_type FROM {target.catalog}.information_schema.columns "
            f"WHERE table_schema='{target.namespace}' AND table_name='{target.table}' "
            f"ORDER BY ordinal_position")
        return [(r[0], r[1]) for r in cur.fetchall()]

    @staticmethod
    def _count(cur) -> int:
        row = cur.fetchone()
        try:
            return int(row[0]) if row and row[0] is not None else 0
        except (TypeError, ValueError):
            return 0

    def _run_sync(self, source_table, target_table, sync_mode, incremental_column, last_value,
                  on_step, partition_spec, key_columns, pii_columns):
        """Synchronous; one Trino connection for the whole job."""
        from . import trino_sync
        from app.catalog_registry import TableRef

        def step(name, message, extra=None):
            if on_step:
                on_step(name, message, extra or {})

        if not self.catalog:
            raise RuntimeError("This source has no Trino catalog yet (it is still being "
                               "projected). Try again in a minute.")
        schema, name = self._split(source_table)
        source = TableRef(self.catalog, schema, name)
        target = self._target(source_table, target_table)
        if incremental_column:
            _ident(incremental_column)

        step("connect", f"Connecting to Trino ({self.catalog})…")
        cur = self._cursor(timeout=3600)
        self._last_cursor = cur

        step("introspect", f"Reading columns of {source.sql()}…")
        columns = self._source_columns(cur, schema, name)
        if not columns:
            raise RuntimeError(f"{source.sql()} has no columns Trino can see (does the table exist?).")
        existing = self._target_columns(cur, target)

        step("create", f"Ensuring {target.sql()} exists…")
        cur.execute(trino_sync.build_create(target, columns, partition_spec))

        step("evolve", "Adding new source columns to the target…")
        if existing:
            for stmt in trino_sync.build_evolve(target, existing, columns):
                cur.execute(stmt)

        incremental = sync_mode == SyncMode.INCREMENTAL and bool(incremental_column)
        max_value = last_value
        masked = sorted(trino_sync.pii_set(columns, pii_columns))
        if incremental:
            step("load", f"Loading rows of {source.sql()} newer than the watermark…",
                 {"incremental_column": incremental_column, "last_value": last_value,
                  "pii_masked": masked})
            stmts, watermark = trino_sync.build_incremental(
                target, source, columns, pii_columns, incremental_column, last_value, key_columns,
                existing=existing)
            rows = 0
            for sql, params in stmts:
                cur.execute(sql, params) if params else cur.execute(sql)
                rows += self._count(cur)
            step("watermark", "Reading the new watermark…")
            cur.execute(watermark)
            row = cur.fetchone()
            if row and row[0] is not None:
                max_value = str(row[0])
        else:
            step("load", f"Replacing {target.sql()} with {source.sql()}…", {"pii_masked": masked})
            (replace,) = trino_sync.build_full(target, source, columns, pii_columns,
                                               existing=existing, partition_spec=partition_spec)
            cur.execute(replace)
            rows = self._count(cur)
        return rows, max_value, target

    async def sync_to_iceberg(self, source_table: str, target_table: str,
                              sync_mode: SyncMode = SyncMode.FULL,
                              incremental_column: Optional[str] = None,
                              last_value: Optional[Any] = None, on_step=None,
                              partition_spec: Optional[list] = None,
                              key_columns: Optional[list] = None,
                              pii_columns: Optional[list] = None) -> SyncJobStatus:
        from . import probe
        started_at = datetime.utcnow()
        try:
            rows, max_value, target = await asyncio.to_thread(
                self._run_sync, source_table, target_table, sync_mode, incremental_column,
                last_value, on_step, partition_spec, key_columns, pii_columns)
            return SyncJobStatus(
                status=SyncStatus.SUCCESS, started_at=started_at, completed_at=datetime.utcnow(),
                rows_processed=rows, rows_failed=0,
                metadata={"source_table": source_table, "target_table": target_table,
                          "sync_mode": sync_mode.value, "iceberg_table": target.sql(),
                          "max_value": max_value, "engine": "trino"})
        except Exception as e:
            message = probe.scrub(str(e) or type(e).__name__, self.config)[:1000]
            logger.warning("[trino_sync] %s → %s failed: %s", source_table, target_table, message)
            return SyncJobStatus(status=SyncStatus.FAILED, started_at=started_at,
                                 completed_at=datetime.utcnow(), rows_processed=0, rows_failed=0,
                                 error_message=message)
