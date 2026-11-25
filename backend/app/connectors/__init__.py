"""
DataPond Data Connectors Module

Data sources:
- Trino-backed sources (PostgreSQL, MySQL, SQL Server, Oracle, MongoDB, Redshift,
  BigQuery): each a Trino catalog, read and synced by Trino (trino_source, trino_sync)
- Amazon S3 (and S3-compatible storage)
- REST API connector (HTTP/HTTPS with auth)
- Custom Python connector (user-defined fetch_data())
"""

from .base import BaseConnector, ConnectorType, SyncMode
from .vault import CredentialVault
from .storage import S3Connector
from .rest import RestConnector, RestConfig
from .custom import CustomConnector, CustomConfig
from .trino_source import TrinoSourceConnector, TrinoSourceConfig
from . import probe, trino_sync

__all__ = [
    "BaseConnector",
    "ConnectorType",
    "SyncMode",
    "CredentialVault",
    "S3Connector",
    "RestConnector",
    "RestConfig",
    "CustomConnector",
    "CustomConfig",
    "TrinoSourceConnector",
    "TrinoSourceConfig",
    "probe",
    "trino_sync",
]
