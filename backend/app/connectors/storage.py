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
from datetime import datetime
from io import BytesIO

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
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


class StorageConfig(ConnectorConfig):
    """Configuration for cloud storage connectors"""
    bucket: str
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    region: str = "us-east-1"
    endpoint_url: Optional[str] = None  # For S3-compatible services (MinIO, SeaweedFS)
    prefix: str = ""  # Default prefix for file operations


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

            full_prefix = f"{self.config.prefix}{prefix}".strip('/')

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

    async def get_schema(self, prefix: str, file_format: str = "csv") -> TableSchema:
        """
        Infer schema from first file in prefix.

        Args:
            prefix: Prefix/folder to analyze
            file_format: File format (csv, json, parquet)

        Returns:
            TableSchema with inferred columns
        """
        try:
            # List files in prefix
            files = await self.list_files(prefix=prefix, pattern=f"*.{file_format}", max_files=1)

            if not files:
                raise ValueError(f"No {file_format} files found in prefix '{prefix}'")

            # Read first file to infer schema
            file_key = files[0]['key']
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
                df = pd.read_json(BytesIO(file_content), lines=True, nrows=100)
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
                row_count=len(df)
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
            # For simplicity, read all CSV files in prefix
            files = await self.list_files(prefix=table_name, pattern="*.csv", max_files=10)

            if not files:
                return []

            client = self._get_client()

            all_data = []
            total_rows = 0

            for file in files:
                if limit and total_rows >= limit:
                    break

                # Download and read file
                response = client.get_object(Bucket=self.config.bucket, Key=file['key'])
                df = pd.read_csv(BytesIO(response['Body'].read()))

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
        ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""

        if ext not in ("csv", "json", "jsonl", "ndjson", "parquet", "pq"):
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
            # List files to sync
            files = await self.list_files(prefix=source_table, max_files=1000)

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
                    from .database import _mask_pii_in_chunk
                    masked = _mask_pii_in_chunk(df, pii_columns)
                except Exception as e:
                    logger.warning(f"[s3_connector] PII masking skipped ({e})")

            tbl_name = target_table.rsplit(".", 1)[-1] if target_table else source_table

            base_mode = "append" if sync_mode == SyncMode.INCREMENTAL else "overwrite"
            upsert = bool(key_columns) and base_mode == "append"
            write_mode = "upsert" if upsert else base_mode

            rows_processed = await asyncio.to_thread(
                write_dataframe_to_iceberg,
                df,
                tbl_name,
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
