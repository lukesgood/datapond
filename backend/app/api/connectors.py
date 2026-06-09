"""
FastAPI routes for DataPond connector management.

Endpoints:
- GET /api/connectors/available - List all available connectors
- POST /api/connectors/test - Test a connection
- POST /api/connectors/create - Create a new connection
- GET /api/connectors/connections - List active connections
- GET /api/connectors/{id} - Get connection details
- DELETE /api/connectors/{id} - Delete connection
- POST /api/connectors/{id}/sync - Trigger sync
- GET /api/connectors/{id}/status - Get sync status
- GET /api/connectors/{id}/tables - List tables for connection
- GET /api/connectors/{id}/schema/{table} - Get table schema
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional, Dict, Any, AsyncGenerator
from datetime import datetime
import uuid
import asyncpg
import asyncio
import json
import os
import logging
import httpx

from app.api.om_util import OPENMETADATA_URL, om_token as _om_token

logger = logging.getLogger(__name__)

# OM database FQN for the Trino/Iceberg service (created by the OM Trino ingestion).
# Synced tables are registered as entities under this database so they show up in
# the OM catalog without a manual ingestion run. Override per deployment if the
# OM databaseService is named differently.
OM_DATABASE_FQN = os.getenv("OPENMETADATA_ICEBERG_DB_FQN", "datapond-trino.iceberg")


async def register_lineage(source_fqn: str, target_fqn: str, connector_name: str) -> bool:
    """Best-effort: register a source→target table lineage edge in OpenMetadata.

    Resolves both tables to their entity IDs by FQN first — OM's lineage PUT needs
    real EntityReferences, and both endpoints must already exist as entities (see
    register_om_table / register_om_source_table). Returns True if the edge was
    accepted. Errors are swallowed (best-effort)."""
    try:
        token = await _om_token()
        if not token:
            return False
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=8) as c:
            sr = await c.get(f"{OPENMETADATA_URL}/api/v1/tables/name/{source_fqn}", headers=headers)
            tr = await c.get(f"{OPENMETADATA_URL}/api/v1/tables/name/{target_fqn}", headers=headers)
            if sr.status_code >= 300 or tr.status_code >= 300:
                logger.debug(f"[lineage] endpoint missing: src={sr.status_code} tgt={tr.status_code}")
                return False
            payload = {
                "edge": {
                    "fromEntity": {"type": "table", "id": sr.json()["id"]},
                    "toEntity":   {"type": "table", "id": tr.json()["id"]},
                    "lineageDetails": {
                        "description": f"Ingested by DataPond connector: {connector_name}",
                    },
                }
            }
            r = await c.put(f"{OPENMETADATA_URL}/api/v1/lineage", headers=headers, json=payload)
            return r.status_code < 300
    except Exception as e:
        logger.debug(f"[lineage] best-effort registration failed: {e}")
        return False


def _om_coltype(trino_type: str):
    """Map a Trino column type to an OpenMetadata (dataType, dataLength)."""
    t = (trino_type or "").lower()
    if t.startswith("bigint"):
        return "BIGINT", None
    if t.startswith("smallint"):
        return "SMALLINT", None
    if t.startswith("tinyint"):
        return "TINYINT", None
    if t.startswith("int"):
        return "INT", None
    if t.startswith("double"):
        return "DOUBLE", None
    if t.startswith("real") or t.startswith("float"):
        return "FLOAT", None
    if t.startswith("boolean"):
        return "BOOLEAN", None
    if t.startswith("date"):
        return "DATE", None
    if "timestamp" in t and "with time zone" in t:
        return "TIMESTAMPZ", None
    if "timestamp" in t:
        return "TIMESTAMP", None
    if t.startswith("decimal") or t.startswith("numeric"):
        return "DECIMAL", None
    if t.startswith(("varchar", "char", "varbinary", "json")):
        return "VARCHAR", 65535
    return "VARCHAR", 65535


def _trino_table_columns(target_schema: str, target_table: str):
    """[(name, trino_type)] for iceberg.<schema>.<table> via Trino information_schema.
    Synchronous (Trino client) — call via asyncio.to_thread.

    Uses a literal predicate, not a `?` bind: the Trino client's parameterized form
    returned an empty result set here. schema/table are internal sync targets; we
    still reject anything that isn't a bare identifier as an injection guard."""
    import re
    from app.api.trino_util import trino_conn
    if not (re.fullmatch(r"[A-Za-z0-9_]+", target_schema or "")
            and re.fullmatch(r"[A-Za-z0-9_]+", target_table or "")):
        return []
    conn = trino_conn(timeout=30)
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name, data_type FROM iceberg.information_schema.columns "
        f"WHERE table_schema = '{target_schema}' AND table_name = '{target_table}' "
        "ORDER BY ordinal_position"
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def _om_slug(s: str) -> str:
    """OM-safe identifier: collapse non-[A-Za-z0-9_] runs to '_'."""
    import re
    return re.sub(r"[^A-Za-z0-9_]+", "_", (s or "")).strip("_") or "src"


async def register_om_table(target_schema: str, target_table: str):
    """Best-effort, idempotent OpenMetadata ingestion for one synced Iceberg table.

    createOrUpdate the databaseSchema + table entity (columns read from Trino) under
    OM_DATABASE_FQN, so every sync reflects tables in the OM catalog without a manual
    ingestion run. Returns the OM column list on success, else None (best-effort)."""
    try:
        token = await _om_token()
        if not token:
            return None
        cols_raw = await asyncio.to_thread(_trino_table_columns, target_schema, target_table)
        if not cols_raw:
            return None
        columns = []
        for cname, ctype in cols_raw:
            dt, dl = _om_coltype(ctype)
            col = {"name": cname, "dataType": dt, "dataTypeDisplay": ctype}
            if dl:
                col["dataLength"] = dl
            columns.append(col)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=10) as c:
            # Ensure the schema exists (idempotent), then the table.
            await c.put(f"{OPENMETADATA_URL}/api/v1/databaseSchemas", headers=headers,
                        json={"name": target_schema, "database": OM_DATABASE_FQN})
            r = await c.put(f"{OPENMETADATA_URL}/api/v1/tables", headers=headers,
                            json={"name": target_table,
                                  "databaseSchema": f"{OM_DATABASE_FQN}.{target_schema}",
                                  "columns": columns})
            return columns if r.status_code < 300 else None
    except Exception as e:
        logger.debug(f"[om] table register failed for {target_schema}.{target_table}: {e}")
        return None


async def register_om_source_table(connector_type: str, connector_name: str,
                                   source_schema: str, source_table: str, columns) -> str | None:
    """Best-effort: register the connector's SOURCE table as an OM entity so the
    lineage edge has a valid 'from' endpoint. Uses a CustomDatabase service (no live
    connection / no connection-config validation). The synced Iceberg table is a full
    copy, so we reuse its columns. Returns the source table FQN, or None.

    FQN: datapond-<type>.<connector-slug>.<schema>.<table>
    """
    if not columns:
        return None
    try:
        token = await _om_token()
        if not token:
            return None
        svc = f"datapond-{_om_slug(connector_type)}"
        db = _om_slug(connector_name)
        sch = _om_slug(source_schema or "public")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=10) as c:
            await c.put(f"{OPENMETADATA_URL}/api/v1/services/databaseServices", headers=headers,
                        json={"name": svc, "serviceType": "CustomDatabase",
                              "connection": {"config": {"type": "CustomDatabase"}}})
            await c.put(f"{OPENMETADATA_URL}/api/v1/databases", headers=headers,
                        json={"name": db, "service": svc})
            await c.put(f"{OPENMETADATA_URL}/api/v1/databaseSchemas", headers=headers,
                        json={"name": sch, "database": f"{svc}.{db}"})
            r = await c.put(f"{OPENMETADATA_URL}/api/v1/tables", headers=headers,
                            json={"name": source_table,
                                  "databaseSchema": f"{svc}.{db}.{sch}",
                                  "columns": columns})
            return f"{svc}.{db}.{sch}.{source_table}" if r.status_code < 300 else None
    except Exception as e:
        logger.debug(f"[om] source register failed for {connector_name}.{source_table}: {e}")
        return None


from ..connectors.base import (
    ConnectorType,
    ConnectorRegistry,
    SyncMode,
    ConnectionStatus,
    SyncStatus
)
from ..connectors.database import DatabaseConfig, PostgreSQLConnector, MySQLConnector
from ..connectors.storage import StorageConfig, S3Connector
from ..connectors.vault import CredentialVault

