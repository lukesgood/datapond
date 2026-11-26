"""
Cloud storage connectors for S3, Azure Blob, GCS, and other object storage systems.

Supports:
- File discovery with pattern matching
- Schema inference
- Compression (gzip, snappy, zstd)
- Large file pagination
- Auto-loader for continuous ingestion
"""

import asyncio
import logging
import time
import fnmatch
from typing import Dict, List, Optional, Any

from pydantic import field_validator
from datetime import datetime
from io import BytesIO

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import pandas as pd

from .base import (
    target_namespace,
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


class StorageConfig(ConnectorConfig):
    """Configuration for cloud storage connectors"""
    bucket: str
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    region: str = "us-east-1"
    endpoint_url: Optional[str] = None  # For S3-compatible services (MinIO, SeaweedFS)
    prefix: str = ""  # Default prefix for file operations

    @field_validator("prefix", mode="before")
    @classmethod
    def _folder_prefix(cls, v):
        """`data`, `/data` and `data/` all mean the folder `data/`. Without the slash the
        table folder `orders` was looked up as `dataorders`."""
        v = str(v or "").strip().lstrip("/")
        return f"{v.rstrip('/')}/" if v else ""


# File extensions a sync reads, and the reader each one uses.
_FORMATS = {"csv": "csv", "json": "json", "jsonl": "json", "ndjson": "json",
            "parquet": "parquet", "pq": "parquet"}


# The changed-rows "column" of an S3 table: an object's LastModified. A table set to
# incremental with this column reads only files newer than the last file it read, and
# appends them (or merges by key columns); the watermark is that file's LastModified.
NEW_FILES_COLUMN = "_file_last_modified"
# A full sync of more files than this fails instead of loading a silent subset (it read
# the first 1,000 and said nothing). A new-files sync takes the oldest this many and the
# next run continues from there.
MAX_FILES_PER_SYNC = 5000
# Files modified this recently are left to the next run: an object written in the same
# second as the newest one read would otherwise sit at the watermark and never be read.
SETTLE_SECONDS = 5


def _ext(key: str) -> str:
    return key.rsplit(".", 1)[-1].lower() if "." in key.rsplit("/", 1)[-1] else ""


@ConnectorRegistry.register(ConnectorType.S3)
class S3Connector(BaseConnector):
    """AWS S3 and S3-compatible storage connector"""

    def __init__(self, config: StorageConfig):
        super().__init__(config)
        self.config: StorageConfig = config
        self._s3_client = None

    def _get_client(self):
        """Get or create boto3 S3 client"""
        if self._s3_client is None:
            client_config = {
                'region_name': self.config.region
            }

            if self.config.access_key and self.config.secret_key:
                client_config['aws_access_key_id'] = self.config.access_key
                client_config['aws_secret_access_key'] = self.config.secret_key

            if self.config.endpoint_url:
                client_config['endpoint_url'] = self.config.endpoint_url

            self._s3_client = boto3.client('s3', **client_config)

        return self._s3_client

    async def test_connection(self) -> ConnectionTestResult:
        """Test S3 connection by listing bucket"""
        start_time = time.time()

        try:
            client = self._get_client()

            # Try to head the bucket
            response = client.head_bucket(Bucket=self.config.bucket)

            latency_ms = (time.time() - start_time) * 1000

            return ConnectionTestResult(
                success=True,
                message=f"Successfully connected to bucket '{self.config.bucket}'",
                latency_ms=latency_ms,
                metadata={
                    "bucket": self.config.bucket,
                    "region": self.config.region
                }
            )

        except NoCredentialsError:
            return ConnectionTestResult(
                success=False,
                message="No AWS credentials found",
                latency_ms=(time.time() - start_time) * 1000
            )
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                message = f"Bucket '{self.config.bucket}' not found"
            elif error_code == '403':
                message = f"Access denied to bucket '{self.config.bucket}'"
            else:
                message = f"Connection failed: {e}"

            return ConnectionTestResult(
                success=False,
                message=message,
                latency_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            logger.error(f"S3 connection test failed: {e}")
            return ConnectionTestResult(
                success=False,
                message=f"Connection failed: {str(e)}",
                latency_ms=(time.time() - start_time) * 1000
            )

    async def get_tables(self) -> List[str]:
        """
        List 'tables' in S3 (interpreted as top-level prefixes/folders).

        Returns prefixes under the configured prefix as table names.
        """
        try:
            client = self._get_client()

            # List objects with delimiter to get folders
            response = client.list_objects_v2(
                Bucket=self.config.bucket,
                Prefix=self.config.prefix,
                Delimiter='/'
            )

            # Extract common prefixes (folders)
            tables = []
            for prefix_obj in response.get('CommonPrefixes', []):
                prefix = prefix_obj['Prefix']
                # Remove base prefix and trailing slash
                table_name = prefix.replace(self.config.prefix, '').rstrip('/')
                if table_name:
                    tables.append(table_name)

            return tables

        except Exception as e:
            logger.error(f"Failed to list tables (prefixes): {e}")
            raise

    async def list_files(
        self,
        prefix: str = "",
        pattern: str = "*",
        max_files: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        List files in bucket matching pattern.

        Args:
            prefix: Prefix to search under
            pattern: File pattern (e.g., '*.csv', '*.parquet')
            max_files: Maximum files to return

        Returns:
            List of file metadata dicts
        """
        try:
            client = self._get_client()

            # A table is a folder: `orders` must not also match `orders_old/`.
            folder = f"{prefix.strip('/')}/" if prefix.strip("/") else ""
            full_prefix = f"{self.config.prefix}{folder}"

            files = []
            paginator = client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self.config.bucket,
                Prefix=full_prefix,
                PaginationConfig={'MaxItems': max_files}
            )

            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    key = obj['Key']

                    # Apply pattern matching
                    if fnmatch.fnmatch(key, pattern) or fnmatch.fnmatch(key, f"*{pattern}"):
                        files.append({
                            'key': key,
                            'size': obj['Size'],
                            'last_modified': obj['LastModified'].isoformat(),
                            'etag': obj['ETag'].strip('"')
                        })

            return files

        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            raise

    async def get_schema(self, prefix: str, file_format: Optional[str] = None) -> TableSchema:
        """
        Infer schema from first file in prefix.

        Args:
            prefix: Prefix/folder to analyze
            file_format: File format (csv, json, parquet)

        Returns:
            TableSchema with inferred columns
        """
        try:
            # The first file a sync would read (CSV, JSON(L) or Parquet), unless a format
            # is named. It was CSV only, so a Parquet folder listed no columns.
            files = await self.list_files(prefix=prefix, max_files=1000)
            files = [f for f in files if _FORMATS.get(_ext(f["key"]))
                     and (file_format is None or _FORMATS[_ext(f["key"])] == file_format)]

            if not files:
                raise ValueError(f"No {file_format or 'CSV, JSON or Parquet'} files found in prefix '{prefix}'")

            file_key = files[0]['key']
            file_format = _FORMATS[_ext(file_key)]
            schema = await self._infer_schema_from_file(file_key, file_format)

            return schema

        except Exception as e:
            logger.error(f"Failed to get schema for {prefix}: {e}")
            raise

    async def _infer_schema_from_file(self, key: str, file_format: str) -> TableSchema:
        """Infer schema from a single file"""
        try:
            client = self._get_client()

            # Download file
            response = client.get_object(Bucket=self.config.bucket, Key=key)
            file_content = response['Body'].read()

            # Read with pandas to infer schema
            if file_format == "csv":
                df = pd.read_csv(BytesIO(file_content), nrows=100)
            elif file_format == "json":
                try:
                    df = pd.read_json(BytesIO(file_content), lines=True, nrows=100)
                except ValueError:
                    df = pd.read_json(BytesIO(file_content))
            elif file_format == "parquet":
                df = pd.read_parquet(BytesIO(file_content))
            else:
                raise ValueError(f"Unsupported format: {file_format}")

            # Convert pandas dtypes to generic types
            columns = []
            for col_name, dtype in df.dtypes.items():
                col_type = str(dtype)

                # Map pandas dtypes to SQL-like types
                if 'int' in col_type:
                    col_type = 'INTEGER'
                elif 'float' in col_type:
                    col_type = 'DOUBLE'
                elif 'bool' in col_type:
                    col_type = 'BOOLEAN'
                elif 'datetime' in col_type:
                    col_type = 'TIMESTAMP'
                else:
                    col_type = 'STRING'

                columns.append(ColumnSchema(
                    name=col_name,
                    type=col_type,
                    nullable=True  # Assume nullable for file sources
                ))

            return TableSchema(
                table_name=key,
                columns=columns,
                row_count=None,  # one file (CSV: its first 100 rows) is not the table; it read as "47 rows" for 241
            )

        except Exception as e:
            logger.error(f"Failed to infer schema from {key}: {e}")
            raise

    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Read data from files in prefix.

        Args:
            table_name: Prefix/folder to read from
            limit: Maximum rows to return
            filters: Not implemented for file sources

        Returns:
            List of records
        """
        try:
            # The same files a sync reads (CSV, JSON(L), Parquet); it read CSV only.
            files = [f for f in await self.list_files(prefix=table_name, max_files=1000)
                     if _FORMATS.get(_ext(f["key"]))][:10]

            if not files:
                return []

            client = self._get_client()

            all_data = []
            total_rows = 0

            for file in files:
                if limit and total_rows >= limit:
                    break

                # Download and read file
                df = await asyncio.to_thread(self._read_file_to_df, client, file['key'])
                if df is None:
                    continue

                # Apply limit
                if limit:
                    remaining = limit - total_rows
                    df = df.head(remaining)

                all_data.extend(df.to_dict('records'))
                total_rows += len(df)

            return all_data

        except Exception as e:
            logger.error(f"Failed to read data from {table_name}: {e}")
            raise

    def _read_file_to_df(self, client, key: str) -> Optional[pd.DataFrame]:
        """Download one S3 object and parse it into a DataFrame by extension.

        Supports CSV, JSON/JSONL, and Parquet — the common structured formats for
        object-storage exports. Returns None for unsupported extensions (caller logs
        + skips). Raises on read/parse failure so the caller can fail the job honestly.
        """
        ext = _ext(key)

        if ext not in _FORMATS:
            return None

        body = client.get_object(Bucket=self.config.bucket, Key=key)["Body"].read()

        if ext == "csv":
            return pd.read_csv(BytesIO(body))
        if ext in ("json", "jsonl", "ndjson"):
            try:
                # Most object-storage exports are newline-delimited JSON.
                return pd.read_json(BytesIO(body), lines=True)
            except ValueError:
                # Fall back to a single JSON array/object document.
                return pd.read_json(BytesIO(body))
        # parquet / pq
        return pd.read_parquet(BytesIO(body))

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
        """
        Synchronize files from S3 to an Iceberg table.

        Reads every matching object under the source prefix (CSV / JSON(L) / Parquet,
        by extension), concatenates them into a single DataFrame, and commits via
        `write_dataframe_to_iceberg` — the same pandas → PyArrow → PyIceberg (Glue+S3)
        path the JDBC/database connectors use. `rows_processed` is the actual number of
        rows written, not a file-count proxy.
        """
        from .iceberg_writer import write_dataframe_to_iceberg

        started_at = datetime.utcnow()

        try:
            new_files = sync_mode == SyncMode.INCREMENTAL and incremental_column == NEW_FILES_COLUMN
            files = await self.list_files(prefix=source_table, max_files=MAX_FILES_PER_SYNC + 1)
            files = [f for f in files if _FORMATS.get(_ext(f["key"]))] or files
            if new_files:
                from datetime import timedelta, timezone
                settled = (datetime.now(timezone.utc) - timedelta(seconds=SETTLE_SECONDS)).isoformat()
                since = str(last_value) if last_value else ""
                files = sorted((f for f in files if f["last_modified"] > since and f["last_modified"] <= settled),
                               key=lambda f: (f["last_modified"], f["key"]))[:MAX_FILES_PER_SYNC]
            elif len(files) > MAX_FILES_PER_SYNC:
                raise RuntimeError(
                    f"More than {MAX_FILES_PER_SYNC} files under {source_table}/; a full sync would load only "
                    "some of them. Set the table to New files only, or split the folder.")

            logger.info(
                f"[s3_connector] Found {len(files)} file(s) under "
                f"s3://{self.config.bucket}/{source_table} for target {target_table}"
            )

            if not files:
                # Honest no-op: nothing to sync is not a failure.
                return SyncJobStatus(
                    job_id=None,
                    status=SyncStatus.SUCCESS,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    rows_processed=0,
                    rows_failed=0,
                    metadata={
                        "source_prefix": source_table,
                        "target_table": target_table,
                        "file_count": 0,
                        "note": "No matching files under prefix",
                    },
                )

            client = self._get_client()
            frames: List[pd.DataFrame] = []
            skipped_files: List[str] = []
            read_errors: List[str] = []

            for f in files:
                key = f["key"]
                try:
                    df = await asyncio.to_thread(self._read_file_to_df, client, key)
                except Exception as e:
                    logger.error(f"[s3_connector] Failed to read/parse {key}: {e}")
                    read_errors.append(f"{key}: {e}")
                    continue

                if df is None:
                    logger.info(f"[s3_connector] Skipping unsupported file type: {key}")
                    skipped_files.append(key)
                    continue

                if not df.empty:
                    frames.append(df)

            # A new-files run that skipped an unreadable file would move the watermark
            # past it for good; fail instead, so the next run tries it again.
            if new_files and read_errors:
                raise RuntimeError(
                    f"Failed to read {len(read_errors)} new file(s); the watermark was not moved: "
                    + "; ".join(read_errors[:5]))

            # All files errored and none were readable → fail honestly (don't fake success).
            if read_errors and not frames and len(skipped_files) < len(files):
                raise RuntimeError(
                    f"Failed to read {len(read_errors)}/{len(files)} file(s): "
                    + "; ".join(read_errors[:5])
                )

            if not frames:
                # Every file was either unsupported or empty — honest zero-row success.
                return SyncJobStatus(
                    job_id=None,
                    status=SyncStatus.SUCCESS,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    rows_processed=0,
                    rows_failed=0,
                    metadata={
                        "source_prefix": source_table,
                        "target_table": target_table,
                        "file_count": len(files),
                        "skipped_files": skipped_files,
                        "read_errors": read_errors,
                        "note": "No rows parsed from matched files",
                    },
                )

            df = frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)

            # Mask configured PII columns before anything lands in the lakehouse
            # (same guardrail the JDBC connectors apply pre-write).
            masked = 0
            if pii_columns:
                try:
                    from .pii_chunk import _mask_pii_in_chunk
                    masked = _mask_pii_in_chunk(df, pii_columns)
                except Exception as e:
                    logger.warning(f"[s3_connector] PII masking skipped ({e})")

            tbl_name = target_table.rsplit(".", 1)[-1] if target_table else source_table

            # A full sync re-reads every object, so plain `append` would duplicate all
            # rows: it upserts (by key_columns) or overwrites. A new-files sync reads
            # each file once, so it appends (or upserts when keys are set).
            upsert = bool(key_columns)
            # The first new-files run (no watermark yet) reads every file, so it replaces
            # the table: a table switched from a full sync would otherwise get its rows twice.
            write_mode = "upsert" if upsert else ("append" if new_files and last_value else "overwrite")

            rows_processed = await asyncio.to_thread(
                write_dataframe_to_iceberg,
                df,
                tbl_name,
                schema=target_namespace(target_table),
                mode=write_mode,
                on_step=on_step,
                partition_spec=partition_spec,
                join_cols=key_columns if upsert else None,
            )

            completed_at = datetime.utcnow()

            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=completed_at,
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={
                    "source_prefix": source_table,
                    "target_table": target_table,
                    "iceberg_table": f"iceberg.default.{tbl_name}",
                    "file_count": len(files),
                    "files_parsed": len(frames),
                    **({"max_value": files[-1]["last_modified"]} if new_files and files else {}),
                    "skipped_files": skipped_files,
                    "read_errors": read_errors,
                    "pii_masked_cells": masked,
                },
            )

        except Exception as e:
            logger.error(f"[s3_connector] Sync failed: {e}")
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=0,
                rows_failed=0,
                error_message=str(e)
            )


# Azure Blob and GCS connectors would follow similar patterns
# Using azure-storage-blob and google-cloud-storage libraries respectively
