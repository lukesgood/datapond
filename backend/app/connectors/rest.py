"""
REST API connector for DataPond.

Supports HTTP/HTTPS endpoints with multiple auth schemes:
  - none     : no authentication
  - bearer   : Authorization: Bearer <token>
  - basic    : Authorization: Basic base64(user:pass)
  - api_key  : custom header (default: Authorization)

Data extraction uses dot-notation JSONPath (e.g. "data.items").
"""

import base64
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from .base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorRegistry,
    ConnectorType,
    ConnectionTestResult,
    ColumnSchema,
    SyncMode,
    SyncJobStatus,
    SyncStatus,
    TableSchema,
)

logger = logging.getLogger(__name__)


class RestConfig(ConnectorConfig):
    """Configuration for REST API connector"""
    base_url: str  # e.g. "https://api.example.com/v1"
    auth_type: str = "none"  # none | bearer | basic | api_key
    auth_value: Optional[str] = None  # token, "user:password", or api_key_value
    auth_header: str = "Authorization"  # header name for api_key auth type
    data_path: Optional[str] = None  # dot-notation path to array, e.g. "data.items"
    headers: Dict[str, str] = {}  # extra static headers
    timeout: int = 30  # request timeout in seconds


def _extract_path(data: Any, path: Optional[str]) -> Any:
    """
    Traverse a nested dict/list using dot-notation.

    Example:
        _extract_path({"data": {"items": [...]}}, "data.items") -> [...]
        _extract_path({...}, None) -> {…}  (returns root)
    """
    if not path:
        return data
    for key in path.split("."):
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list):
            # Allow numeric index segments, e.g. "results.0.items"
            try:
                data = data[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if data is None:
            return None
    return data


@ConnectorRegistry.register(ConnectorType.REST_API)
class RestConnector(BaseConnector):
    """REST API connector — fetch JSON data from any HTTP endpoint."""

    def __init__(self, config: RestConfig):
        super().__init__(config)
        self.config: RestConfig = config

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        headers = dict(self.config.headers)
        headers["Accept"] = "application/json"

        auth_type = (self.config.auth_type or "none").lower()
        value = self.config.auth_value or ""

        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {value}"

        elif auth_type == "basic":
            # auth_value expected as "user:password"
            try:
                encoded = base64.b64encode(value.encode()).decode()
            except Exception:
                encoded = ""
            headers["Authorization"] = f"Basic {encoded}"

        elif auth_type == "api_key":
            header_name = self.config.auth_header or "Authorization"
            headers[header_name] = value

        # auth_type == "none" — no additional header

        return headers

    # ------------------------------------------------------------------
    # Core request helper
    # ------------------------------------------------------------------

    def _get(self, path: str = "", params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Perform a synchronous GET request and return parsed JSON.

        Args:
            path:   path appended to base_url (e.g. "/users")
            params: query parameters

        Returns:
            Parsed JSON (dict or list)

        Raises:
            httpx.HTTPStatusError on 4xx/5xx
            httpx.RequestError    on network failure
        """
        url = self.config.base_url.rstrip("/")
        if path:
            url = url + "/" + path.lstrip("/")

        headers = self._build_headers()
        with httpx.Client(timeout=self.config.timeout) as client:
            resp = client.get(url, headers=headers, params=params or {})
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectionTestResult:
        """Test by issuing a GET to base_url and checking for a 2xx response."""
        start = time.time()
        try:
            self._get()  # GET base_url
            latency_ms = (time.time() - start) * 1000
            return ConnectionTestResult(
                success=True,
                message="Connection successful",
                latency_ms=latency_ms,
                metadata={"base_url": self.config.base_url},
            )
        except httpx.HTTPStatusError as e:
            return ConnectionTestResult(
                success=False,
                message=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            logger.error(f"REST connection test failed: {e}")
            return ConnectionTestResult(
                success=False,
                message=f"Connection failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def get_tables(self) -> List[str]:
        """
        REST APIs don't have a canonical 'table' concept.
        Returns a placeholder representing the root endpoint.
        """
        return ["root"]

    async def get_schema(self, table_name: str) -> TableSchema:
        """
        Infer schema by fetching data and inspecting the first record.
        """
        try:
            data = self._get()
            records = _extract_path(data, self.config.data_path)
            if not isinstance(records, list) or not records:
                return TableSchema(table_name=table_name, columns=[])

            sample = records[0]
            columns = [
                ColumnSchema(name=k, type=type(v).__name__, nullable=True)
                for k, v in (sample.items() if isinstance(sample, dict) else {})
            ]
            return TableSchema(table_name=table_name, columns=columns, row_count=len(records))
        except Exception as e:
            logger.error(f"REST get_schema failed: {e}")
            return TableSchema(table_name=table_name, columns=[])

    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch data from base_url and extract via data_path."""
        try:
            data = self._get(params=filters or {})
            records = _extract_path(data, self.config.data_path)

            if records is None:
                return []
            if isinstance(records, dict):
                records = [records]
            if not isinstance(records, list):
                return []

            if limit:
                records = records[:limit]
            return records
        except Exception as e:
            logger.error(f"REST read_data failed: {e}")
            raise

    def fetch(self, endpoint: str = "", params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Public helper: fetch data from a specific endpoint.

        Args:
            endpoint: path relative to base_url, e.g. "/users"
            params:   query parameters

        Returns:
            List of records extracted via data_path
        """
        try:
            data = self._get(path=endpoint, params=params or {})
            records = _extract_path(data, self.config.data_path)

            if records is None:
                return []
            if isinstance(records, dict):
                return [records]
            if isinstance(records, list):
                return records
            return []
        except Exception as e:
            logger.error(f"REST fetch failed: {e}")
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
        """Fetch REST records and COMMIT them to an Iceberg table.

        Records from `read_data` → pandas → `write_dataframe_to_iceberg` (the same
        PyArrow → PyIceberg (Glue+S3) path the JDBC/S3 connectors use). A REST sync
        re-fetches the whole endpoint each run (no per-record watermark), so `append`
        would duplicate every row — the only safe modes are upsert (dedupe by
        key_columns) or overwrite. `rows_processed` is the real row count written.
        """
        import asyncio
        from datetime import datetime

        import pandas as pd

        from .iceberg_writer import write_dataframe_to_iceberg

        started_at = datetime.utcnow()
        try:
            records = await self.read_data(source_table)
            tbl_name = target_table.rsplit(".", 1)[-1] if target_table else source_table

            if not records:
                # Honest no-op: an empty endpoint response is not a failure.
                return SyncJobStatus(
                    job_id=None,
                    status=SyncStatus.SUCCESS,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    rows_processed=0,
                    rows_failed=0,
                    metadata={"source": self.config.base_url, "target_table": target_table,
                              "note": "No records returned by endpoint"},
                )

            df = pd.DataFrame(records)

            # Mask configured PII columns before anything lands in the lakehouse.
            masked = 0
            if pii_columns:
                try:
                    from .database import _mask_pii_in_chunk
                    masked = _mask_pii_in_chunk(df, pii_columns)
                except Exception as e:
                    logger.warning(f"[rest_connector] PII masking skipped ({e})")

            upsert = bool(key_columns)
            write_mode = "upsert" if upsert else "overwrite"
            rows_processed = await asyncio.to_thread(
                write_dataframe_to_iceberg, df, tbl_name,
                mode=write_mode, on_step=on_step, partition_spec=partition_spec,
                join_cols=key_columns if upsert else None,
            )
            logger.info(
                f"[rest_connector] Wrote {rows_processed} rows from REST endpoint to {tbl_name}"
            )
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={"source": self.config.base_url, "target_table": target_table,
                          "iceberg_table": f"iceberg.default.{tbl_name}",
                          "write_mode": write_mode, "pii_masked_cells": masked},
            )
        except Exception as e:
            logger.error(f"REST sync_to_iceberg failed: {e}")
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=0,
                rows_failed=0,
                error_message=str(e),
            )
