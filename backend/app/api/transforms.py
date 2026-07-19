"""
ELT Transform API — SQL-based Medallion transformations via Trino CTAS + Airflow DAG.

Flow: user writes SQL → backend generates Airflow DAG (TrinoCTASOperator pattern)
      → deploys to Airflow → Trino executes CTAS into Iceberg target namespace
"""
import os
import re
import uuid
import base64
import asyncio
import httpx
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.connection import get_db, engine, Base
from app.models.transform import SavedTransform
from app.api.trino_util import trino_conn
from app.runtime import component_secret

router = APIRouter()

Base.metadata.create_all(bind=engine, tables=[SavedTransform.__table__], checkfirst=True)

AIRFLOW_API  = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver.datapond.svc.cluster.local:8080/airflow/api/v1")
DAGS_PATH    = Path(os.getenv("AIRFLOW_DAGS_PATH", "/opt/airflow/dags"))


def _airflow_auth() -> tuple:
    """Resolved per-request: fail-closed in prod when Airflow creds are missing."""
    return (
        os.getenv("AIRFLOW_USERNAME", "airflow"),
        component_secret("AIRFLOW_PASSWORD", "airflow", component="airflow"),
    )

NAMESPACES = ["raw", "refined", "serving"]

TRINO_HOST = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT = int(os.getenv("TRINO_SERVICE_PORT", "8080"))


def _airflow_response_detail(response: httpx.Response) -> str:
    detail = response.text.strip()
    return detail[:1000] if detail else f"HTTP {response.status_code}"


async def _ensure_trino_connection() -> None:
    """Create or update the Airflow Trino connection, failing closed on errors."""
    payload = {
        "connection_id": "trino_default",
        "conn_type": "trino",
        "host": TRINO_HOST,
        "port": TRINO_PORT,
        "login": "datapond",
        "schema": "iceberg",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{AIRFLOW_API}/connections/trino_default",
                auth=_airflow_auth(), json=payload,
            )
            if response.status_code == 404:
                response = await client.post(
                    f"{AIRFLOW_API}/connections",
                    auth=_airflow_auth(), json=payload,
                )
            if response.status_code not in (200, 201, 204):
                raise HTTPException(
                    502,
                    f"Airflow Trino connection setup failed: {_airflow_response_detail(response)}",
                )
    except HTTPException:
        raise
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(503, f"Airflow is unavailable while configuring Trino: {exc}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Airflow connection request failed: {exc}") from exc


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


_SQL_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def _validate_transform_sql(sql: str) -> None:
    """T3: SELECT/WITH 단일 문만 허용 — DAG로 정기 실행되므로 DDL/DML 차단."""
    stripped = _SQL_COMMENT_RE.sub(" ", sql).strip()
    if not stripped:
        raise HTTPException(400, "SQL is empty")
    first = stripped.split(None, 1)[0].upper()
    if first not in ("SELECT", "WITH"):
        raise HTTPException(400, "Transform SQL must start with SELECT or WITH — it defines the target table contents (no DDL/DML)")
    if ";" in stripped.rstrip().rstrip(";"):
        raise HTTPException(400, "Multiple SQL statements are not allowed")


async def _explain_check(sql: str) -> None:
    """T2: 배포 전 Trino EXPLAIN으로 문법/테이블 존재 검증 — 실패를 즉시 400으로."""
    def run():
        cur = trino_conn(timeout=20).cursor()
        cur.execute(f"EXPLAIN {sql.rstrip().rstrip(';')}")
        cur.fetchall()
    try:
        await asyncio.to_thread(run)
    except Exception as e:
        raise HTTPException(400, f"SQL validation failed: {e}")


