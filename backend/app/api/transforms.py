"""
ELT Transform API — SQL-based Medallion transformations via Trino CTAS + Airflow DAG.

Flow: user writes SQL → backend generates Airflow DAG (TrinoCTASOperator pattern)
      → deploys to Airflow → Trino executes CTAS into Iceberg target namespace
"""
import os
import re
import uuid
import httpx
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.connection import get_db, engine, Base
from app.models.transform import SavedTransform

router = APIRouter()

Base.metadata.create_all(bind=engine, tables=[SavedTransform.__table__], checkfirst=True)

AIRFLOW_API  = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver.datapond.svc.cluster.local:8080/airflow/api/v1")
AIRFLOW_AUTH = (os.getenv("AIRFLOW_USERNAME", "airflow"), os.getenv("AIRFLOW_PASSWORD", "airflow"))
DAGS_PATH    = Path(os.getenv("AIRFLOW_DAGS_PATH", "/opt/airflow/dags"))

NAMESPACES = ["raw", "refined", "serving"]

TRINO_HOST = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT = int(os.getenv("TRINO_SERVICE_PORT", "8080"))


async def _ensure_trino_connection() -> None:
    """Create or update trino_default Airflow connection to point at our Trino cluster."""
    payload = {
        "connection_id": "trino_default",
        "conn_type": "trino",
        "host": TRINO_HOST,
        "port": TRINO_PORT,
        "login": "datapond",
        "schema": "iceberg",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        # Try PATCH first, fall back to POST
        resp = await client.patch(
            f"{AIRFLOW_API}/connections/trino_default",
            auth=AIRFLOW_AUTH, json=payload,
        )
        if resp.status_code == 404:
            await client.post(
                f"{AIRFLOW_API}/connections",
                auth=AIRFLOW_AUTH, json=payload,
            )


class TransformCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    source_namespace: str       # raw | refined
    target_namespace: str       # refined | serving
    target_table: str
    sql: str                    # SELECT … (no CREATE TABLE prefix)
    schedule: Optional[str] = None   # cron or None
    overwrite: bool = True


class TransformUpdateRequest(BaseModel):
    description: Optional[str] = None
    source_namespace: Optional[str] = None
    target_namespace: Optional[str] = None
    target_table: Optional[str] = None
    sql: Optional[str] = None
    schedule: Optional[str] = None


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower())


def _generate_dag(transform: "SavedTransform") -> str:
    dag_id    = f"transform_{_safe_id(transform.name)}"
    target_ns = transform.target_namespace
    target_tbl = _safe_id(transform.target_table)
    fqtn       = f"iceberg.{target_ns}.{target_tbl}"
    schedule   = f'"{transform.schedule}"' if transform.schedule else "None"
    sql_escaped = transform.sql.replace('"""', '\\"\\"\\"')

    return f'''"""
Auto-generated ELT transform DAG: {transform.name}
{transform.description or ""}
Source: iceberg.{transform.source_namespace}  →  Target: {fqtn}
Generated: {datetime.utcnow().isoformat()}
"""
from airflow import DAG
from airflow.providers.trino.operators.trino import TrinoOperator
from datetime import datetime, timedelta

default_args = {{
    "owner": "datapond",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}}

with DAG(
    dag_id="{dag_id}",
    description="{transform.description or transform.name}",
    schedule_interval={schedule},
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["transform", "{target_ns}", "datapond"],
    default_args=default_args,
) as dag:

    create_schema = TrinoOperator(
        task_id="create_schema",
        trino_conn_id="trino_default",
        sql="CREATE SCHEMA IF NOT EXISTS iceberg.{target_ns} WITH (location = 's3a://iceberg/{target_ns}')",
    )

    drop_table = TrinoOperator(
        task_id="drop_table",
        trino_conn_id="trino_default",
        sql="DROP TABLE IF EXISTS {fqtn}",
    )

    create_table = TrinoOperator(
        task_id="create_table",
        trino_conn_id="trino_default",
        sql="""CREATE TABLE {fqtn}
WITH (format = 'PARQUET', location = 's3a://iceberg/{target_ns}/{target_tbl}')
AS
{sql_escaped}""",
    )

    create_schema >> drop_table >> create_table
'''


