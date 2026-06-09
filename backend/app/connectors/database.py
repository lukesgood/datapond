"""
Database connectors for PostgreSQL, MySQL, SQL Server, and other JDBC/ODBC databases.

Supports:
- Connection pooling
- SSL/TLS connections
- Incremental loading
- Schema auto-detection
- Custom SQL queries
"""

import asyncio
import os
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy import create_engine, MetaData, Table, inspect, text
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import SQLAlchemyError
import pandas as pd

from .base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorType,
    ConnectorRegistry,
    ConnectionTestResult,
    TableSchema,
    ColumnSchema,
    SyncMode,
    SyncJobStatus,
    SyncStatus
)

logger = logging.getLogger(__name__)


class DatabaseConfig(ConnectorConfig):
    """Configuration for database connectors"""
    host: str
    port: int
    database: str
    username: str
    password: str
    ssl: bool = False
    schema: Optional[str] = None  # For databases that support schemas (PostgreSQL, SQL Server)
    connection_params: Dict[str, Any] = {}


# Rows read per batch. Bounds backend memory regardless of source table size.
INGEST_CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "50000"))


def _mask_pii_in_chunk(chunk, pii_columns) -> int:
    """Mask configured columns' string cells (pii_ko) BEFORE they're written to Iceberg —
    sensitive data never lands raw in the lakehouse. pii_columns == ['*'] scans all
    string columns; otherwise only the named ones. Returns # of cells changed. In-place."""
    if not pii_columns:
        return 0
    from app.guardrails import pii_ko
    cols = (list(chunk.columns) if pii_columns == ["*"]
            else [c for c in pii_columns if c in chunk.columns])
    changed = 0
    for col in cols:
        if chunk[col].dtype != object:   # only string/object columns can carry PII text
            continue
        def _m(v):
            nonlocal changed
            if isinstance(v, str) and v:
                mv = pii_ko.mask(v)
                if mv != v:
                    changed += 1
                return mv
            return v
        chunk[col] = chunk[col].map(_m)
    return changed


def _read_write_chunked(engine, query, source_table, write_mode, incremental_column,
                        on_step=None, partition_spec=None, key_columns=None,
                        pii_columns=None, chunk_size=INGEST_CHUNK_SIZE):
    """Stream a source query in chunks → write to Iceberg, bounding memory to one chunk.

    Uses a server-side cursor (execution_options(stream_results=True)) so the DB driver
    does not buffer the entire result client-side either — without this, pandas'
    chunksize alone still loads every row into the driver (the OOM risk on big tables).
    First non-empty chunk uses write_mode (overwrite/append); subsequent chunks append.
    Returns (rows_processed, max_value_str) where max_value is the incremental watermark.
    Synchronous (CPU/IO heavy) — call via asyncio.to_thread."""
    from .iceberg_writer import write_dataframe_to_iceberg
    # Incremental + PK → upsert(merge): updates changed rows, inserts new ones (no dup).
    # Without keys, incremental falls back to append (historical behavior).
    upsert = bool(key_columns) and write_mode == "append"
    rows = 0
    masked = 0
    typed_max = None
    first = True
    with engine.connect().execution_options(stream_results=True) as conn:
        for chunk in pd.read_sql(query, conn, chunksize=chunk_size):
            if chunk.empty:
                continue
            # PII 마스킹 — 원천 데이터가 raw로 레이크하우스에 적재되기 전 차단(주권/규제).
            masked += _mask_pii_in_chunk(chunk, pii_columns)
            if upsert:
                write_dataframe_to_iceberg(chunk, source_table, mode="upsert",
                                           join_cols=key_columns,
                                           on_step=on_step if first else None,
                                           partition_spec=partition_spec)
            else:
                mode = write_mode if first else "append"
                write_dataframe_to_iceberg(chunk, source_table, mode=mode,
                                           on_step=on_step if first else None,
                                           partition_spec=partition_spec)
            first = False
            rows += len(chunk)
            if incremental_column and incremental_column in chunk.columns:
                cmax = chunk[incremental_column].max()
                if cmax is not None and (typed_max is None or cmax > typed_max):
                    typed_max = cmax
    # Full refresh that returned zero rows → overwrite to an empty table (truthful);
    # recover the column schema via a LIMIT 0 read. Incremental + empty = no-op
    # (don't append nothing, don't move the watermark).
    if first and write_mode == "overwrite":
        empty = pd.read_sql(f"SELECT * FROM ({query}) AS _src LIMIT 0", engine)
        write_dataframe_to_iceberg(empty, source_table, mode="overwrite",
                                   on_step=on_step, partition_spec=partition_spec)
    if masked and on_step:
        on_step("pii_mask", f"PII 마스킹: {masked} cell(s)", {"masked": masked})
    elif masked:
        logger.info(f"[ingest] PII masked {masked} cell(s) in {source_table}")
    return rows, (str(typed_max) if typed_max is not None else None)