router = APIRouter(tags=["connectors"])


# Pydantic models for API

class ConnectorInfo(BaseModel):
    """Available connector information"""
    id: str
    name: str
    category: str  # "database", "storage", "streaming", "saas"
    icon: str
    description: str
    supported: bool
    config_schema: Dict[str, Any]


class ConnectionTestRequest(BaseModel):
    """Request to test a connection"""
    connector_type: ConnectorType
    config: Dict[str, Any]
    connection_id: Optional[str] = None  # If editing existing, merge masked fields


class ConnectionCreateRequest(BaseModel):
    """Request to create a new connection"""
    name: str
    connector_type: ConnectorType
    config: Dict[str, Any]
    description: Optional[str] = None


class ConnectionResponse(BaseModel):
    """Connection response"""
    id: str
    name: str
    connector_type: str
    status: str
    created_at: datetime
    last_sync_at: Optional[datetime] = None
    schedule: Optional[str] = None


class SyncRequest(BaseModel):
    """Request to trigger a sync"""
    source_table: Optional[str] = None
    target_table: Optional[str] = None
    sync_mode: SyncMode = SyncMode.FULL
    incremental_column: Optional[str] = None


class SyncStatusResponse(BaseModel):
    """Sync status response"""
    job_id: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rows_processed: int = 0
    error_message: Optional[str] = None


# Database connection helper

_db_pool = None

async def get_db_pool():
    """Get shared PostgreSQL connection pool (singleton)"""
    global _db_pool
    if _db_pool is None or _db_pool._closed:
        _db_pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=5432,
            database=os.getenv("POSTGRES_DB", "datapond"),
            user=os.getenv("POSTGRES_USER", "datapond"),
            password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
            min_size=2,
            max_size=10,
        )
        # 풀 생성 시 1회 멱등 마이그레이션 (CREATE TABLE IF NOT EXISTS는 컬럼을 추가하지 않음).
        # 실패해도 무시하되, 매 호출이 아닌 풀 재생성 시에만 재시도한다.
        try:
            async with _db_pool.acquire() as conn:
                await conn.execute(
                    "ALTER TABLE connector_sync_jobs ADD COLUMN IF NOT EXISTS partition_spec JSONB"
                )
                # key_columns: 증분 upsert(merge)용 PK. NULL/[] = upsert 비활성(append).
                await conn.execute(
                    "ALTER TABLE connector_sync_jobs ADD COLUMN IF NOT EXISTS key_columns JSONB"
                )
                # pii_columns: 적재 전 마스킹할 컬럼(["*"]=모든 문자열 컬럼). NULL/[] = 비활성.
                await conn.execute(
                    "ALTER TABLE connector_sync_jobs ADD COLUMN IF NOT EXISTS pii_columns JSONB"
                )
        except Exception as e:
            logger.warning(f"[connectors] 컬럼 ensure 실패(무시): {e}")
    return _db_pool


def _parse_key_columns(raw):
    """JSONB key_columns 값을 list|None으로 정규화(빈 리스트는 None 취급=upsert 비활성)."""
    if raw is None:
        return None
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    return v if (isinstance(v, list) and len(v) > 0) else None


async def _load_key_columns(pool, connection_id: str, table: str):
    """connector_sync_jobs에서 테이블의 key_columns(upsert PK)를 읽어 list|None 반환."""
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT key_columns FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
            uuid.UUID(connection_id), table
        )
    return _parse_key_columns(raw)


async def _load_pii_columns(pool, connection_id: str, table: str):
    """connector_sync_jobs에서 테이블의 pii_columns(적재 전 마스킹 대상)를 읽어 list|None 반환."""
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT pii_columns FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
            uuid.UUID(connection_id), table
        )
    return _parse_key_columns(raw)  # 동일 정규화(list|None, ["*"] 보존)


def _parse_partition_spec(raw):
    """JSONB partition_spec 값을 list|None으로 정규화. []('무파티션')도 그대로 보존한다.

    asyncpg는 기본적으로 JSONB를 str로 반환하지만(codec 미등록), codec이 등록된 환경에서는
    list를 반환할 수 있으므로 두 경우를 모두 처리한다. None(자동 추론)과 [](무파티션)을
    구분하기 위해 호출부는 falsy 검사 대신 이 함수를 사용한다.
    """
    if raw is None:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None


async def _load_partition_spec(pool, connection_id: str, table: str):
    """connector_sync_jobs에서 테이블의 partition_spec을 읽어 list|None으로 반환."""
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT partition_spec FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
            uuid.UUID(connection_id), table
        )
    return _parse_partition_spec(raw)


# Credential vault instance

vault = CredentialVault()


# API Endpoints

@router.get("/connectors/available", response_model=List[ConnectorInfo])
async def list_available_connectors():
    """
    List all available data connectors.

    Returns connector metadata including configuration schema.
    """
    connectors = [
        {
            "id": "postgresql",
            "name": "PostgreSQL",
            "category": "database",
            "icon": "/icons/postgresql.svg",
            "description": "Connect to PostgreSQL databases (v9.6+)",
            "supported": True,
            "config_schema": {
                "host": {"type": "string", "required": True},
                "port": {"type": "integer", "default": 5432},
                "database": {"type": "string", "required": True},
                "username": {"type": "string", "required": True},
                "password": {"type": "password", "required": True},
                "ssl": {"type": "boolean", "default": False}
            }
        },
        {
            "id": "mysql",
            "name": "MySQL",
            "category": "database",
            "icon": "/icons/mysql.svg",
            "description": "Connect to MySQL and MariaDB databases",
            "supported": True,
            "config_schema": {
                "host": {"type": "string", "required": True},
                "port": {"type": "integer", "default": 3306},
                "database": {"type": "string", "required": True},
                "username": {"type": "string", "required": True},
                "password": {"type": "password", "required": True},
                "ssl": {"type": "boolean", "default": False}
            }
        },
        {
            "id": "s3",
            "name": "Amazon S3",
            "category": "storage",
            "icon": "/icons/s3.svg",
            "description": "Connect to AWS S3 buckets",
            "supported": True,
            "config_schema": {
                "bucket": {"type": "string", "required": True},
                "access_key": {"type": "string", "required": True},
                "secret_key": {"type": "password", "required": True},
                "region": {"type": "string", "default": "us-east-1"},
                "endpoint_url": {"type": "string", "required": False}
            }
        },
        {
            "id": "sqlserver",
            "name": "SQL Server",
            "category": "database",
            "icon": "/icons/sqlserver.svg",
            "description": "Connect to Microsoft SQL Server",
            "supported": False,
            "config_schema": {}
        },
        {
            "id": "mongodb",
            "name": "MongoDB",
            "category": "database",
            "icon": "/icons/mongodb.svg",
            "description": "Connect to MongoDB databases",
            "supported": False,
            "config_schema": {}
        },
        {
            "id": "kafka",
            "name": "Apache Kafka",
            "category": "streaming",
            "icon": "/icons/kafka.svg",
            "description": "Stream data from Kafka topics",
            "supported": False,
            "config_schema": {}
        },
        {
            "id": "database_url",
            "name": "Universal Database (SQLAlchemy)",
            "category": "database",
            "icon": "/icons/database_url.svg",
            "description": "SQLAlchemy 연결 문자열로 모든 데이터베이스 연결. Oracle, SQL Server, Snowflake, Redshift 등.",
            "supported": True,
            "config_schema": {
                "database_url": {
                    "type": "string",
                    "required": True,
                    "placeholder": "postgresql://user:pass@host:5432/db"
                },
                "query": {
                    "type": "string",
                    "required": False,
                    "placeholder": "SELECT 1 (test query)"
                }
            }
        },
        {
            "id": "rest_api",
            "name": "REST API",
            "category": "saas",
            "icon": "/icons/rest_api.svg",
            "description": "HTTP/HTTPS REST API 엔드포인트에서 데이터 수집. Bearer, Basic, API Key 인증 지원.",
            "supported": True,
            "config_schema": {
                "base_url": {"type": "string", "required": True},
                "auth_type": {
                    "type": "select",
                    "options": ["none", "bearer", "basic", "api_key"],
                    "default": "none"
                },
                "auth_value": {"type": "password", "required": False},
                "auth_header": {
                    "type": "string",
                    "required": False,
                    "default": "Authorization"
                },
                "data_path": {
                    "type": "string",
                    "required": False,
                    "placeholder": "data.items"
                }
            }
        },
        {
            "id": "custom",
            "name": "Custom Python",
            "category": "saas",
            "icon": "/icons/custom.svg",
            "description": "Python 코드를 직접 작성해 어떤 소스든 연결. fetch_data() 함수를 정의하면 됩니다.",
            "supported": True,
            "config_schema": {
                "code": {"type": "text", "required": True}
            }
        }
    ]

    return connectors


