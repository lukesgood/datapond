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
            "created_at": row['created_at'].isoformat(),
            "last_sync_at": row['last_sync_at'].isoformat() if row['last_sync_at'] else None
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
    """List tables available in connection"""
    try:
        # Get connection from database
        connector = await _get_connector_instance(connection_id)

        # List tables
        tables = await connector.get_tables()

        return {"tables": tables}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tables: {str(e)}")


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
            yield sse("start", {"job_id": job_id, "message": "Initializing sync…", "ts": started_at.isoformat()})
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
            tables = await connector.get_tables()
            if not tables:
                yield sse("done", {"message": "No tables found", "rows_processed": 0, "tables": 0})
                return
            yield sse("step", {"step": "discover", "message": f"Found {len(tables)} tables", "status": "done", "tables": tables})
            await asyncio.sleep(0)

            # Sync each table
            pool = await get_db_pool()
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
                        "connection_id": connection_id,
                        "sync_mode": mode.value,
                        "duration_ms": duration_ms,
                        "tables": table_details,
                    })
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
                "last_run_at": row['last_run_at'].isoformat() if row['last_run_at'] else None,
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
                "started_at": row['started_at'].isoformat() if row['started_at'] else None,
                "completed_at": row['completed_at'].isoformat() if row['completed_at'] else None,
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