@ConnectorRegistry.register(ConnectorType.POSTGRESQL)
class PostgreSQLConnector(BaseConnector):
    """PostgreSQL database connector"""

    def __init__(self, config: DatabaseConfig):
        super().__init__(config)
        self.config: DatabaseConfig = config
        self.engine = None

    def _build_connection_string(self) -> str:
        """Build PostgreSQL connection string"""
        password = quote_plus(self.config.password)
        username = quote_plus(self.config.username)

        ssl_mode = "?sslmode=require" if self.config.ssl else ""

        conn_str = (
            f"postgresql://{username}:{password}"
            f"@{self.config.host}:{self.config.port}/{self.config.database}{ssl_mode}"
        )

        return conn_str

    def _get_engine(self):
        """Get or create SQLAlchemy engine"""
        if self.engine is None:
            conn_str = self._build_connection_string()
            self.engine = create_engine(
                conn_str,
                poolclass=NullPool,  # Don't maintain connections
                **self.config.connection_params
            )
        return self.engine

    async def test_connection(self) -> ConnectionTestResult:
        """Test PostgreSQL connection"""
        start_time = time.time()

        try:
            engine = self._get_engine()

            # Test connection
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                version = result.scalar()

            latency_ms = (time.time() - start_time) * 1000

            return ConnectionTestResult(
                success=True,
                message="Connection successful",
                latency_ms=latency_ms,
                metadata={"version": version}
            )

        except Exception as e:
            logger.error(f"PostgreSQL connection test failed: {e}")
            return ConnectionTestResult(
                success=False,
                message=f"Connection failed: {str(e)}",
                latency_ms=(time.time() - start_time) * 1000
            )

    async def get_tables(self) -> List[str]:
        """List all tables in the database"""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)

            schema = self.config.schema or 'public'
            tables = inspector.get_table_names(schema=schema)

            return tables

        except Exception as e:
            logger.error(f"Failed to list tables: {e}")
            raise

    async def get_schema(self, table_name: str) -> TableSchema:
        """Get table schema"""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)

            schema = self.config.schema or 'public'

            # Get columns
            columns = inspector.get_columns(table_name, schema=schema)
            primary_keys = inspector.get_pk_constraint(table_name, schema=schema).get('constrained_columns', [])

            column_schemas = []
            for col in columns:
                column_schemas.append(ColumnSchema(
                    name=col['name'],
                    type=str(col['type']),
                    nullable=col['nullable'],
                    primary_key=col['name'] in primary_keys
                ))

            # Get row count
            with engine.connect() as conn:
                result = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{table_name}"'))
                row_count = result.scalar()

            return TableSchema(
                table_name=table_name,
                columns=column_schemas,
                row_count=row_count
            )

        except Exception as e:
            logger.error(f"Failed to get schema for {table_name}: {e}")
            raise

    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Read data from table"""
        try:
            engine = self._get_engine()
            schema = self.config.schema or 'public'

            # Build query
            query = f'SELECT * FROM "{schema}"."{table_name}"'

            if filters:
                conditions = [f"{key} = '{value}'" for key, value in filters.items()]
                query += " WHERE " + " AND ".join(conditions)

            if limit:
                query += f" LIMIT {limit}"

            # Execute query
            df = await asyncio.to_thread(pd.read_sql, query, engine)

            # Convert to list of dicts
            return df.to_dict('records')

        except Exception as e:
            logger.error(f"Failed to read data from {table_name}: {e}")
            raise

    async def sync_to_iceberg(
        self,
        source_table: str,
        target_table: str,
        sync_mode: SyncMode = SyncMode.FULL,
        incremental_column: Optional[str] = None,
        last_value: Optional[Any] = None,
        on_step=None,
        partition_spec: Optional[list] = None,
        key_columns: Optional[list] = None,
        pii_columns: Optional[list] = None,
    ) -> SyncJobStatus:
        """Synchronize PostgreSQL table to Iceberg via SeaweedFS S3 + Trino."""
        from .iceberg_writer import write_dataframe_to_iceberg
        started_at = datetime.utcnow()

        try:
            src_schema = self.config.schema or 'public'
            engine = self._get_engine()

            query = f'SELECT * FROM "{src_schema}"."{source_table}"'
            if sync_mode == SyncMode.INCREMENTAL and incremental_column and last_value:
                query += f" WHERE \"{incremental_column}\" > '{last_value}'"
            elif sync_mode == SyncMode.INCREMENTAL and incremental_column and not last_value:
                # First incremental run — read all, then track max value
                pass

            write_mode = "append" if sync_mode == SyncMode.INCREMENTAL else "overwrite"
            rows_processed, max_value = await asyncio.to_thread(
                _read_write_chunked, engine, query, source_table, write_mode,
                incremental_column, on_step, partition_spec, key_columns, pii_columns)
            logger.info(f"[pg_connector] Synced {rows_processed} rows from {src_schema}.{source_table} (chunked)")

            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={
                    "source_table": source_table,
                    "target_table": target_table,
                    "sync_mode": sync_mode.value,
                    "iceberg_table": f"iceberg.default.{source_table}",
                    "max_value": max_value,
                }
            )

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=0,
                rows_failed=0,
                error_message=str(e)
            )


@ConnectorRegistry.register(ConnectorType.MYSQL)
class MySQLConnector(BaseConnector):
    """MySQL/MariaDB database connector"""

    def __init__(self, config: DatabaseConfig):
        super().__init__(config)
        self.config: DatabaseConfig = config
        self.engine = None

    def _build_connection_string(self) -> str:
        """Build MySQL connection string"""
        password = quote_plus(self.config.password)
        username = quote_plus(self.config.username)

        ssl_params = "?ssl=true" if self.config.ssl else ""

        conn_str = (
            f"mysql+pymysql://{username}:{password}"
            f"@{self.config.host}:{self.config.port}/{self.config.database}{ssl_params}"
        )

        return conn_str

    def _get_engine(self):
        """Get or create SQLAlchemy engine"""
        if self.engine is None:
            conn_str = self._build_connection_string()
            self.engine = create_engine(
                conn_str,
                poolclass=NullPool,
                **self.config.connection_params
            )
        return self.engine

    async def test_connection(self) -> ConnectionTestResult:
        """Test MySQL connection"""
        start_time = time.time()

        try:
            engine = self._get_engine()

            with engine.connect() as conn:
                result = conn.execute(text("SELECT VERSION()"))
                version = result.scalar()

            latency_ms = (time.time() - start_time) * 1000

            return ConnectionTestResult(
                success=True,
                message="Connection successful",
                latency_ms=latency_ms,
                metadata={"version": version}
            )

        except Exception as e:
            logger.error(f"MySQL connection test failed: {e}")
            return ConnectionTestResult(
                success=False,
                message=f"Connection failed: {str(e)}",
                latency_ms=(time.time() - start_time) * 1000
            )

    async def get_tables(self) -> List[str]:
        """List all tables in the database"""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)
            return inspector.get_table_names()

        except Exception as e:
            logger.error(f"Failed to list tables: {e}")
            raise

    async def get_schema(self, table_name: str) -> TableSchema:
        """Get table schema"""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)

            # Get columns
            columns = inspector.get_columns(table_name)
            primary_keys = inspector.get_pk_constraint(table_name).get('constrained_columns', [])

            column_schemas = []
            for col in columns:
                column_schemas.append(ColumnSchema(
                    name=col['name'],
                    type=str(col['type']),
                    nullable=col['nullable'],
                    primary_key=col['name'] in primary_keys
                ))

            # Get row count
            with engine.connect() as conn:
                result = conn.execute(text(f'SELECT COUNT(*) FROM `{table_name}`'))
                row_count = result.scalar()

            return TableSchema(
                table_name=table_name,
                columns=column_schemas,
                row_count=row_count
            )

        except Exception as e:
            logger.error(f"Failed to get schema for {table_name}: {e}")
            raise

    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Read data from table"""
        try:
            engine = self._get_engine()

            query = f'SELECT * FROM `{table_name}`'

            if filters:
                conditions = [f"`{key}` = '{value}'" for key, value in filters.items()]
                query += " WHERE " + " AND ".join(conditions)

            if limit:
                query += f" LIMIT {limit}"

            df = await asyncio.to_thread(pd.read_sql, query, engine)
            return df.to_dict('records')

        except Exception as e:
            logger.error(f"Failed to read data from {table_name}: {e}")
            raise

    async def sync_to_iceberg(
        self,
        source_table: str,
        target_table: str,
        sync_mode: SyncMode = SyncMode.FULL,
        incremental_column: Optional[str] = None,
        last_value: Optional[Any] = None,
        on_step=None,
        partition_spec: Optional[list] = None,
        key_columns: Optional[list] = None,
        pii_columns: Optional[list] = None,
    ) -> SyncJobStatus:
        """Synchronize MySQL table to Iceberg via SeaweedFS S3 + Trino."""
        from .iceberg_writer import write_dataframe_to_iceberg
        started_at = datetime.utcnow()

        try:
            engine = self._get_engine()
            query = f'SELECT * FROM `{source_table}`'
            if sync_mode == SyncMode.INCREMENTAL and incremental_column and last_value:
                query += f" WHERE `{incremental_column}` > '{last_value}'"

            write_mode = "append" if sync_mode == SyncMode.INCREMENTAL else "overwrite"
            rows_processed, max_value = await asyncio.to_thread(
                _read_write_chunked, engine, query, source_table, write_mode,
                incremental_column, on_step, partition_spec, key_columns, pii_columns)
            logger.info(f"[mysql_connector] Synced {rows_processed} rows from {source_table} (chunked)")

            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={
                    "source_table": source_table,
                    "target_table": target_table,
                    "sync_mode": sync_mode.value,
                    "iceberg_table": f"iceberg.default.{source_table}",
                    "max_value": max_value,
                }
            )

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=0,
                rows_failed=0,
                error_message=str(e)
            )


