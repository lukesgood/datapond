"""
Base connector classes and interfaces for DataPond data connectors.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class ConnectorType(str, Enum):
    """Supported connector types"""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    MONGODB = "mongodb"
    ORACLE = "oracle"
    S3 = "s3"
    AZURE_BLOB = "azure_blob"
    GCS = "gcs"
    KAFKA = "kafka"
    KINESIS = "kinesis"
    DATABASE_URL = "database_url"
    REST_API = "rest_api"
    CUSTOM = "custom"


class SyncMode(str, Enum):
    """Data synchronization modes"""
    FULL = "full"  # Full refresh (drop and replace)
    INCREMENTAL = "incremental"  # Append new/changed data
    CDC = "cdc"  # Change Data Capture
    SNAPSHOT = "snapshot"  # One-time snapshot


class ConnectorConfig(BaseModel):
    """Base configuration for all connectors"""
    name: str = Field(..., description="Connection name")
    connector_type: ConnectorType
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ConnectionStatus(str, Enum):
    """Connection status"""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    TESTING = "testing"


class SyncStatus(str, Enum):
    """Sync job status"""
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"
    PENDING = "pending"
    CANCELLED = "cancelled"


class ColumnSchema(BaseModel):
    """Column schema definition"""
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    description: Optional[str] = None


class TableSchema(BaseModel):
    """Table schema definition"""
    table_name: str
    columns: List[ColumnSchema]
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None


class ConnectionTestResult(BaseModel):
    """Connection test result"""
    success: bool
    message: str
    latency_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SyncJobConfig(BaseModel):
    """Sync job configuration"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    connection_id: uuid.UUID
    source_table: str
    target_table: str
    sync_mode: SyncMode = SyncMode.FULL
    schedule: Optional[str] = None  # Cron expression or 'manual'
    incremental_column: Optional[str] = None
    primary_keys: List[str] = Field(default_factory=list)
    enabled: bool = True


class SyncJobStatus(BaseModel):
    """Sync job execution status"""
    job_id: Optional[uuid.UUID] = None
    status: SyncStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rows_processed: int = 0
    rows_failed: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseConnector(ABC):
    """
    Abstract base class for all data connectors.

    All connectors must implement:
    - test_connection(): Verify connectivity
    - get_tables(): List available tables/objects
    - get_schema(): Get table schema
    - read_data(): Read data from source
    - sync_to_iceberg(): Sync data to Iceberg table
    """

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.connector_type = config.connector_type
        self._client = None

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        """
        Test if the connection is valid.

        Returns:
            ConnectionTestResult with success status and details
        """
        pass

    @abstractmethod
    async def get_tables(self) -> List[str]:
        """
        List all available tables/collections/objects.

        Returns:
            List of table names
        """
        pass

    @abstractmethod
    async def get_schema(self, table_name: str) -> TableSchema:
        """
        Get schema for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            TableSchema with column definitions
        """
        pass

    @abstractmethod
    async def read_data(
        self,
        table_name: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Read data from source.

        Args:
            table_name: Table to read from
            limit: Maximum rows to return
            filters: Filter conditions

        Returns:
            List of records as dictionaries
        """
        pass

    @abstractmethod
    async def sync_to_iceberg(
        self,
        source_table: str,
        target_table: str,
        sync_mode: SyncMode = SyncMode.FULL,
        incremental_column: Optional[str] = None,
        last_value: Optional[Any] = None,
        on_step=None,
        partition_spec: Optional[list] = None,
    ) -> SyncJobStatus:
        """
        Synchronize data to Iceberg table.

        Args:
            source_table: Source table name
            target_table: Target Iceberg table (format: catalog.schema.table)
            sync_mode: Synchronization mode
            incremental_column: Column for incremental sync
            last_value: Last synced value for incremental sync

        Returns:
            SyncJobStatus with execution details
        """
        pass

    async def close(self):
        """Close any open connections"""
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass


class ConnectorRegistry:
    """Registry of available connectors"""

    _connectors: Dict[ConnectorType, type] = {}

    @classmethod
    def register(cls, connector_type: ConnectorType):
        """Decorator to register a connector"""
        def wrapper(connector_class):
            cls._connectors[connector_type] = connector_class
            return connector_class
        return wrapper

    @classmethod
    def get_connector(cls, connector_type: ConnectorType) -> Optional[type]:
        """Get connector class by type"""
        return cls._connectors.get(connector_type)

    @classmethod
    def list_connectors(cls) -> List[Dict[str, Any]]:
        """List all registered connectors"""
        connectors = []
        for conn_type, conn_class in cls._connectors.items():
            connectors.append({
                "type": conn_type.value,
                "name": conn_type.value.replace("_", " ").title(),
                "class": conn_class.__name__,
                "description": conn_class.__doc__ or "No description"
            })
        return connectors