@router.post("/connectors/test")
async def test_connection(request: ConnectionTestRequest):
    """
    Test a connector connection without saving it.

    Validates credentials and connectivity.
    If connection_id is provided, masked fields (••••••••) are replaced with stored values.
    """
    try:
        config = dict(request.config)

        # If editing existing connection, replace masked fields with stored originals
        if request.connection_id:
            has_masked = any(v == "••••••••" for v in config.values() if isinstance(v, str))
            if has_masked:
                pool = await get_db_pool()
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT config_encrypted FROM connector_connections WHERE id=$1",
                        uuid.UUID(request.connection_id)
                    )
                if row:
                    stored = vault.decrypt_credentials(row['config_encrypted'])
                    for k, v in config.items():
                        if v == "••••••••":
                            config[k] = stored.get(k, v)

        # Create connector instance based on type
        connector = _create_connector(request.connector_type, config)

        # Test connection
        result = await connector.test_connection()

        return {
            "success": result.success,
            "message": result.message,
            "latency_ms": result.latency_ms,
            "metadata": result.metadata
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Test failed: {str(e)}",
            "latency_ms": None,
            "metadata": {}
        }


@router.post("/connectors/sample-db")
async def create_sample_db():
    """
    Create sample e-commerce DB in local PostgreSQL and register as a connector.
    Idempotent — safe to call multiple times.
    """
    import asyncpg as _asyncpg

    SAMPLE_DDL = """
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL, country VARCHAR(50) DEFAULT 'KR',
    tier VARCHAR(20) DEFAULT 'standard', signup_date DATE DEFAULT CURRENT_DATE,
    is_active BOOLEAN DEFAULT true, created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY, sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL, category VARCHAR(50) NOT NULL,
    price NUMERIC(10,2) NOT NULL, cost NUMERIC(10,2),
    stock_qty INTEGER DEFAULT 0, is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
    status VARCHAR(20) DEFAULT 'pending', total_amount NUMERIC(10,2) NOT NULL,
    discount NUMERIC(10,2) DEFAULT 0, channel VARCHAR(30) DEFAULT 'web',
    ordered_at TIMESTAMPTZ DEFAULT NOW(), shipped_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 1, unit_price NUMERIC(10,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS page_events (
    id BIGSERIAL PRIMARY KEY, customer_id INTEGER,
    event_type VARCHAR(50) NOT NULL, page VARCHAR(255),
    device VARCHAR(20) DEFAULT 'desktop', session_id VARCHAR(64),
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);
"""

    try:
        # 1. Create sampledb if not exists (connect to postgres db first)
        sys_conn = await _asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=5432,
            database="postgres",
            user=os.getenv("POSTGRES_USER", "datapond"),
            password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
        )
        db_exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname='sampledb'"
        )
        if not db_exists:
            await sys_conn.execute("CREATE DATABASE sampledb")
        await sys_conn.close()

        # 2. Connect to sampledb and create schema + seed data
        sample_conn = await _asyncpg.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=5432,
            database="sampledb",
            user=os.getenv("POSTGRES_USER", "datapond"),
            password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
        )
        await sample_conn.execute(SAMPLE_DDL)

        # Check if data already exists
        cust_count = await sample_conn.fetchval("SELECT COUNT(*) FROM customers")
        if cust_count == 0:
            await sample_conn.execute("""
INSERT INTO customers (email,full_name,country,tier,signup_date) VALUES
  ('alice@acme.com','Alice Kim','KR','vip','2023-01-15'),
  ('bob@example.com','Bob Lee','KR','premium','2023-03-20'),
  ('carol@corp.io','Carol Park','US','standard','2023-06-01'),
  ('dave@startup.kr','Dave Choi','KR','premium','2023-08-12'),
  ('eve@finance.co','Eve Jung','KR','vip','2024-01-05'),
  ('frank@bank.com','Frank Oh','JP','standard','2024-02-18'),
  ('grace@health.io','Grace Shin','KR','standard','2024-03-30'),
  ('henry@mfg.com','Henry Han','KR','premium','2024-05-10'),
  ('iris@defense.kr','Iris Yoon','KR','vip','2024-07-22'),
  ('jake@data.com','Jake Kwon','SG','standard','2024-09-01')
ON CONFLICT DO NOTHING
""")
            await sample_conn.execute("""
INSERT INTO products (sku,name,category,price,cost,stock_qty) VALUES
  ('SKU-001','DataPond Enterprise License','software',4990000,500000,999),
  ('SKU-002','AI Analytics Add-on','software',1990000,200000,999),
  ('SKU-003','On-Prem Support Package','service',2500000,800000,50),
  ('SKU-004','GPU Compute Node 4xA100','hardware',45000000,35000000,10),
  ('SKU-005','NVMe Storage Array 100TB','hardware',12000000,9000000,20),
  ('SKU-006','Training and Onboarding','service',3000000,500000,100),
  ('SKU-007','Migration Consulting','service',5000000,1000000,30),
  ('SKU-008','Streaming Module License','software',1500000,150000,999)
ON CONFLICT DO NOTHING
""")
            await sample_conn.execute("""
INSERT INTO orders (customer_id,status,total_amount,discount,channel,ordered_at,shipped_at,delivered_at) VALUES
  (1,'delivered',4990000,0,'direct',NOW()-'90 days'::interval,NOW()-'88 days'::interval,NOW()-'85 days'::interval),
  (1,'delivered',1990000,199000,'web',NOW()-'60 days'::interval,NOW()-'58 days'::interval,NOW()-'55 days'::interval),
  (2,'delivered',7490000,0,'direct',NOW()-'75 days'::interval,NOW()-'73 days'::interval,NOW()-'70 days'::interval),
  (3,'shipped',2500000,0,'web',NOW()-'5 days'::interval,NOW()-'3 days'::interval,NULL),
  (4,'confirmed',6490000,649000,'partner',NOW()-'2 days'::interval,NULL,NULL),
  (5,'delivered',45000000,4500000,'direct',NOW()-'45 days'::interval,NOW()-'42 days'::interval,NOW()-'38 days'::interval),
  (6,'pending',1500000,0,'web',NOW()-'1 day'::interval,NULL,NULL),
  (7,'delivered',3000000,0,'partner',NOW()-'30 days'::interval,NOW()-'28 days'::interval,NOW()-'25 days'::interval),
  (8,'delivered',12000000,600000,'direct',NOW()-'20 days'::interval,NOW()-'18 days'::interval,NOW()-'15 days'::interval),
  (9,'confirmed',8490000,0,'web',NOW()-'3 days'::interval,NULL,NULL),
  (10,'delivered',4990000,0,'web',NOW()-'10 days'::interval,NOW()-'8 days'::interval,NOW()-'5 days'::interval),
  (1,'pending',5000000,0,'direct',NOW()-'1 day'::interval,NULL,NULL),
  (2,'cancelled',2500000,0,'web',NOW()-'15 days'::interval,NULL,NULL)
""")
            await sample_conn.execute("""
INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES
  (1,1,1,4990000),(2,2,1,1990000),(3,1,1,4990000),(3,3,1,2500000),
  (4,3,1,2500000),(5,1,1,4990000),(5,2,1,1990000),(5,8,1,1500000),
  (6,4,1,45000000),(7,8,1,1500000),(8,6,1,3000000),(9,5,1,12000000),
  (10,1,1,4990000),(10,7,1,5000000),(11,1,1,4990000),(12,1,1,4990000)
""")
            await sample_conn.execute("""
INSERT INTO page_events (customer_id,event_type,page,device,session_id) VALUES
  (1,'page_view','/pricing','desktop','sess_001'),
  (1,'click','/pricing','desktop','sess_001'),
  (2,'page_view','/features','mobile','sess_002'),
  (3,'page_view','/docs','desktop','sess_003'),
  (4,'signup','/register','desktop','sess_004'),
  (5,'page_view','/dashboard','desktop','sess_005'),
  (NULL,'page_view','/landing','mobile','sess_006'),
  (NULL,'page_view','/landing','desktop','sess_007'),
  (6,'page_view','/pricing','tablet','sess_008'),
  (7,'page_view','/blog','desktop','sess_009')
""")
        await sample_conn.close()

        # 3. Register as connector (idempotent)
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM connector_connections WHERE name='Sample E-Commerce DB'"
            )

        if existing:
            return {
                "id": str(existing),
                "name": "Sample E-Commerce DB",
                "connector_type": "postgresql",
                "status": "active",
                "created_at": datetime.utcnow(),
                "already_existed": True,
            }

        # Create new connector entry
        connection_id = str(uuid.uuid4())
        sample_config = {
            "host": os.getenv("POSTGRES_HOST", "postgres"),
            "port": 5432,
            "database": "sampledb",
            "username": os.getenv("POSTGRES_USER", "datapond"),
            "password": os.getenv("POSTGRES_PASSWORD", "dev_password"),
            "ssl": False,
        }
        encrypted = vault.encrypt_credentials(sample_config)
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO connector_connections
                (id, name, connector_type, config_encrypted, status, created_at, updated_at)
                VALUES ($1,$2,'postgresql',$3,'active',$4,$4)
            """, connection_id, "Sample E-Commerce DB", encrypted, datetime.utcnow())

        return {
            "id": connection_id,
            "name": "Sample E-Commerce DB",
            "connector_type": "postgresql",
            "status": "active",
            "created_at": datetime.utcnow(),
            "already_existed": False,
            "tables": ["customers", "products", "orders", "order_items", "page_events"],
            "message": "Sample DB created with 5 tables and demo data",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create sample DB: {str(e)}")


@router.delete("/connectors/{connection_id}/draft")
async def discard_draft_connection(connection_id: str):
    """Discard a connection created during setup wizard (no sync history).
    Used when user clicks Back/Cancel after Step 1 to prevent orphan records."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            # Only allow deletion if never synced (no history, no jobs with last_run_at)
            has_synced = await conn.fetchval(
                "SELECT COUNT(*) FROM connector_sync_history WHERE metadata->>'connection_id'=$1",
                connection_id
            )
            if has_synced and has_synced > 0:
                raise HTTPException(status_code=409, detail="Cannot discard — connection has sync history")
            # Remove DAG file if exists
            import pathlib, glob
            dag_files = glob.glob(f"/opt/airflow/dags/datapond_sync_*.py")
            for f in dag_files:
                if connection_id in open(f).read():
                    pathlib.Path(f).unlink(missing_ok=True)
            # Delete connection (cascade removes sync_jobs)
            await conn.execute("DELETE FROM connector_connections WHERE id=$1", uuid.UUID(connection_id))
        return {"message": "Draft connection discarded"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connectors/create", response_model=ConnectionResponse)
async def create_connection(request: ConnectionCreateRequest):
    """
    Create and save a new connector connection.

    Tests connectivity first, then encrypts credentials before storage.
    Status is set to 'active' on success, 'error' on connection failure.
    """
    try:
        # Generate connection ID
        connection_id = str(uuid.uuid4())

        # Test connection before saving
        status = ConnectionStatus.ACTIVE.value
        try:
            connector = _create_connector(request.connector_type, request.config)
            result = await connector.test_connection()
            if not result.success:
                status = "error"
        except Exception:
            status = "error"

        # Encrypt credentials
        encrypted_config = vault.encrypt_credentials(request.config)

        # Store in database
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO connector_connections
                (id, name, connector_type, config_encrypted, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            ''',
                connection_id,
                request.name,
                request.connector_type.value,
                encrypted_config,
                status,
                datetime.utcnow(),
                datetime.utcnow()
            )

        return ConnectionResponse(
            id=connection_id,
            name=request.name,
            connector_type=request.connector_type.value,
            status=status,
            created_at=datetime.utcnow()
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create connection: {str(e)}")


@router.get("/connectors/connections")
async def list_connections():
    """
    List all saved connections.

    Does not include credentials in response.
    """
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT id, name, connector_type, status, created_at, last_sync_at, schedule
                FROM connector_connections
                ORDER BY created_at DESC
            ''')

        connections = []
        for row in rows:
            connections.append({
                "id": str(row['id']),
                "name": row['name'],
                "connector_type": row['connector_type'],
                "status": row['status'],
                "created_at": row['created_at'].isoformat() + "Z",
                "last_sync_at": row['last_sync_at'].isoformat() + "Z" if row['last_sync_at'] else None,
                "schedule": row['schedule'],
            })

        return connections

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list connections: {str(e)}")


@router.get("/connectors/{connection_id}")
async def get_connection(connection_id: str):
    """Get connection details by ID"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT id, name, connector_type, status, created_at, last_sync_at, schedule
                FROM connector_connections
                WHERE id = $1
            ''', uuid.UUID(connection_id))

        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")

        return {
            "id": str(row['id']),
            "name": row['name'],
            "connector_type": row['connector_type'],
            "status": row['status'],
            "created_at": row['created_at'].isoformat() + "Z",
            "last_sync_at": row['last_sync_at'].isoformat() + "Z" if row['last_sync_at'] else None,
            "schedule": row['schedule'],
        }

    except (HTTPException, ValueError) as e:
        if isinstance(e, ValueError):
            raise HTTPException(status_code=400, detail="Invalid connection ID")
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connection_id}/config")
async def get_connection_config(connection_id: str):
    """Get decrypted config for a connection (for editing)"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT name, connector_type, config_encrypted, description
                FROM connector_connections WHERE id = $1
            ''', uuid.UUID(connection_id))
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = vault.decrypt_credentials(row['config_encrypted'])
        # Mask password fields
        masked = {k: ("••••••••" if "password" in k.lower() or "secret" in k.lower() or "key" in k.lower() else v)
                  for k, v in config.items() if k not in ("name", "connector_type")}
        return {
            "name": row['name'],
            "connector_type": row['connector_type'],
            "description": row['description'],
            "config": masked
        }
    except (HTTPException, ValueError) as e:
        if isinstance(e, ValueError):
            raise HTTPException(status_code=400, detail="Invalid connection ID")
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ConnectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


@router.patch("/connectors/{connection_id}")
async def update_connection(connection_id: str, request: ConnectionUpdateRequest):
    """Update connection name and/or config"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT name, connector_type, config_encrypted
                FROM connector_connections WHERE id = $1
            ''', uuid.UUID(connection_id))
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")

        new_name = request.name or row['name']
        if request.config is not None:
            # Merge with existing config (keep existing values for masked/empty fields)
            # Always remove ingestion metadata that should not be in DB connection config
            INGESTION_KEYS = {"sync_frequency", "sync_mode", "selected_tables", "schedule"}
            existing = vault.decrypt_credentials(row['config_encrypted'])
            # Strip ingestion keys from existing
            merged = {k: v for k, v in existing.items() if k not in INGESTION_KEYS}
            for k, v in request.config.items():
                if v not in ("••••••••", "") and k not in ("name", "connector_type") and k not in INGESTION_KEYS:
                    merged[k] = v
            new_config = vault.encrypt_credentials(merged)
        else:
            new_config = row['config_encrypted']

        async with pool.acquire() as conn:
            await conn.execute('''
                UPDATE connector_connections
                SET name = $1, config_encrypted = $2, updated_at = $3
                WHERE id = $4
            ''', new_name, new_config, datetime.utcnow(), uuid.UUID(connection_id))

        return {"message": "Connection updated successfully"}
    except (HTTPException, ValueError) as e:
        if isinstance(e, ValueError):
            raise HTTPException(status_code=400, detail="Invalid connection ID")
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ScheduleRequest(BaseModel):
    schedule: Optional[str] = None   # cron expression or None to disable