def _generate_dag(transform: "SavedTransform") -> str:
    dag_id    = f"transform_{_safe_id(transform.name)}"
    target_ns = transform.target_namespace
    target_tbl = _safe_id(transform.target_table)
    fqtn       = f"iceberg.{target_ns}.{target_tbl}"
    schedule   = f'"{transform.schedule}"' if transform.schedule else "None"
    # T1: CREATE OR REPLACE TABLE … AS — 원자적 교체(Trino 481 Iceberg 검증).
    #     실패 시 기존 테이블이 보존되고, drop~create 사이 조회 공백도 없다.
    # T8: SQL은 base64로 삽입 — 따옴표/백슬래시가 생성된 DAG 소스를 깨지 못함.
    # description/name이 따옴표·개행을 포함해도 생성된 Python 소스가 깨지지 않도록 정제
    desc_safe = re.sub(r'["\\\n\r]+', " ", (transform.description or transform.name)).strip()
    replace_sql = (
        f"CREATE OR REPLACE TABLE {fqtn}\n"
        f"WITH (format = 'PARQUET')\n"
        f"AS\n{transform.sql.rstrip().rstrip(';')}"
    )
    sql_b64 = base64.b64encode(replace_sql.encode("utf-8")).decode("ascii")

    return f'''"""
Auto-generated ELT transform DAG: {transform.name}
{desc_safe}
Source: iceberg.{transform.source_namespace}  →  Target: {fqtn}
Generated: {datetime.utcnow().isoformat()}

stock Airflow 이미지에는 trino provider가 없으므로 Trino REST API(/v1/statement)를
requests로 직접 호출한다(에어갭 환경에서 런타임 pip 설치 회피).
"""
import base64
import time
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

TRINO_URL = "http://{TRINO_HOST}:{TRINO_PORT}"


def _trino_exec(sql):
    """Trino REST 프로토콜: POST 후 nextUri를 끝까지 폴링, 에러 시 예외."""
    headers = {{"X-Trino-User": "datapond", "X-Trino-Catalog": "iceberg"}}
    resp = requests.post(TRINO_URL + "/v1/statement", data=sql.encode("utf-8"),
                         headers=headers, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    while True:
        err = payload.get("error")
        if err:
            raise RuntimeError(err.get("message", "trino error"))
        nxt = payload.get("nextUri")
        if not nxt:
            break
        time.sleep(0.2)
        r = requests.get(nxt, headers=headers, timeout=120)
        r.raise_for_status()
        payload = r.json()


# 타깃 스키마(raw/refined/serving)는 backend startup이 생성해 둔다 — DAG에서는
# CREATE SCHEMA를 시도하지 않는다(Trino ACL상 일반 유저의 스키마 생성은 차단됨).
# 원자적 교체 — DROP 단계 없음(실패 시 기존 테이블 보존). SQL은 base64(소스 손상 방지).
REPLACE_TABLE_SQL = base64.b64decode("{sql_b64}").decode("utf-8")


def run_sql(sql):
    _trino_exec(sql)


default_args = {{
    "owner": "datapond",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}}

with DAG(
    dag_id="{dag_id}",
    description="{desc_safe}",
    schedule_interval={schedule},
    start_date=datetime(2024, 1, 1),
    catchup=False,
    is_paused_upon_creation=False,
    tags=["transform", "{target_ns}", "datapond"],
    default_args=default_args,
) as dag:

    replace_table = PythonOperator(
        task_id="replace_table", python_callable=run_sql, op_args=[REPLACE_TABLE_SQL],
    )
'''


