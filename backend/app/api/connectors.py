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
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "datapond"),
            user=os.getenv("POSTGRES_USER", "datapond"),
            password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
            min_size=2,
            max_size=10,
        )
    return _db_pool


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
    """
    try:
        # Create connector instance based on type
        connector = _create_connector(request.connector_type, request.config)

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
            port=int(os.getenv("POSTGRES_PORT", "5432")),
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
            port=int(os.getenv("POSTGRES_PORT", "5432")),
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
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
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


@router.post("/connectors/create", response_model=ConnectionResponse)
async def create_connection(request: ConnectionCreateRequest):
    """
    Create and save a new connector connection.

    Credentials are encrypted before storage.
    """
    try:
        # Generate connection ID
        connection_id = str(uuid.uuid4())

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
                ConnectionStatus.ACTIVE.value,
                datetime.utcnow(),
                datetime.utcnow()
            )



        return ConnectionResponse(
            id=connection_id,
            name=request.name,
            connector_type=request.connector_type.value,
            status=ConnectionStatus.ACTIVE.value,
            created_at=datetime.utcnow()
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create connection: {str(e)}")


@router.get("/connectors/connections", response_model=List[ConnectionResponse])
async def list_connections():
    """
    List all saved connections.

    Does not include credentials in response.
    """
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT id, name, connector_type, status, created_at, last_sync_at
                FROM connector_connections
                ORDER BY created_at DESC
            ''')



        connections = []
        for row in rows:
            connections.append(ConnectionResponse(
                id=str(row['id']),
                name=row['name'],
                connector_type=row['connector_type'],
                status=row['status'],
                created_at=row['created_at'],
                last_sync_at=row['last_sync_at']
            ))

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
                SELECT id, name, connector_type, status, created_at, last_sync_at
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
            "last_sync_at": row['last_sync_at'].isoformat() + "Z" if row['last_sync_at'] else None
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
            existing = vault.decrypt_credentials(row['config_encrypted'])
            merged = {**existing}
            for k, v in request.config.items():
                if v not in ("••••••••", "") and k not in ("name", "connector_type"):
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
    """Set or remove a sync schedule (creates/deletes Airflow DAG file)."""
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
            # Write DAG file
            dag_code = _generate_sync_dag(connection_id, connection_name, request.schedule)
            with open(dag_path, "w") as f:
                f.write(dag_code)

            # Save schedule to DB
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE connector_sync_jobs SET schedule=$1 WHERE connection_id=$2",
                    request.schedule, uuid.UUID(connection_id)
                )

            return {
                "message": f"Schedule '{request.schedule}' set for '{connection_name}'",
                "dag_id": f"datapond_sync_{safe_name}",
                "dag_path": dag_path,
            }
        else:
            # Remove DAG file
            import pathlib
            p = pathlib.Path(dag_path)
            if p.exists():
                p.unlink()

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE connector_sync_jobs SET schedule=NULL WHERE connection_id=$1",
                    uuid.UUID(connection_id)
                )

            return {"message": f"Schedule removed for '{connection_name}'"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connectors/{connection_id}/schedule")
async def get_schedule(connection_id: str):
    """Get current schedule for a connection."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT schedule FROM connector_sync_jobs WHERE connection_id=$1 LIMIT 1",
                uuid.UUID(connection_id)
            )
        schedule = row['schedule'] if row else None
        safe_conn = connection_id.replace("-", "_")

        # Check if DAG file exists
        import pathlib, glob
        dag_files = glob.glob(f"/opt/airflow/dags/datapond_sync_*.py")
        dag_active = any(connection_id in open(f).read() for f in dag_files) if dag_files else False

        return {"schedule": schedule, "dag_active": dag_active}
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
                "SELECT source_table, enabled, sync_mode, incremental_column FROM connector_sync_jobs WHERE connection_id=$1",
                uuid.UUID(connection_id)
            )
        config_map = {r['source_table']: r for r in rows}

        return {
            "tables": [
                {
                    "name": t,
                    "enabled": config_map[t]['enabled'] if t in config_map else True,
                    "sync_mode": config_map[t]['sync_mode'] if t in config_map else "full",
                    "incremental_column": config_map[t]['incremental_column'] if t in config_map else None,
                }
                for t in tables
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tables: {str(e)}")


@router.patch("/connectors/{connection_id}/tables/{table_name}/enabled")
async def set_table_enabled(connection_id: str, table_name: str, body: dict):
    """Enable/disable a table and optionally set incremental_column."""
    try:
        enabled             = bool(body.get("enabled", True))
        incremental_column  = body.get("incremental_column")   # None = don't change
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


@router.patch("/connectors/{connection_id}/sync-mode")
async def set_connection_sync_mode(connection_id: str, body: dict):
    """Set sync_mode for all tables of a connection."""
    try:
        mode = body.get("sync_mode", "full")
        if mode not in ("full", "incremental", "cdc", "snapshot"):
            raise HTTPException(status_code=400, detail=f"Invalid sync_mode: {mode}")
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE connector_sync_jobs SET sync_mode=$1 WHERE connection_id=$2",
                mode, uuid.UUID(connection_id)
            )
        return {"sync_mode": mode}
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

            # Filter to enabled tables only
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                enabled_rows = await conn.fetch(
                    "SELECT source_table, enabled FROM connector_sync_jobs WHERE connection_id=$1",
                    uuid.UUID(connection_id)
                )
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

                # Load watermark for incremental mode
                last_value = None
                incremental_column = None
                if mode == SyncMode.INCREMENTAL:
                    async with pool.acquire() as conn:
                        wm_row = await conn.fetchrow('''
                            SELECT incremental_column, last_value
                            FROM connector_sync_jobs
                            WHERE connection_id=$1 AND source_table=$2
                              AND last_run_status='success'
                            ORDER BY last_run_at DESC LIMIT 1
                        ''', uuid.UUID(connection_id), table)
                    if wm_row:
                        incremental_column = wm_row['incremental_column']
                        last_value = wm_row['last_value']

                yield sse("table_start", {
                    "table": table, "index": i, "total": len(tables),
                    "message": f"Syncing {table}… ({i+1}/{len(tables)})"
                    + (f" [incremental since {last_value}]" if last_value else ""),
                })
                await asyncio.sleep(0)

                # Collect sub-steps from iceberg_writer via callback queue
                step_queue: list[dict] = []

                def on_iceberg_step(step_name: str, msg: str, extra: dict):
                    step_queue.append({
                        "table": table, "step": step_name,
                        "message": msg, **extra
                    })

                status = await connector.sync_to_iceberg(
                    source_table=table, target_table=target,
                    sync_mode=mode,
                    incremental_column=incremental_column,
                    last_value=last_value,
                    on_step=on_iceberg_step,
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
                if ok and mode == SyncMode.INCREMENTAL and status.metadata:
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
                        await conn.execute('''
                            UPDATE connector_sync_jobs
                            SET sync_mode=$1, last_run_at=$2, last_run_status=$3,
                                rows_synced=$4, last_value=$5
                            WHERE id=$6
                        ''', mode.value, run_at, status.status.value, rows,
                            new_last_value, existing)
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

            async with pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO connector_sync_history
                    (id, job_id, started_at, completed_at, status,
                     rows_processed, rows_failed, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ''',
                    uuid.UUID(history_id),
                    real_job_id,
                    started_at,
                    completed_at,
                    "success" if failed_count == 0 else "failed",
                    total_rows,
                    failed_count,
                    _json.dumps({
                        "connection_id": str(connection_id),
                        "sync_mode": mode.value,
                        "duration_ms": duration_ms,
                        "tables": table_details,
                    }, default=str)  # default=str handles UUID/datetime
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

        except Exception as e:
            yield sse("error", {"message": str(e)})

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
            pool = await get_db_pool()
            for table in tables:
                target = f"datapond.default.{table}"
                status = await connector.sync_to_iceberg(
                    source_table=table,
                    target_table=target,
                    sync_mode=request.sync_mode,
                    incremental_column=request.incremental_column
                )
                total_rows += status.rows_processed
                last_status = status
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
            return {
                "job_id": job_id,
                "status": last_status.status.value,
                "rows_processed": total_rows,
                "message": f"Synced {len(tables)} tables ({total_rows} rows)"
            }

        # Sync a specific table
        source_table = request.source_table
        target_table = request.target_table or f"datapond.default.{source_table}"
        status = await connector.sync_to_iceberg(
            source_table=source_table,
            target_table=target_table,
            sync_mode=request.sync_mode,
            incremental_column=request.incremental_column
        )
        job_id = str(uuid.uuid4())
        pool = await get_db_pool()
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
