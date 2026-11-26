"""
Custom Python connector for DataPond.

Allows users to provide Python code that defines a ``fetch_data() -> list[dict]``
function. The code is checked and run by app/connectors/sandbox.py: no imports, no
names or attributes starting with "_", in a child process with no secrets in its
environment, under CPU-time, memory and wall-clock limits. Only built-in Python is
available (see sandbox_runner.SAFE_BUILTIN_NAMES).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import (
    target_namespace,
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

class CustomConfig(ConnectorConfig):
    """Configuration for the Custom Python connector"""
    code: str  # Python source; must define fetch_data() -> list[dict]
    requirements: List[str] = []  # optional extra pip packages (informational only)
    table_name: Optional[str] = None  # catalog table name; "result" when unset


@ConnectorRegistry.register(ConnectorType.CUSTOM)
class CustomConnector(BaseConnector):
    """
    Custom Python connector — execute user-supplied code in a sandboxed
    namespace and return the result of ``fetch_data()``.

    The provided code **must** define::

        def fetch_data() -> list[dict]:
            ...
            return [{"col": "value"}, ...]
    """

    def __init__(self, config: CustomConfig):
        super().__init__(config)
        self.config: CustomConfig = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    def _execute(self) -> List[Dict[str, Any]]:
        """Run fetch_data() in the sandbox and return its records (blocking; async
        callers use `_records`)."""
        from .sandbox import run
        return run(self.config.code)

    async def _records(self) -> List[Dict[str, Any]]:
        from .sandbox import run_async
        return await run_async(self.config.code)

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectionTestResult:
        """
        Validate the custom code:
          1. Syntax check (compile)
          2. Verify fetch_data() is defined
        """
        import time
        start = time.time()
        from .sandbox import SandboxError, run_async
        try:
            # Defines fetch_data without calling it, in the sandbox (module-level code runs).
            await run_async(self.config.code, mode="define")
            return ConnectionTestResult(
                success=True,
                message="Code compiled and fetch_data() found. Ready to execute.",
                latency_ms=(time.time() - start) * 1000,
                metadata={"requirements": self.config.requirements},
            )
        except SandboxError as e:
            return ConnectionTestResult(
                success=False,
                message=str(e) if e.kind != "error" else f"Code validation failed: {e}",
                latency_ms=(time.time() - start) * 1000,
            )
        except SyntaxError as e:
            return ConnectionTestResult(
                success=False,
                message=f"Syntax error in code: {e}",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            logger.error(f"Custom connector test_connection failed: {e}")
            return ConnectionTestResult(
                success=False,
                message=f"Code validation failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def get_tables(self) -> List[str]:
        """Custom connectors expose a single virtual table, "result" unless named."""
        return [self.config.table_name or "result"]

    async def get_schema(self, table_name: str) -> TableSchema:
        """Infer schema by running fetch_data() and inspecting the first record."""
        try:
            records = await self._records()
            if not records or not isinstance(records[0], dict):
                return TableSchema(table_name=table_name, columns=[])
            columns = [
                ColumnSchema(name=k, type=type(v).__name__, nullable=True)
                for k, v in records[0].items()
            ]
            return TableSchema(
                table_name=table_name,
                columns=columns,
                row_count=len(records),
            )
        except Exception as e:
            logger.error(f"Custom connector get_schema failed: {e}")
            return TableSchema(table_name=table_name, columns=[])

    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute user code and return records from fetch_data()."""
        try:
            records = await self._records()
            if filters:
                records = [
                    r for r in records
                    if isinstance(r, dict) and all(r.get(k) == v for k, v in filters.items())
                ]
            if limit:
                records = records[:limit]
            return records
        except Exception as e:
            logger.error(f"Custom connector read_data failed: {e}")
            raise

    def run(self) -> List[Dict[str, Any]]:
        """
        Synchronous public helper: run fetch_data() and return results.

        Raises:
            ValueError  — fetch_data missing or wrong return type
            SyntaxError — code has syntax errors
        """
        return self._execute()

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
        """Run the user code and COMMIT its records to an Iceberg table.

        The user's `fetch_data()` returns records → pandas → `write_dataframe_to_iceberg`
        (the same PyArrow → PyIceberg (Glue+S3) path the other connectors use). Custom
        code re-produces its full result set each run, so `append` would duplicate — the
        only safe modes are upsert (dedupe by key_columns) or overwrite. `rows_processed`
        is the real row count written.
        """
        import asyncio

        import pandas as pd

        from .iceberg_writer import write_dataframe_to_iceberg

        started_at = datetime.utcnow()
        try:
            records = await self._records()
            tbl_name = target_table.rsplit(".", 1)[-1] if target_table else source_table

            if not records:
                return SyncJobStatus(
                    job_id=None,
                    status=SyncStatus.SUCCESS,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    rows_processed=0,
                    rows_failed=0,
                    metadata={"target_table": target_table, "sync_mode": sync_mode.value,
                              "note": "User code returned no records"},
                )

            df = pd.DataFrame(records)

            masked = 0
            if pii_columns:
                try:
                    from .pii_chunk import _mask_pii_in_chunk
                    masked = _mask_pii_in_chunk(df, pii_columns)
                except Exception as e:
                    logger.warning(f"[custom_connector] PII masking skipped ({e})")

            upsert = bool(key_columns)
            write_mode = "upsert" if upsert else "overwrite"
            rows_processed = await asyncio.to_thread(
                write_dataframe_to_iceberg, df, tbl_name,
                schema=target_namespace(target_table),
                mode=write_mode, on_step=on_step, partition_spec=partition_spec,
                join_cols=key_columns if upsert else None,
            )
            logger.info(
                f"[custom_connector] Wrote {rows_processed} rows to {tbl_name}"
            )
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={"target_table": target_table, "sync_mode": sync_mode.value,
                          "iceberg_table": f"iceberg.default.{tbl_name}",
                          "write_mode": write_mode, "pii_masked_cells": masked},
            )
        except Exception as e:
            logger.error(f"Custom connector sync_to_iceberg failed: {e}")
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=0,
                rows_failed=0,
                error_message=str(e),
            )
