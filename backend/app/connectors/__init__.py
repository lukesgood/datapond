"""
DataPond Data Connectors Module

Provides data ingestion capabilities from 50+ sources:
- Database connectors (PostgreSQL, MySQL, SQL Server)
- Universal database connector (SQLAlchemy connection string)
- Cloud storage (S3, Azure Blob, GCS)
- Streaming sources (Kafka, Kinesis)
- REST API connector (HTTP/HTTPS with auth)
- Custom Python connector (user-defined fetch_data())
- SaaS applications (via Airbyte)
"""

from .base import BaseConnector, ConnectorType, SyncMode
from .vault import CredentialVault
from .database import PostgreSQLConnector, MySQLConnector, DatabaseURLConnector, DatabaseURLConfig
from .storage import S3Connector
from .rest import RestConnector, RestConfig
from .custom import CustomConnector, CustomConfig

__all__ = [
    "BaseConnector",
    "ConnectorType",
    "SyncMode",
    "CredentialVault",
    "PostgreSQLConnector",
    "MySQLConnector",
    "DatabaseURLConnector",
    "DatabaseURLConfig",
    "S3Connector",
    "RestConnector",
    "RestConfig",
    "CustomConnector",
    "CustomConfig",
]