async def _deploy_dag(dag_id: str, dag_code: str) -> bool:
    DAGS_PATH.mkdir(parents=True, exist_ok=True)
    (DAGS_PATH / f"{dag_id}.py").write_text(dag_code, encoding="utf-8")
    try:
        await _ensure_trino_connection()
        async with httpx.AsyncClient(timeout=10) as client:
            await client.patch(
                f"{AIRFLOW_API}/dags/{dag_id}",
                auth=AIRFLOW_AUTH,
                json={"is_paused": False},
            )
    except Exception:
        pass
    return True


@router.post("/transforms")
async def create_transform(req: TransformCreateRequest, db: Session = Depends(get_db)):
    if req.source_namespace not in NAMESPACES or req.target_namespace not in NAMESPACES:
        raise HTTPException(400, f"namespace must be one of {NAMESPACES}")
    if req.source_namespace == req.target_namespace:
        raise HTTPException(400, "source and target namespace must differ")

    existing = db.query(SavedTransform).filter(SavedTransform.name == req.name).first()
    if existing and not req.overwrite:
        raise HTTPException(409, f"Transform '{req.name}' already exists")

    if existing:
        existing.description      = req.description
        existing.source_namespace = req.source_namespace
        existing.target_namespace = req.target_namespace
        existing.target_table     = req.target_table
        existing.sql              = req.sql
        existing.schedule         = req.schedule
        existing.updated_at       = datetime.utcnow()
        row = existing
    else:
        row = SavedTransform(
            id=uuid.uuid4(),
            name=req.name,
            description=req.description,
            source_namespace=req.source_namespace,
            target_namespace=req.target_namespace,
            target_table=req.target_table,
            sql=req.sql,
            schedule=req.schedule,
            status="draft",
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    dag_id   = f"transform_{_safe_id(row.name)}"
    dag_code = _generate_dag(row)
    await _deploy_dag(dag_id, dag_code)

    row.status = "deployed"
    row.dag_id = dag_id
    db.commit()

    return {
        "id": str(row.id),
        "name": row.name,
        "dag_id": dag_id,
        "status": "deployed",
        "message": "Transform deployed. Airflow will pick it up within 30 seconds.",
    }


@router.get("/transforms")
async def list_transforms(db: Session = Depends(get_db)):
    rows = db.query(SavedTransform).order_by(SavedTransform.updated_at.desc()).all()
    return {
        "transforms": [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "source_namespace": r.source_namespace,
                "target_namespace": r.target_namespace,
                "target_table": r.target_table,
                "schedule": r.schedule,
                "status": r.status,
                "dag_id": r.dag_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/transforms/{transform_id}")
async def get_transform(transform_id: str, db: Session = Depends(get_db)):
    row = db.query(SavedTransform).filter(SavedTransform.id == uuid.UUID(transform_id)).first()
    if not row:
        raise HTTPException(404, "Transform not found")
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "source_namespace": row.source_namespace,
        "target_namespace": row.target_namespace,
        "target_table": row.target_table,
        "sql": row.sql,
        "schedule": row.schedule,
        "status": row.status,
        "dag_id": row.dag_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/transforms/{transform_id}/trigger")
async def trigger_transform(transform_id: str, db: Session = Depends(get_db)):
    row = db.query(SavedTransform).filter(SavedTransform.id == uuid.UUID(transform_id)).first()
    if not row or not row.dag_id:
        raise HTTPException(404, "Transform not found or not deployed")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{AIRFLOW_API}/dags/{row.dag_id}/dagRuns",
                auth=AIRFLOW_AUTH,
                json={"conf": {}},
            )
        if resp.status_code not in (200, 201):
            raise HTTPException(502, f"Airflow trigger failed: {resp.text}")
        return {"success": True, "dag_id": row.dag_id, "run": resp.json()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


@router.delete("/transforms/{transform_id}")
async def delete_transform(transform_id: str, db: Session = Depends(get_db)):
    row = db.query(SavedTransform).filter(SavedTransform.id == uuid.UUID(transform_id)).first()
    if not row:
        raise HTTPException(404, "Transform not found")

    if row.dag_id:
        dag_file = DAGS_PATH / f"{row.dag_id}.py"
        dag_file.unlink(missing_ok=True)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.patch(f"{AIRFLOW_API}/dags/{row.dag_id}", auth=AIRFLOW_AUTH, json={"is_paused": True})
                await client.delete(f"{AIRFLOW_API}/dags/{row.dag_id}", auth=AIRFLOW_AUTH)
        except Exception:
            pass

    db.delete(row)
    db.commit()
    return {"success": True}