def _generate_sync_dag(connection_id: str, connection_name: str, schedule: str) -> str:
    safe_name = connection_name.lower().replace(" ", "_").replace("-", "_")
    dag_id = f"datapond_sync_{safe_name}"
    return f'''"""Auto-generated by DataPond — sync DAG for connector '{connection_name}'"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import requests

default_args = {{
    "owner": "datapond",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}}

def run_sync(**kwargs):
    resp = requests.post(
        "http://backend.datapond.svc.cluster.local:8000/api/connectors/{connection_id}/sync",
        json={{}}, timeout=600
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"Sync result: {{result}}")
    if result.get("status") == "failed":
        raise Exception(f"Sync failed: {{result.get('message')}}")

with DAG(
    dag_id="{dag_id}",
    default_args=default_args,
    description="DataPond sync: {connection_name}",
    schedule_interval="{schedule}",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["datapond", "sync", "connector"],
) as dag:
    sync_task = PythonOperator(
        task_id="sync_{safe_name}",
        python_callable=run_sync,
    )
'''


@router.patch("/connectors/{connection_id}/schedule")
async def set_schedule(connection_id: str, request: ScheduleRequest):
    """Set or remove a sync schedule. Stores in connector_connections.schedule (single source of truth)."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name FROM connector_connections WHERE id=$1",
                uuid.UUID(connection_id)
            )
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")

        connection_name = row['name']
        safe_name = connection_name.lower().replace(" ", "_").replace("-", "_")
        dag_path = f"/opt/airflow/dags/datapond_sync_{safe_name}.py"

        if request.schedule:
            # 1. Write DAG file
            dag_code = _generate_sync_dag(connection_id, connection_name, request.schedule)
            with open(dag_path, "w") as f:
                f.write(dag_code)

            # 2. Save to connector_connections (single source of truth)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE connector_connections SET schedule=$1 WHERE id=$2",
                    request.schedule, uuid.UUID(connection_id)
                )

            return {
                "message": f"Schedule '{request.schedule}' set for '{connection_name}'",
                "dag_id": f"datapond_sync_{safe_name}",
                "schedule": request.schedule,
                "dag_active": True,
            }
        else:
            # Remove DAG file
            import pathlib
            p = pathlib.Path(dag_path)
            if p.exists():
                p.unlink()

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE connector_connections SET schedule=NULL WHERE id=$1",
                    uuid.UUID(connection_id)
                )

            return {"message": f"Schedule removed for '{connection_name}'", "schedule": None, "dag_active": False}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connection_id}/schedule")
async def get_schedule(connection_id: str):
    """Get current schedule from connector_connections (single source of truth)."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, schedule FROM connector_connections WHERE id=$1",
                uuid.UUID(connection_id)
            )
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")

        schedule = row['schedule']
        connection_name = row['name']
        safe_name = connection_name.lower().replace(" ", "_").replace("-", "_")

        # Verify DAG file actually exists (schedule DB and file should be in sync)
        import pathlib
        dag_path = pathlib.Path(f"/opt/airflow/dags/datapond_sync_{safe_name}.py")
        dag_file_exists = dag_path.exists()

        # Auto-repair: if schedule set but DAG missing, recreate
        if schedule and not dag_file_exists:
            dag_code = _generate_sync_dag(connection_id, connection_name, schedule)
            dag_path.write_text(dag_code)
            dag_file_exists = True

        # Auto-repair: if DAG exists but schedule cleared, remove DAG
        if not schedule and dag_file_exists:
            dag_path.unlink()
            dag_file_exists = False

        return {"schedule": schedule, "dag_active": dag_file_exists}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/connectors/{connection_id}")
