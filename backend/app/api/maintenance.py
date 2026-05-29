"""
Iceberg 테이블 유지보수 (P0-3).

주기적으로 모든 Iceberg 테이블에 대해:
  1. compaction  — ALTER TABLE … EXECUTE optimize(file_size_threshold)
  2. 스냅샷 만료  — ALTER TABLE … EXECUTE expire_snapshots(retention_threshold)
  3. 고아 파일 제거 — ALTER TABLE … EXECUTE remove_orphan_files(retention_threshold)

PyIceberg 적재(P0-1)가 만드는 스몰파일·스냅샷 누적을 정리하고 스토리지를 회수한다.
Airflow DAG(PythonOperator + TrinoHook)로 information_schema를 동적 순회하며,
테이블별 try/except로 격리한다.

DAG 파일은 transforms와 동일하게 공유 dags PVC(/opt/airflow/dags)에 배포된다.
"""
import os
import logging

import httpx
from fastapi import APIRouter, HTTPException

# transforms의 배포/연결 헬퍼·상수 재사용 (동일 메커니즘)
from app.api.transforms import (
    _deploy_dag, _ensure_trino_connection, DAGS_PATH, AIRFLOW_API, AIRFLOW_AUTH,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DAG_ID = "datapond_iceberg_maintenance"

# 설정 (env override 가능 · DAG 코드에 baked-in)
SCHEDULE          = os.getenv("DATAPOND_MAINTENANCE_SCHEDULE", "0 3 * * *")   # 매일 03:00
TARGET_FILE_SIZE  = os.getenv("DATAPOND_MAINTENANCE_FILE_SIZE", "128MB")
SNAPSHOT_RETENTION = os.getenv("DATAPOND_MAINTENANCE_SNAPSHOT_RETENTION", "7d")
ORPHAN_RETENTION   = os.getenv("DATAPOND_MAINTENANCE_ORPHAN_RETENTION", "7d")
# stock Airflow 이미지에는 trino provider/라이브러리가 없으므로 Trino REST API를 requests로 직접 호출
TRINO_HOST        = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT        = int(os.getenv("TRINO_SERVICE_PORT", "8080"))


def _generate_dag() -> str:
    """유지보수 DAG 코드 생성 (설정값 baked-in)."""
    schedule = f'"{SCHEDULE}"' if SCHEDULE else "None"
    return f'''"""
Auto-generated DataPond Iceberg 유지보수 DAG.
모든 Iceberg 테이블에 optimize / expire_snapshots / remove_orphan_files 적용.
설정: file_size={TARGET_FILE_SIZE}, snapshot_retention={SNAPSHOT_RETENTION}, orphan_retention={ORPHAN_RETENTION}

stock Airflow 이미지에는 trino provider가 없으므로 Trino REST API(/v1/statement)를
requests로 직접 호출한다(에어갭 환경에서 런타임 pip 설치 회피).
"""
import logging
import time
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

TRINO_URL          = "http://{TRINO_HOST}:{TRINO_PORT}"
FILE_SIZE          = "{TARGET_FILE_SIZE}"
SNAPSHOT_RETENTION = "{SNAPSHOT_RETENTION}"
ORPHAN_RETENTION   = "{ORPHAN_RETENTION}"

log = logging.getLogger("datapond.maintenance")


def _trino_exec(sql):
    """Trino REST 프로토콜: POST 후 nextUri를 끝까지 폴링, 에러 시 예외."""
    headers = {{"X-Trino-User": "datapond", "X-Trino-Catalog": "iceberg"}}
    resp = requests.post(TRINO_URL + "/v1/statement", data=sql.encode("utf-8"),
                         headers=headers, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    rows = []
    while True:
        if payload.get("data"):
            rows.extend(payload["data"])
        err = payload.get("error")
        if err:
            raise RuntimeError(err.get("message", "trino error"))
        nxt = payload.get("nextUri")
        if not nxt:
            break
        time.sleep(0.15)
        r = requests.get(nxt, headers=headers, timeout=60)
        r.raise_for_status()
        payload = r.json()
    return rows


def run_maintenance(**_):
    tables = _trino_exec(
        "SELECT table_schema, table_name FROM iceberg.information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema')"
    )
    summary = {{"tables": len(tables), "optimize": 0, "expire": 0, "orphan": 0, "errors": 0}}

    for schema, table in tables:
        fqtn = 'iceberg."%s"."%s"' % (schema, table)
        for label, sql in (
            ("optimize", "ALTER TABLE %s EXECUTE optimize(file_size_threshold => '%s')" % (fqtn, FILE_SIZE)),
            ("expire",   "ALTER TABLE %s EXECUTE expire_snapshots(retention_threshold => '%s')" % (fqtn, SNAPSHOT_RETENTION)),
            ("orphan",   "ALTER TABLE %s EXECUTE remove_orphan_files(retention_threshold => '%s')" % (fqtn, ORPHAN_RETENTION)),
        ):
            try:
                _trino_exec(sql)
                summary[label] += 1
            except Exception as e:  # noqa: BLE001 — 테이블별 격리
                summary["errors"] += 1
                log.warning("[maintenance] %s %s skip: %s", fqtn, label, e)

    log.info("[maintenance] done: %s", summary)
    return summary


default_args = {{
    "owner": "datapond",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}}

with DAG(
    dag_id="{DAG_ID}",
    description="Iceberg table maintenance — compaction, snapshot expiry, orphan removal",
    schedule_interval={schedule},
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["maintenance", "iceberg", "datapond"],
    default_args=default_args,
) as dag:
    PythonOperator(task_id="run_maintenance", python_callable=run_maintenance)
'''


async def deploy_maintenance_dag() -> bool:
    """DAG 파일을 dags PVC에 쓰고 unpause. 멱등(매 호출 덮어쓰기)."""
    await _ensure_trino_connection()
    return await _deploy_dag(DAG_ID, _generate_dag())


# ── API ───────────────────────────────────────────────────────────────────────

@router.post("/maintenance/deploy")
async def deploy():
    """유지보수 DAG를 (재)배포한다."""
    try:
        await deploy_maintenance_dag()
        return {
            "dag_id": DAG_ID, "deployed": True, "schedule": SCHEDULE,
            "file_size": TARGET_FILE_SIZE,
            "snapshot_retention": SNAPSHOT_RETENTION,
            "orphan_retention": ORPHAN_RETENTION,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"deploy failed: {e}")


@router.post("/maintenance/run")
async def run_now():
    """유지보수 DAG를 즉시 1회 트리거한다."""
    try:
        await deploy_maintenance_dag()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{AIRFLOW_API}/dags/{DAG_ID}/dagRuns",
                auth=AIRFLOW_AUTH, json={},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"airflow trigger failed: {resp.text}")
        return {"dag_id": DAG_ID, "triggered": True, "run": resp.json()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"run failed: {e}")


@router.get("/maintenance/status")
async def status():
    """DAG 상태 + 최근 실행 조회."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            dag_resp = await client.get(f"{AIRFLOW_API}/dags/{DAG_ID}", auth=AIRFLOW_AUTH)
            if dag_resp.status_code == 404:
                return {"dag_id": DAG_ID, "deployed": False}
            runs_resp = await client.get(
                f"{AIRFLOW_API}/dags/{DAG_ID}/dagRuns",
                auth=AIRFLOW_AUTH, params={"order_by": "-execution_date", "limit": 5},
            )
        dag = dag_resp.json()
        runs = runs_resp.json().get("dag_runs", []) if runs_resp.status_code < 400 else []
        return {
            "dag_id": DAG_ID,
            "deployed": True,
            "is_paused": dag.get("is_paused"),
            "schedule": SCHEDULE,
            "config": {
                "file_size": TARGET_FILE_SIZE,
                "snapshot_retention": SNAPSHOT_RETENTION,
                "orphan_retention": ORPHAN_RETENTION,
            },
            "recent_runs": [
                {"run_id": r.get("dag_run_id"), "state": r.get("state"),
                 "start": r.get("start_date"), "end": r.get("end_date")}
                for r in runs
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"status failed: {e}")