async def _deploy_dag(dag_id: str, dag_code: str) -> bool:
    """Install and activate a DAG, restoring the prior file on remote failure."""
    dag_file = DAGS_PATH / f"{dag_id}.py"
    temporary = DAGS_PATH / f".{dag_id}.{uuid.uuid4().hex}.tmp"
    previous = dag_file.read_bytes() if dag_file.exists() else None
    try:
        DAGS_PATH.mkdir(parents=True, exist_ok=True)
        temporary.write_text(dag_code, encoding="utf-8")
        temporary.replace(dag_file)
        await _ensure_trino_connection()

        last_response = None
        async with httpx.AsyncClient(timeout=10) as client:
            for attempt in range(5):
                last_response = await client.patch(
                    f"{AIRFLOW_API}/dags/{dag_id}",
                    auth=_airflow_auth(),
                    json={"is_paused": False},
                )
                if last_response.status_code in (200, 204):
                    return True
                if last_response.status_code != 404 or attempt == 4:
                    break
                await asyncio.sleep(0.5)
        assert last_response is not None
        raise HTTPException(
            502,
            f"Airflow failed to activate DAG '{dag_id}': {_airflow_response_detail(last_response)}",
        )
    except HTTPException:
        if previous is None:
            dag_file.unlink(missing_ok=True)
        else:
            dag_file.write_bytes(previous)
        raise
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        if previous is None:
            dag_file.unlink(missing_ok=True)
        else:
            dag_file.write_bytes(previous)
        raise HTTPException(503, f"Airflow is unavailable while activating DAG '{dag_id}': {exc}") from exc
    except httpx.HTTPError as exc:
        if previous is None:
            dag_file.unlink(missing_ok=True)
        else:
            dag_file.write_bytes(previous)
        raise HTTPException(503, f"Airflow activation request failed for DAG '{dag_id}': {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


@router.post("/transforms")
async def create_transform(req: TransformCreateRequest, db: Session = Depends(get_db)):
    if req.target_namespace not in NAMESPACES:
        raise HTTPException(400, f"target namespace must be one of {NAMESPACES}")
    if req.source_namespace == req.target_namespace:
        raise HTTPException(400, "source and target namespace must differ")
    _validate_transform_sql(req.sql)
    await _explain_check(req.sql)

    dag_id = f"transform_{_safe_id(req.name)}"
    clash = db.query(SavedTransform).filter(
        SavedTransform.dag_id == dag_id, SavedTransform.name != req.name
    ).first()
    if clash:
        raise HTTPException(
            409,
            f"Name normalizes to DAG id '{dag_id}' which is already used by transform '{clash.name}' — choose a different name",
        )

    existing = db.query(SavedTransform).filter(SavedTransform.name == req.name).first()
    if existing and not req.overwrite:
        raise HTTPException(409, f"Transform '{req.name}' already exists")

    candidate = SimpleNamespace(
        name=req.name,
        description=req.description,
        source_namespace=req.source_namespace,
        target_namespace=req.target_namespace,
        target_table=req.target_table,
        sql=req.sql,
        schedule=req.schedule,
    )
    try:
        await _deploy_dag(dag_id, _generate_dag(candidate))
    except Exception:
        db.rollback()
        raise

    if existing:
        row = existing
        row.description = req.description
        row.source_namespace = req.source_namespace
        row.target_namespace = req.target_namespace
        row.target_table = req.target_table
        row.sql = req.sql
        row.schedule = req.schedule
        row.updated_at = datetime.utcnow()
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
        )
        db.add(row)
    row.status = "deployed"
    row.dag_id = dag_id
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise

    return {
        "id": str(row.id),
        "name": row.name,
        "dag_id": dag_id,
        "status": "deployed",
        "message": "Transform deployed and activated in Airflow.",
    }


async def _last_runs(dag_ids: list) -> dict:
    """Airflow에서 각 DAG의 최근 run 1건 — best-effort(5s), 실패는 None."""
    out: dict = {}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            async def one(d):
                try:
                    r = await client.get(f"{AIRFLOW_API}/dags/{d}/dagRuns",
                                         auth=_airflow_auth(),
                                         params={"limit": 1, "order_by": "-execution_date"})
                    runs = r.json().get("dag_runs", [])
                    if runs:
                        out[d] = {"state": runs[0].get("state"),
                                  "at": runs[0].get("end_date") or runs[0].get("execution_date")}
                except Exception:
                    pass
            await asyncio.gather(*(one(d) for d in dag_ids))
    except Exception:
        pass
    return out


@router.get("/transforms")
async def list_transforms(db: Session = Depends(get_db)):
    rows = db.query(SavedTransform).order_by(SavedTransform.updated_at.desc()).all()
    runs = await _last_runs([r.dag_id for r in rows if r.dag_id])
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
                "last_run_state": (runs.get(r.dag_id) or {}).get("state"),
                "last_run_at": (runs.get(r.dag_id) or {}).get("at"),
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