async def delete_connection(connection_id: str):
    """Delete a connection"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            result = await conn.execute('''
                DELETE FROM connector_connections
                WHERE id = $1
            ''', uuid.UUID(connection_id))

        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Connection not found")

        return {"message": "Connection deleted successfully"}

    except (HTTPException, ValueError) as e:
        if isinstance(e, ValueError):
            raise HTTPException(status_code=400, detail="Invalid connection ID")
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connection_id}/tables")
async def list_tables(connection_id: str):
    """List tables with enabled status from connector_sync_jobs."""
    try:
        connector = await _get_connector_instance(connection_id)
        tables = await connector.get_tables()

        # Load full config per table from DB
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source_table, enabled, sync_mode, incremental_column, last_value, partition_spec, key_columns, pii_columns FROM connector_sync_jobs WHERE connection_id=$1",
                uuid.UUID(connection_id)
            )
        config_map = {r['source_table']: r for r in rows}

        def _table_info(t: str) -> dict:
            cfg = config_map.get(t)
            mode = (cfg['sync_mode'] or "full") if cfg else "full"
            inc_col = cfg['incremental_column'] if cfg else None
            last_val = cfg['last_value'] if cfg else None
            enabled = cfg['enabled'] if cfg else True
            raw_ps = cfg['partition_spec'] if cfg else None
            try:
                part_spec = json.loads(raw_ps) if isinstance(raw_ps, str) else raw_ps
            except (ValueError, TypeError):
                part_spec = None
            # Warn: incremental set but no column → effectively full
            effective_mode = mode
            if mode == "incremental" and not inc_col:
                effective_mode = "incremental_no_col"  # UI can show warning
            return {
                "name": t,
                "enabled": enabled,
                "sync_mode": mode,
                "effective_mode": effective_mode,
                "incremental_column": inc_col,
                "last_value": last_val,
                "partition_spec": part_spec,
                "key_columns": _parse_key_columns(cfg['key_columns']) if cfg else None,
                "pii_columns": _parse_key_columns(cfg['pii_columns']) if cfg else None,
            }

        return {"tables": [_table_info(t) for t in tables]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tables: {str(e)}")


@router.patch("/connectors/{connection_id}/tables/{table_name}/enabled")
async def set_table_enabled(connection_id: str, table_name: str, body: dict):
    """Enable/disable a table and optionally set incremental_column / key_columns(upsert PK)."""
    try:
        enabled             = bool(body.get("enabled", True))
        incremental_column  = body.get("incremental_column")   # None = don't change
        key_columns         = body.get("key_columns", "__keep__")  # list|[]|None; sentinel=don't change
        pii_columns         = body.get("pii_columns", "__keep__")  # list|["*"]|[]; sentinel=don't change
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
                uuid.UUID(connection_id), table_name
            )
            if existing:
                sets = ["enabled=$1"]
                vals = [enabled]
                if incremental_column is not None:
                    sets.append(f"incremental_column=${len(vals)+1}")
                    vals.append(incremental_column or None)
                if key_columns != "__keep__":
                    kc = key_columns if (isinstance(key_columns, list) and key_columns) else None
                    sets.append(f"key_columns=${len(vals)+1}::jsonb")
                    vals.append(json.dumps(kc) if kc else None)
                if pii_columns != "__keep__":
                    pc = pii_columns if (isinstance(pii_columns, list) and pii_columns) else None
                    sets.append(f"pii_columns=${len(vals)+1}::jsonb")
                    vals.append(json.dumps(pc) if pc else None)
                vals += [uuid.UUID(connection_id), table_name]
                await conn.execute(
                    f"UPDATE connector_sync_jobs SET {', '.join(sets)} "
                    f"WHERE connection_id=${len(vals)-1} AND source_table=${len(vals)}",
                    *vals
                )
            else:
                await conn.execute(
                    """INSERT INTO connector_sync_jobs
                       (id, connection_id, source_table, target_table, sync_mode, enabled, incremental_column)
                       VALUES ($1,$2,$3,$4,'full',$5,$6)""",
                    uuid.UUID(str(uuid.uuid4())), uuid.UUID(connection_id),
                    table_name, f"datapond.default.{table_name}",
                    enabled, incremental_column or None
                )
        return {"table": table_name, "enabled": enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_PARTITION_TRANSFORMS = {"day", "month", "year", "identity", "bucket"}


@router.patch("/connectors/{connection_id}/tables/{table_name}/partition")
async def set_table_partition(connection_id: str, table_name: str, body: dict):
    """
    테이블별 파티션 spec 설정.
    body: {"partition_spec": [{"column":"created_at","transform":"day"}, ...]}  · null/[] = 무파티션(자동추론 해제)
    """
    try:
        spec = body.get("partition_spec")
        if spec is not None:
            if not isinstance(spec, list):
                raise HTTPException(status_code=400, detail="partition_spec must be a list or null")
            for f in spec:
                if not isinstance(f, dict) or not f.get("column"):
                    raise HTTPException(status_code=400, detail="each partition field needs a 'column'")
                tr = f.get("transform", "identity")
                if tr not in _PARTITION_TRANSFORMS:
                    raise HTTPException(status_code=400, detail=f"invalid transform '{tr}' (allowed: {sorted(_PARTITION_TRANSFORMS)})")
        spec_json = json.dumps(spec) if spec is not None else None

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
                uuid.UUID(connection_id), table_name
            )
            if existing:
                await conn.execute(
                    "UPDATE connector_sync_jobs SET partition_spec=$1 WHERE connection_id=$2 AND source_table=$3",
                    spec_json, uuid.UUID(connection_id), table_name
                )
            else:
                await conn.execute(
                    """INSERT INTO connector_sync_jobs
                       (id, connection_id, source_table, target_table, sync_mode, enabled, partition_spec)
                       VALUES ($1,$2,$3,$4,'full',true,$5)""",
                    uuid.UUID(str(uuid.uuid4())), uuid.UUID(connection_id),
                    table_name, f"datapond.default.{table_name}", spec_json
                )
        return {"table": table_name, "partition_spec": spec}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/connectors/{connection_id}/sync-mode")
async def set_connection_sync_mode(connection_id: str, body: dict):
    """Set sync_mode — for a specific table or all tables of a connection."""
    try:
        mode = body.get("sync_mode", "full")
        table_name = body.get("table_name")  # Optional: specific table only
        if mode not in ("full", "incremental"):
            raise HTTPException(status_code=400, detail=f"Invalid sync_mode: {mode}")
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if table_name:
                # Per-table update
                existing = await conn.fetchval(
                    "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
                    uuid.UUID(connection_id), table_name
                )
                if existing:
                    await conn.execute(
                        "UPDATE connector_sync_jobs SET sync_mode=$1 WHERE connection_id=$2 AND source_table=$3",
                        mode, uuid.UUID(connection_id), table_name
                    )
                else:
                    await conn.execute(
                        """INSERT INTO connector_sync_jobs
                           (id, connection_id, source_table, target_table, sync_mode, enabled)
                           VALUES ($1,$2,$3,$4,$5,true)""",
                        uuid.UUID(str(uuid.uuid4())), uuid.UUID(connection_id),
                        table_name, f"datapond.default.{table_name}", mode
                    )
            else:
                # All tables update
                await conn.execute(
                    "UPDATE connector_sync_jobs SET sync_mode=$1 WHERE connection_id=$2",
                    mode, uuid.UUID(connection_id)
                )
        return {"sync_mode": mode, "table": table_name or "all"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connection_id}/schema/{table_name}")
async def get_table_schema(connection_id: str, table_name: str):
    """Get schema for a specific table"""
    try:
        connector = await _get_connector_instance(connection_id)

        schema = await connector.get_schema(table_name)

        return schema.dict()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get schema: {str(e)}")


@router.get("/connectors/{connection_id}/sync/stream")
async def sync_stream(connection_id: str, sync_mode: str = "full"):
    """SSE endpoint — streams sync progress step by step."""

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    async def generate() -> AsyncGenerator[str, None]:
        started_at = datetime.utcnow()
        total_rows = 0
        job_id = str(uuid.uuid4())

        try:
            yield sse("start", {"job_id": job_id, "message": "Initializing sync…", "ts": started_at.isoformat() + "Z"})
            await asyncio.sleep(0)

            # Get connector
            yield sse("step", {"step": "connect", "message": "Connecting to source…", "status": "running"})
            await asyncio.sleep(0)
            try:
                connector = await _get_connector_instance(connection_id)
            except HTTPException as e:
                yield sse("error", {"message": e.detail})
                return

            yield sse("step", {"step": "connect", "message": "Connection established", "status": "done"})
            await asyncio.sleep(0)

            # Discover tables
            yield sse("step", {"step": "discover", "message": "Discovering tables…", "status": "running"})
            await asyncio.sleep(0)
            mode = SyncMode(sync_mode) if sync_mode in [m.value for m in SyncMode] else SyncMode.FULL
            all_tables = await connector.get_tables()
            if not all_tables:
                yield sse("done", {"message": "No tables found", "rows_processed": 0, "tables": 0})
                return

            # Load full table config (enabled, sync_mode, incremental_column, last_value)
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                enabled_rows = await conn.fetch(
                    """SELECT source_table, enabled, sync_mode, incremental_column, last_value, partition_spec, key_columns, pii_columns
                       FROM connector_sync_jobs WHERE connection_id=$1""",
                    uuid.UUID(connection_id)
                )
            job_map = {r['source_table']: r for r in enabled_rows}
            enabled_map = {r['source_table']: r['enabled'] for r in enabled_rows}
            # Tables not yet in DB are enabled by default
            tables = [t for t in all_tables if enabled_map.get(t, True)]
            skipped = [t for t in all_tables if not enabled_map.get(t, True)]

            yield sse("step", {
                "step": "discover",
                "message": f"Found {len(all_tables)} tables, {len(tables)} enabled" + (f", {len(skipped)} skipped" if skipped else ""),
                "status": "done", "tables": tables, "skipped": skipped
            })
            await asyncio.sleep(0)

            if not tables:
                yield sse("done", {"message": "All tables disabled — nothing to sync", "rows_processed": 0, "tables": 0})
                return
            results = []
            for i, table in enumerate(tables):
                target = f"datapond.default.{table}"

                # Per-table mode: use stored sync_mode (overrides global mode)
                job = job_map.get(table)
                table_mode = SyncMode.FULL
                if job and job['sync_mode']:
                    try:
                        table_mode = SyncMode(job['sync_mode'])
                    except ValueError:
                        table_mode = mode  # fallback to global

                # Load watermark for incremental mode
                last_value = None
                incremental_column = None
                if table_mode == SyncMode.INCREMENTAL:
                    incremental_column = job['incremental_column'] if job else None
                    last_value = job['last_value'] if job else None
                    if incremental_column:
                        yield sse("table_start", {
                            "table": table, "index": i, "total": len(tables),
                            "message": f"Syncing {table}… ({i+1}/{len(tables)})"
                            + (f" [incremental since {last_value}]" if last_value else " [first incremental run — full load]"),
                        })
                    else:
                        # No incremental_column configured — fall back to full
                        table_mode = SyncMode.FULL

                # Emit table_start (if not already emitted for incremental)
                if table_mode != SyncMode.INCREMENTAL or not incremental_column:
                    yield sse("table_start", {
                        "table": table, "index": i, "total": len(tables),
                        "message": f"Syncing {table}… ({i+1}/{len(tables)}) [{table_mode.value}]",
                    })
                await asyncio.sleep(0)

                # Per-table 파티션 spec (JSONB) — None=자동 추론, []=무파티션(둘을 구분 보존)
                partition_spec = _parse_partition_spec(job['partition_spec']) if job else None

                # Collect sub-steps from iceberg_writer via callback queue
                step_queue: list[dict] = []

                def on_iceberg_step(step_name: str, msg: str, extra: dict):
                    step_queue.append({
                        "table": table, "step": step_name,
                        "message": msg, **extra
                    })

                status = await connector.sync_to_iceberg(
                    source_table=table, target_table=target,
                    sync_mode=table_mode,          # ← per-table mode
                    incremental_column=incremental_column,
                    last_value=last_value,
                    on_step=on_iceberg_step,
                    partition_spec=partition_spec,
                    key_columns=_parse_key_columns(job['key_columns']) if job else None,
                    pii_columns=_parse_key_columns(job['pii_columns']) if job else None,
                )

                # Emit all sub-steps collected during sync
                for step_data in step_queue:
                    yield sse("table_step", step_data)
                    await asyncio.sleep(0)

                rows = status.rows_processed
                total_rows += rows
                ok = status.status == SyncStatus.SUCCESS

                # Derive new watermark from metadata if incremental
                new_last_value = None
                if ok and table_mode == SyncMode.INCREMENTAL and status.metadata:
                    new_last_value = status.metadata.get("max_value")

                yield sse("table_done", {
                    "table": table, "index": i, "total": len(tables),
                    "rows": rows, "status": "success" if ok else "failed",
                    "error": status.error_message if not ok else None,
                    "message": f"{'✓' if ok else '✗'} {table} — {rows:,} rows"
                })
                await asyncio.sleep(0)

                results.append((table, target, ok, rows, status))

                # Persist job record (UPSERT by connection+table)
                run_at = datetime.utcnow()
                async with pool.acquire() as conn:
                    existing = await conn.fetchval(
                        "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 AND source_table=$2",
                        uuid.UUID(connection_id), table
                    )
                    if existing:
                        # Only advance watermark when new_last_value is set; never overwrite with NULL
                        if new_last_value is not None:
                            await conn.execute('''
                                UPDATE connector_sync_jobs
                                SET last_run_at=$1, last_run_status=$2,
                                    rows_synced=$3, last_value=$4
                                WHERE id=$5
                            ''', run_at, status.status.value, rows,
                                new_last_value, existing)
                        else:
                            await conn.execute('''
                                UPDATE connector_sync_jobs
                                SET last_run_at=$1, last_run_status=$2,
                                    rows_synced=$3
                                WHERE id=$4
                            ''', run_at, status.status.value, rows, existing)
                    else:
                        await conn.execute('''
                            INSERT INTO connector_sync_jobs
                            (id, connection_id, source_table, target_table,
                             sync_mode, last_run_at, last_run_status, rows_synced, last_value)
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ''', uuid.UUID(str(uuid.uuid4())), uuid.UUID(connection_id),
                            table, target, mode.value, run_at,
                            status.status.value, rows, new_last_value)

            # Update last_sync_at
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE connector_connections SET last_sync_at=$1 WHERE id=$2",
                    datetime.utcnow(), uuid.UUID(connection_id)
                )

            success_count = sum(1 for _, _, ok, _, _ in results if ok)
            failed_count  = len(results) - success_count
            duration_ms   = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            completed_at  = datetime.utcnow()

            # Persist session to connector_sync_history
            import json as _json
            table_details = [
                {
                    "table": tbl,
                    "target": tgt,
                    "status": "success" if ok else "failed",
                    "rows": rows,
                    "error": st.error_message if not ok else None,
                }
                for tbl, tgt, ok, rows, st in results
            ]
            history_id = str(uuid.uuid4())
            # Fetch a real job_id (most recent job for this connection) to satisfy FK
            async with pool.acquire() as conn:
                real_job = await conn.fetchval(
                    "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 ORDER BY created_at DESC LIMIT 1",
                    uuid.UUID(connection_id)
                )
            real_job_id = real_job if real_job else uuid.UUID(job_id)

            first_error = next((t["error"] for t in table_details if t.get("error")), None)
            async with pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO connector_sync_history
                    (id, job_id, started_at, completed_at, status,
                     rows_processed, rows_failed, error_message, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ''',
                    uuid.UUID(history_id),
                    real_job_id,
                    started_at,
                    completed_at,
                    "success" if failed_count == 0 else "failed",
                    total_rows,
                    failed_count,
                    first_error,
                    _json.dumps({
                        "connection_id": str(connection_id),
                        "sync_mode": mode.value,
                        "duration_ms": duration_ms,
                        "tables": table_details,
                    }, default=str)
                )

            yield sse("done", {
                "job_id": job_id,
                "history_id": history_id,
                "message": f"Sync complete — {len(tables)} tables, {total_rows:,} rows",
                "tables_synced": len(tables),
                "tables_success": success_count,
                "tables_failed": failed_count,
                "rows_processed": total_rows,
                "duration_ms": duration_ms,
            })

            # Best-effort: run data quality checks for successful tables
            from .quality import run_and_store_quality_checks
            asyncio.create_task(run_and_store_quality_checks(pool, connection_id, results))

            # Best-effort: register lineage in OpenMetadata for successful tables
            async with pool.acquire() as conn:
                conn_info = await conn.fetchrow(
                    "SELECT name, connector_type FROM connector_connections WHERE id=$1",
                    uuid.UUID(connection_id)
                )
            if conn_info:
                for tbl, tgt, ok, rows, _ in results:
                    if ok:
                        asyncio.create_task(register_lineage(
                            source_name=tbl,
                            source_schema=conn_info["connector_type"],
                            target_table=tbl,
                            target_schema="default",
                            connector_name=conn_info["name"],
                        ))

        except Exception as e:
            # Save failed history entry so errors are always recorded
            try:
                import json as _json
                error_msg = str(e)
                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                completed_at = datetime.utcnow()
                table_details = [
                    {
                        "table": tbl, "target": tgt,
                        "status": "success" if ok else "failed",
                        "rows": rows,
                        "error": st.error_message if not ok else None,
                    }
                    for tbl, tgt, ok, rows, st in results
                ]
                history_id = str(uuid.uuid4())
                async with pool.acquire() as conn:
                    real_job = await conn.fetchval(
                        "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 ORDER BY created_at DESC LIMIT 1",
                        uuid.UUID(connection_id)
                    )
                real_job_id = real_job if real_job else uuid.UUID(job_id)
                async with pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO connector_sync_history
                        (id, job_id, started_at, completed_at, status,
                         rows_processed, rows_failed, error_message, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ''',
                        uuid.UUID(history_id), real_job_id,
                        started_at, completed_at, "failed",
                        total_rows, len(results) - sum(1 for _, _, ok, _, _ in results if ok),
                        error_msg,
                        _json.dumps({
                            "connection_id": str(connection_id),
                            "sync_mode": mode.value if 'mode' in dir() else "full",
                            "duration_ms": duration_ms,
                            "tables": table_details,
                        }, default=str)
                    )
            except Exception:
                pass  # Don't let history save failure mask the original error
            yield sse("error", {"message": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _persist_sync_session(pool, connection_id: str, job_id: str,
                                started_at: datetime, results: list, sync_mode) -> str:
    """Record a connector_sync_history session row and fire best-effort data
    quality checks + OpenMetadata lineage registration.

    Shared by /sync and /sync/stream so a sync triggered from the connectors
    list (lean /sync) records history/quality/lineage identically to the detail
    view (/sync/stream). `results` is a list of (table, target, ok, rows, status).
    """
    import json as _json
    completed_at = datetime.utcnow()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    success_count = sum(1 for _, _, ok, _, _ in results if ok)
    failed_count = len(results) - success_count
    total_rows = sum(rows for _, _, _, rows, _ in results)
    mode_val = sync_mode.value if hasattr(sync_mode, "value") else str(sync_mode)
    table_details = [
        {"table": tbl, "target": tgt,
         "status": "success" if ok else "failed",
         "rows": rows,
         "error": st.error_message if not ok else None}
        for tbl, tgt, ok, rows, st in results
    ]
    first_error = next((t["error"] for t in table_details if t.get("error")), None)
    history_id = str(uuid.uuid4())
    # job_id FK must reference a real connector_sync_jobs row
    async with pool.acquire() as conn:
        real_job = await conn.fetchval(
            "SELECT id FROM connector_sync_jobs WHERE connection_id=$1 ORDER BY created_at DESC LIMIT 1",
            uuid.UUID(connection_id)
        )
    real_job_id = real_job if real_job else uuid.UUID(job_id)
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO connector_sync_history
            (id, job_id, started_at, completed_at, status,
             rows_processed, rows_failed, error_message, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ''',
            uuid.UUID(history_id), real_job_id, started_at, completed_at,
            "success" if failed_count == 0 else "failed",
            total_rows, failed_count, first_error,
            _json.dumps({
                "connection_id": str(connection_id),
                "sync_mode": mode_val,
                "duration_ms": duration_ms,
                "tables": table_details,
            }, default=str)
        )

    # Best-effort: data quality checks for successful tables
    try:
        from .quality import run_and_store_quality_checks
        asyncio.create_task(run_and_store_quality_checks(pool, connection_id, results))
    except Exception:
        pass

    # Best-effort: reflect each synced table in OpenMetadata (register the table
    # entity, then the lineage edge). Done per table in one task so the lineage
    # target exists before the edge is created.
    try:
        async with pool.acquire() as conn:
            conn_info = await conn.fetchrow(
                "SELECT name, connector_type FROM connector_connections WHERE id=$1",
                uuid.UUID(connection_id)
            )
        if conn_info:
            async def _reflect_in_om(tbl):
                # 1) target iceberg table entity (reproducible OM ingestion)
                columns = await register_om_table("default", tbl)
                # 2) source table entity (so lineage has a valid 'from' endpoint)
                source_fqn = await register_om_source_table(
                    conn_info["connector_type"], conn_info["name"], "public", tbl, columns)
                # 3) lineage edge (needs both entities to exist)
                if columns and source_fqn:
                    await register_lineage(
                        source_fqn=source_fqn,
                        target_fqn=f"{OM_DATABASE_FQN}.default.{tbl}",
                        connector_name=conn_info["name"],
                    )
            for tbl, tgt, ok, rows, _ in results:
                if ok:
                    asyncio.create_task(_reflect_in_om(tbl))
    except Exception:
        pass

    return history_id


@router.post("/connectors/{connection_id}/sync")
async def trigger_sync(connection_id: str, request: Optional[SyncRequest] = None):
    """Trigger a data sync job"""
    if request is None:
        request = SyncRequest()
    try:
        connector = await _get_connector_instance(connection_id)

        # When no source_table specified, sync all available tables
        if not request.source_table:
            tables = await connector.get_tables()
            if not tables:
                return {"job_id": None, "status": "success", "rows_processed": 0, "message": "No tables to sync"}
            total_rows = 0
            last_status = None
            results = []
            started_at = datetime.utcnow()
            job_id = None
            pool = await get_db_pool()
            for table in tables:
                target = f"datapond.default.{table}"
                status = await connector.sync_to_iceberg(
                    source_table=table,
                    target_table=target,
                    sync_mode=request.sync_mode,
                    incremental_column=request.incremental_column,
                    partition_spec=await _load_partition_spec(pool, connection_id, table),
                    key_columns=await _load_key_columns(pool, connection_id, table),
                    pii_columns=await _load_pii_columns(pool, connection_id, table),
                )
                total_rows += status.rows_processed
                last_status = status
                results.append((table, target, status.status == SyncStatus.SUCCESS,
                                status.rows_processed, status))
                job_id = str(uuid.uuid4())
                async with pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO connector_sync_jobs
                        (id, connection_id, source_table, target_table, sync_mode, last_run_at, last_run_status, rows_synced)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ''',
                        uuid.UUID(job_id),
                        uuid.UUID(connection_id),
                        table,
                        target,
                        request.sync_mode.value,
                        datetime.utcnow(),
                        status.status.value,
                        status.rows_processed
                    )
            # Update last_sync_at on connection
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE connector_connections SET last_sync_at = $1 WHERE id = $2",
                    datetime.utcnow(), uuid.UUID(connection_id)
                )
            # Record session history + best-effort quality/lineage (same as /sync/stream)
            try:
                await _persist_sync_session(pool, connection_id, job_id, started_at,
                                            results, request.sync_mode)
            except Exception:
                pass  # never let bookkeeping fail the sync
            return {
                "job_id": job_id,
                "status": last_status.status.value,
                "rows_processed": total_rows,
                "message": f"Synced {len(tables)} tables ({total_rows} rows)"
            }

        # Sync a specific table
        source_table = request.source_table
        target_table = request.target_table or f"datapond.default.{source_table}"
        started_at = datetime.utcnow()
        pool = await get_db_pool()
        status = await connector.sync_to_iceberg(
            source_table=source_table,
            target_table=target_table,
            sync_mode=request.sync_mode,
            incremental_column=request.incremental_column,
            partition_spec=await _load_partition_spec(pool, connection_id, source_table),
            key_columns=await _load_key_columns(pool, connection_id, source_table),
            pii_columns=await _load_pii_columns(pool, connection_id, source_table),
        )
        job_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO connector_sync_jobs
                (id, connection_id, source_table, target_table, sync_mode, last_run_at, last_run_status, rows_synced)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ''',
                uuid.UUID(job_id),
                uuid.UUID(connection_id),
                source_table,
                target_table,
                request.sync_mode.value,
                datetime.utcnow(),
                status.status.value,
                status.rows_processed
            )
        # Update last_sync_at on connection
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE connector_connections SET last_sync_at = $1 WHERE id = $2",
                datetime.utcnow(), uuid.UUID(connection_id)
            )
        # Record session history + best-effort quality/lineage (same as /sync/stream)
        try:
            await _persist_sync_session(
                pool, connection_id, job_id, started_at,
                [(source_table, target_table, status.status == SyncStatus.SUCCESS,
                  status.rows_processed, status)],
                request.sync_mode)
        except Exception:
            pass
        return {
            "job_id": job_id,
            "status": status.status.value,
            "rows_processed": status.rows_processed,
            "message": "Sync completed successfully" if status.status == SyncStatus.SUCCESS else status.error_message
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.get("/connectors/{connection_id}/status")
async def get_sync_status(connection_id: str):
    """Get status of sync jobs for a connection"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT id, source_table, target_table, sync_mode,
                       last_run_at, last_run_status, rows_synced
                FROM connector_sync_jobs
                WHERE connection_id = $1
                ORDER BY last_run_at DESC
                LIMIT 10
            ''', uuid.UUID(connection_id))

        jobs = []
        for row in rows:
            jobs.append({
                "job_id": str(row['id']),
                "source_table": row['source_table'],
                "target_table": row['target_table'],
                "sync_mode": row['sync_mode'],
                "last_run_at": row['last_run_at'].isoformat() + "Z" if row['last_run_at'] else None,
                "status": row['last_run_status'],
                "rows_synced": row['rows_synced']
            })

        return {"jobs": jobs}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connection_id}/history")
async def get_sync_history(connection_id: str, limit: int = 20):
    """Get sync session history — one row per Sync Now click."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT id, started_at, completed_at, status,
                       rows_processed, rows_failed, error_message, metadata
                FROM connector_sync_history
                WHERE metadata->>'connection_id' = $1
                ORDER BY started_at DESC
                LIMIT $2
            ''', connection_id, limit)

        sessions = []
        for row in rows:
            import json as _json
            meta = row['metadata'] or {}
            if isinstance(meta, str):
                meta = _json.loads(meta)
            sessions.append({
                "id": str(row['id']),
                "started_at": row['started_at'].isoformat() + "Z" if row['started_at'] else None,
                "completed_at": row['completed_at'].isoformat() + "Z" if row['completed_at'] else None,
                "status": row['status'],
                "rows_processed": row['rows_processed'] or 0,
                "rows_failed": row['rows_failed'] or 0,
                "error_message": row['error_message'],
                "tables": meta.get("tables", []),
                "duration_ms": meta.get("duration_ms"),
                "sync_mode": meta.get("sync_mode", "full"),
            })
        return sessions

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Helper functions