# SQL Server connector would be similar but use mssql+pyodbc driver
# MongoDB connector would use pymongo instead of SQLAlchemy
# For brevity, showing structure for PostgreSQL and MySQL


class DatabaseURLConfig(ConnectorConfig):
    """Configuration for Universal SQLAlchemy connector"""
    database_url: str  # e.g. "postgresql://user:pass@host/db", "mssql+pyodbc://...", etc.
    query: Optional[str] = None  # Custom SQL for connection test (defaults to SELECT 1)

    # Supported examples (for documentation purposes):
    # postgresql://user:pass@host:5432/db
    # mysql+pymysql://user:pass@host:3306/db
    # mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+17+for+SQL+Server
    # oracle+cx_oracle://user:pass@host:1521/service
    # sqlite:///path/to/file.db
    # snowflake://user:pass@account/db/schema
    # redshift+redshift_connector://user:pass@host:5439/db


@ConnectorRegistry.register(ConnectorType.DATABASE_URL)
class DatabaseURLConnector(BaseConnector):
    """Universal database connector using SQLAlchemy connection strings.

    Supports any database with a SQLAlchemy dialect:
    PostgreSQL, MySQL, SQL Server (pyodbc), Oracle (cx_oracle),
    SQLite, Snowflake, Redshift, and more.
    """

    def __init__(self, config: DatabaseURLConfig):
        super().__init__(config)
        self.config: DatabaseURLConfig = config
        self.engine = None

    # Driver-friendly error hints
    _DRIVER_HINTS = {
        "cx_oracle": "pip install cx_oracle",
        "pyodbc": "pip install pyodbc  (and install the appropriate ODBC driver)",
        "pymysql": "pip install pymysql",
        "psycopg2": "pip install psycopg2-binary",
        "snowflake": "pip install snowflake-sqlalchemy",
        "redshift_connector": "pip install redshift-connector sqlalchemy-redshift",
        "pymssql": "pip install pymssql",
    }

    def _get_engine(self):
        """Get or create SQLAlchemy engine (NullPool — no persistent connections)"""
        if self.engine is None:
            self.engine = create_engine(
                self.config.database_url,
                poolclass=NullPool
            )
        return self.engine

    def _friendly_error(self, exc: Exception) -> str:
        """Return a helpful error message with driver installation hints if relevant"""
        msg = str(exc)
        for driver, hint in self._DRIVER_HINTS.items():
            if driver in msg.lower():
                return f"{msg}\n\nHint: '{driver}' driver not found. Run: {hint}"
        return msg

    async def test_connection(self) -> ConnectionTestResult:
        """Test connection using the provided database_url"""
        start_time = time.time()
        try:
            engine = self._get_engine()
            test_sql = self.config.query or "SELECT 1"
            with engine.connect() as conn:
                result = conn.execute(text(test_sql))
                # Consume the result so it doesn't stay open
                result.fetchall()

            latency_ms = (time.time() - start_time) * 1000
            # Strip password from URL before returning
            safe_url = engine.url.__repr__()
            return ConnectionTestResult(
                success=True,
                message="Connection successful",
                latency_ms=latency_ms,
                metadata={"database_url": safe_url}
            )
        except Exception as e:
            logger.error(f"DatabaseURL connection test failed: {e}")
            return ConnectionTestResult(
                success=False,
                message=f"Connection failed: {self._friendly_error(e)}",
                latency_ms=(time.time() - start_time) * 1000
            )

    async def get_tables(self) -> List[str]:
        """List all tables across all schemas"""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)
            schemas = []
            try:
                schemas = inspector.get_schema_names()
            except Exception:
                schemas = [None]

            tables = []
            for schema in schemas:
                try:
                    schema_tables = inspector.get_table_names(schema=schema)
                    if schema:
                        tables.extend([f"{schema}.{t}" for t in schema_tables])
                    else:
                        tables.extend(schema_tables)
                except Exception:
                    continue
            return tables
        except Exception as e:
            logger.error(f"DatabaseURL list_tables failed: {e}")
            raise

    async def get_schema(self, table_name: str) -> TableSchema:
        """Get table schema — supports 'schema.table' notation"""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)

            # Parse optional schema prefix
            if "." in table_name:
                schema, tbl = table_name.split(".", 1)
            else:
                schema, tbl = None, table_name

            columns = inspector.get_columns(tbl, schema=schema)
            pk_info = inspector.get_pk_constraint(tbl, schema=schema)
            primary_keys = pk_info.get("constrained_columns", [])

            column_schemas = [
                ColumnSchema(
                    name=col["name"],
                    type=str(col["type"]),
                    nullable=col.get("nullable", True),
                    primary_key=col["name"] in primary_keys,
                )
                for col in columns
            ]

            # Row count (best-effort)
            row_count = None
            try:
                qualified = f'"{schema}"."{tbl}"' if schema else f'"{tbl}"'
                with engine.connect() as conn:
                    row_count = conn.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar()
            except Exception:
                pass

            return TableSchema(
                table_name=table_name,
                columns=column_schemas,
                row_count=row_count,
            )
        except Exception as e:
            logger.error(f"DatabaseURL get_schema failed for {table_name}: {e}")
            raise

    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Read rows from any table"""
        try:
            engine = self._get_engine()
            if "." in table_name:
                schema, tbl = table_name.split(".", 1)
                qualified = f'"{schema}"."{tbl}"'
            else:
                qualified = f'"{table_name}"'

            query = f"SELECT * FROM {qualified}"
            if filters:
                conditions = [f"{k} = '{v}'" for k, v in filters.items()]
                query += " WHERE " + " AND ".join(conditions)
            if limit:
                query += f" LIMIT {limit}"

            df = await asyncio.to_thread(pd.read_sql, query, engine)
            return df.to_dict("records")
        except Exception as e:
            logger.error(f"DatabaseURL read_data failed: {e}")
            raise

    async def sync_to_iceberg(
        self,
        source_table: str,
        target_table: str,
        sync_mode: SyncMode = SyncMode.FULL,
        incremental_column: Optional[str] = None,
        last_value: Optional[Any] = None,
        on_step=None,
        partition_spec: Optional[list] = None,
        key_columns: Optional[list] = None,
        pii_columns: Optional[list] = None,
    ) -> SyncJobStatus:
        """Sync table data to Iceberg via SeaweedFS S3 + Trino."""
        from .iceberg_writer import write_dataframe_to_iceberg
        started_at = datetime.utcnow()
        try:
            engine = self._get_engine()
            if "." in source_table:
                schema, tbl = source_table.split(".", 1)
                qualified = f'"{schema}"."{tbl}"'
                tbl_name = tbl
            else:
                qualified = f'"{source_table}"'
                tbl_name = source_table

            query = f"SELECT * FROM {qualified}"
            if sync_mode == SyncMode.INCREMENTAL and incremental_column and last_value:
                query += f" WHERE {incremental_column} > '{last_value}'"

            df = await asyncio.to_thread(pd.read_sql, query, engine)
            logger.info(f"[dburl_connector] Read {len(df)} rows from {source_table}")

            write_mode = "append" if sync_mode == SyncMode.INCREMENTAL else "overwrite"
            rows_processed = await asyncio.to_thread(write_dataframe_to_iceberg, df, tbl_name, mode=write_mode, on_step=on_step, partition_spec=partition_spec)

            max_value = None
            if incremental_column and incremental_column in df.columns and not df.empty:
                max_val = df[incremental_column].max()
                max_value = str(max_val) if max_val is not None else None

            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={
                    "source_table": source_table,
                    "target_table": target_table,
                    "sync_mode": sync_mode.value,
                    "iceberg_table": f"iceberg.default.{tbl_name}",
                    "max_value": max_value,
                },
            )
        except Exception as e:
            logger.error(f"DatabaseURL sync_to_iceberg failed: {e}")
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=0,
                rows_failed=0,
                error_message=self._friendly_error(e),
            )