@router.patch("/transforms/{transform_id}")
async def update_transform(
    transform_id: str,
    req: TransformUpdateRequest,
    db: Session = Depends(get_db),
):
    try:
        transform_uuid = uuid.UUID(transform_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid transform id") from exc
    row = db.query(SavedTransform).filter(SavedTransform.id == transform_uuid).first()
    if not row:
        raise HTTPException(404, "Transform not found")

    fields_set = getattr(req, "model_fields_set", getattr(req, "__fields_set__", set()))
    values = {
        "description": req.description if "description" in fields_set else row.description,
        "source_namespace": req.source_namespace if "source_namespace" in fields_set else row.source_namespace,
        "target_namespace": req.target_namespace if "target_namespace" in fields_set else row.target_namespace,
        "target_table": req.target_table if "target_table" in fields_set else row.target_table,
        "sql": req.sql if "sql" in fields_set else row.sql,
        "schedule": req.schedule if "schedule" in fields_set else row.schedule,
    }
    if not values["source_namespace"] or not values["target_namespace"] or not values["target_table"] or not values["sql"]:
        raise HTTPException(400, "source_namespace, target_namespace, target_table, and sql cannot be empty")
    if values["target_namespace"] not in NAMESPACES:
        raise HTTPException(400, f"target namespace must be one of {NAMESPACES}")
    if values["source_namespace"] == values["target_namespace"]:
        raise HTTPException(400, "source and target namespace must differ")
    _validate_transform_sql(values["sql"])
    await _explain_check(values["sql"])

    dag_id = row.dag_id or f"transform_{_safe_id(row.name)}"
    candidate = SimpleNamespace(name=row.name, **values)
    try:
        await _deploy_dag(dag_id, _generate_dag(candidate))
    except Exception:
        db.rollback()
        raise

    for field, value in values.items():
        setattr(row, field, value)
    row.dag_id = dag_id
    row.status = "deployed"
    row.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise
    return {
        "id": str(row.id),
        "name": row.name,
        "dag_id": row.dag_id,
        "status": row.status,
        "message": "Transform updated and activated in Airflow.",
    }


@router.post("/transforms/{transform_id}/trigger")
async def trigger_transform(transform_id: str, db: Session = Depends(get_db)):
    row = db.query(SavedTransform).filter(SavedTransform.id == uuid.UUID(transform_id)).first()
    if not row or not row.dag_id:
        raise HTTPException(404, "Transform not found or not deployed")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            activation = await client.patch(
                f"{AIRFLOW_API}/dags/{row.dag_id}",
                auth=_airflow_auth(),
                json={"is_paused": False},
            )
            if activation.status_code not in (200, 204):
                raise HTTPException(502, f"Airflow activation failed: {_airflow_response_detail(activation)}")
            response = await client.post(
                f"{AIRFLOW_API}/dags/{row.dag_id}/dagRuns",
                auth=_airflow_auth(),
                json={"conf": {}},
            )
        if response.status_code not in (200, 201):
            raise HTTPException(502, f"Airflow trigger failed: {_airflow_response_detail(response)}")
        return {"success": True, "dag_id": row.dag_id, "run": response.json()}
    except HTTPException:
        raise
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(503, f"Airflow is unavailable while triggering the transform: {exc}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Airflow trigger request failed: {exc}") from exc


async def _remove_remote_dag(dag_id: str) -> None:
    """Pause and delete a DAG; 404 means the remote state is already absent."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            paused = await client.patch(
                f"{AIRFLOW_API}/dags/{dag_id}",
                auth=_airflow_auth(),
                json={"is_paused": True},
            )
            if paused.status_code == 404:
                return
            if paused.status_code not in (200, 204):
                raise HTTPException(
                    502,
                    f"Airflow failed to pause DAG '{dag_id}': {_airflow_response_detail(paused)}",
                )
            deleted = await client.delete(
                f"{AIRFLOW_API}/dags/{dag_id}",
                auth=_airflow_auth(),
            )
            if deleted.status_code not in (200, 204, 404):
                raise HTTPException(
                    502,
                    f"Airflow failed to delete DAG '{dag_id}': {_airflow_response_detail(deleted)}",
                )
    except HTTPException:
        raise
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(503, f"Airflow is unavailable while deleting DAG '{dag_id}': {exc}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Airflow delete request failed for DAG '{dag_id}': {exc}") from exc


@router.delete("/transforms/{transform_id}")
async def delete_transform(transform_id: str, db: Session = Depends(get_db)):
    try:
        transform_uuid = uuid.UUID(transform_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid transform id") from exc
    row = db.query(SavedTransform).filter(SavedTransform.id == transform_uuid).first()
    if not row:
        raise HTTPException(404, "Transform not found")

    if row.dag_id:
        try:
            await _remove_remote_dag(row.dag_id)
        except Exception:
            db.rollback()
            raise
        (DAGS_PATH / f"{row.dag_id}.py").unlink(missing_ok=True)

    db.delete(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"success": True}