def _create_connector(connector_type: ConnectorType, config: Dict[str, Any]):  # noqa: C901
    """Create connector instance from type and config"""
    # ConnectorConfig base requires 'name' — inject a default if not provided
    if 'name' not in config:
        config = {**config, 'name': connector_type.value}

    try:
        if connector_type == ConnectorType.POSTGRESQL:
            return PostgreSQLConnector(DatabaseConfig(connector_type=connector_type, **config))

        elif connector_type == ConnectorType.MYSQL:
            return MySQLConnector(DatabaseConfig(connector_type=connector_type, **config))

        elif connector_type == ConnectorType.S3:
            return S3Connector(StorageConfig(connector_type=connector_type, **config))

        elif connector_type == ConnectorType.DATABASE_URL:
            from ..connectors.database import DatabaseURLConfig, DatabaseURLConnector
            return DatabaseURLConnector(DatabaseURLConfig(connector_type=connector_type, **config))

        elif connector_type == ConnectorType.REST_API:
            from ..connectors.rest import RestConfig, RestConnector
            return RestConnector(RestConfig(connector_type=connector_type, **config))

        elif connector_type == ConnectorType.CUSTOM:
            from ..connectors.custom import CustomConfig, CustomConnector
            return CustomConnector(CustomConfig(connector_type=connector_type, **config))

        else:
            raise ValueError(f"Unsupported connector type: {connector_type}")

    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid connector config: {e.error_count()} field(s) missing or invalid")


