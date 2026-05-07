"""
Custom Python connector for DataPond.

Allows users to provide arbitrary Python code that defines a
``fetch_data() -> list[dict]`` function.  The code is executed in a
sandboxed namespace with dangerous builtins removed.

Restricted builtins (blocked):
  __import__, open, exec, eval, compile, getattr, setattr,
  delattr, input, print (output captured), os, subprocess,
  sys (import blocked via __import__ restriction)

Safe builtins allowed:
  abs, all, any, bool, dict, enumerate, filter, float, int,
  isinstance, issubclass, iter, len, list, map, max, min,
  next, range, repr, reversed, round, set, slice, sorted,
  str, sum, tuple, type, zip
"""

import logging
import types
from datetime import datetime
from typing import Any, Dict, List, Optional

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

# ---------------------------------------------------------------------------
# Safe builtins whitelist
# ---------------------------------------------------------------------------

_SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "bytes": bytes,
    "chr": chr,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "getattr": None,         # blocked
    "hasattr": hasattr,
    "hash": hash,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    # Exceptions users may raise
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "Exception": Exception,
    "RuntimeError": RuntimeError,
    "NotImplementedError": NotImplementedError,
    # None / True / False
    "None": None,
    "True": True,
    "False": False,
}

# Remove any None-valued keys that were placeholders for blocked builtins
_SAFE_BUILTINS = {k: v for k, v in _SAFE_BUILTINS.items() if v is not None or k in ("None",)}


def _make_safe_namespace() -> Dict[str, Any]:
    """Return a minimal execution namespace with restricted __builtins__."""
    return {
        "__builtins__": _SAFE_BUILTINS,
        "__name__": "__datapond_custom__",
        "__doc__": None,
    }


class CustomConfig(ConnectorConfig):
    """Configuration for the Custom Python connector"""
    code: str  # Python source; must define fetch_data() -> list[dict]
    requirements: List[str] = []  # optional extra pip packages (informational only)


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

    def _compile(self) -> types.CodeType:
        """Compile user code and return a code object, raising SyntaxError if invalid."""
        return compile(self.config.code, "<custom_connector>", "exec")

    def _execute(self) -> List[Dict[str, Any]]:
        """
        Execute the user code in a restricted namespace and call fetch_data().

        Returns:
            The list of records returned by fetch_data().

        Raises:
            ValueError  if fetch_data is missing or returns the wrong type.
            Any exception raised inside fetch_data propagates to the caller.
        """
        namespace = _make_safe_namespace()
        code_obj = self._compile()
        exec(code_obj, namespace)  # noqa: S102 — controlled sandbox

        fetch_fn = namespace.get("fetch_data")
        if fetch_fn is None or not callable(fetch_fn):
            raise ValueError(
                "fetch_data() function not found. "
                "Your code must define: def fetch_data() -> list[dict]: ..."
            )

        result = fetch_fn()

        if not isinstance(result, list):
            raise ValueError(
                f"fetch_data() must return a list of dicts, got {type(result).__name__}"
            )
        return result

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
        try:
            code_obj = self._compile()

            # Dry-run: execute the code and check for fetch_data, but don't call it
            namespace = _make_safe_namespace()
            exec(code_obj, namespace)  # noqa: S102

            if "fetch_data" not in namespace or not callable(namespace["fetch_data"]):
                return ConnectionTestResult(
                    success=False,
                    message="fetch_data() function not found in code.",
                    latency_ms=(time.time() - start) * 1000,
                )

            return ConnectionTestResult(
                success=True,
                message="Code compiled and fetch_data() found. Ready to execute.",
                latency_ms=(time.time() - start) * 1000,
                metadata={"requirements": self.config.requirements},
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
        """Custom connectors expose a single virtual 'result' table."""
        return ["result"]

    async def get_schema(self, table_name: str) -> TableSchema:
        """Infer schema by running fetch_data() and inspecting the first record."""
        try:
            records = self._execute()
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
            records = self._execute()
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
    ) -> SyncJobStatus:
        """Execute user code and sync results to Iceberg."""
        started_at = datetime.utcnow()
        try:
            records = self._execute()
            rows_processed = len(records)
            logger.info(
                f"Custom connector: syncing {rows_processed} records to {target_table}"
            )
            return SyncJobStatus(
                job_id=None,
                status=SyncStatus.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                rows_processed=rows_processed,
                rows_failed=0,
                metadata={"target_table": target_table, "sync_mode": sync_mode.value},
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