async def _get_connector_instance(connection_id: str):
    """Get connector instance from saved connection"""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT name, connector_type, config_encrypted
            FROM connector_connections
            WHERE id = $1
        ''', uuid.UUID(connection_id))


    if not row:
        raise HTTPException(status_code=404, detail="Connection not found")

    config = vault.decrypt_credentials(row['config_encrypted'])

    # ConnectorConfig base requires 'name' — inject from DB row if missing
    if 'name' not in config:
        config['name'] = row['name']

    connector_type = ConnectorType(row['connector_type'])
    return _create_connector(connector_type, config)


@router.get("/connectors/{connection_id}/quality")
async def get_quality_checks(connection_id: str, limit: int = 20):
    """Get latest data quality check results for a connection."""
    pool = await get_db_pool()
    from .quality import ensure_quality_table
    await ensure_quality_table(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT source_table, checked_at, rows_current, rows_previous,
                      row_change_pct, row_change_status, null_checks,
                      overall_status, warnings
               FROM connector_quality_checks
               WHERE connection_id=$1
               ORDER BY checked_at DESC LIMIT $2""",
            uuid.UUID(connection_id), limit
        )
    import json as _json
    return {
        "checks": [
            {
                "source_table": r["source_table"],
                "checked_at": r["checked_at"].isoformat() + "Z",
                "rows_current": r["rows_current"],
                "rows_previous": r["rows_previous"],
                "row_change_pct": r["row_change_pct"],
                "row_change_status": r["row_change_status"],
                "null_checks": _json.loads(r["null_checks"]) if r["null_checks"] else {},
                "overall_status": r["overall_status"],
                "warnings": _json.loads(r["warnings"]) if r["warnings"] else [],
            }
            for r in rows
        ]
    }
