"""Airflow DAG routes the Transforms page still uses: run history and delete.

The declarative pipeline builder (its save/validate/compile/deploy/upload routes, the
`app.pipelines` DSL compiler and the `pipelines` drafts table) was removed in 2.7: its
compiled DAGs were placeholder tasks and the deploy refused them. SQL transforms are
in app/api/transforms.py; Airflow DAG browsing is in app/api/airflow.py.
"""
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_permission
from app.runtime import component_secret

router = APIRouter()

AIRFLOW_API = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver.datapond.svc.cluster.local:8080/api/v1")
DAGS_PATH = Path(os.getenv("AIRFLOW_DAGS_PATH", "/opt/airflow/dags"))


def _airflow_auth() -> tuple:
    """Resolved per-request: fail-closed in prod when Airflow creds are missing."""
    return (
        os.getenv("AIRFLOW_USERNAME", "airflow"),
        component_secret("AIRFLOW_PASSWORD", "airflow", component="airflow"),
    )


async def _airflow_request(method: str, path: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15) as client:
        return await getattr(client, method)(f"{AIRFLOW_API}{path}", auth=_airflow_auth(), **kwargs)


def _dag_id(name: str) -> str:
    return name if name.startswith("datapond_") else f"datapond_{name}"


@router.get("/pipelines/{pipeline_name}/runs")
async def get_pipeline_runs(pipeline_name: str, limit: int = 10):
    """Execution history for a DAG (the assistant's `pipelines.recent_runs`)."""
    dag_id = _dag_id(pipeline_name)
    try:
        resp = await _airflow_request("get", f"/dags/{dag_id}/dagRuns?limit={limit}&order_by=-execution_date")
        if resp.status_code == 404:
            raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")
        if resp.status_code != 200:
            raise HTTPException(502, "Failed to fetch runs")
        data = resp.json()
        runs = data.get("dag_runs", [])
        return {"pipeline_name": pipeline_name, "runs": runs, "total": data.get("total_entries", len(runs))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Airflow connection error: {e}")


@router.delete("/pipelines/{pipeline_name}", dependencies=[Depends(require_permission("pipeline:write"))])
async def delete_pipeline(pipeline_name: str):
    """Delete a DAG: remove its file and pause/delete it in Airflow."""
    dag_id = _dag_id(pipeline_name)
    dag_file = DAGS_PATH / f"{dag_id}.py"
    file_removed = False
    if dag_file.exists():
        dag_file.unlink()
        file_removed = True

    airflow_deleted = False
    try:
        await _airflow_request("patch", f"/dags/{dag_id}", json={"is_paused": True})
        resp = await _airflow_request("delete", f"/dags/{dag_id}")
        airflow_deleted = resp.status_code in (200, 204)
    except Exception:
        pass  # Best-effort — file removal is the primary action

    if not file_removed and not airflow_deleted:
        raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")
    return {"success": True, "dag_id": dag_id, "file_removed": file_removed, "airflow_deleted": airflow_deleted}
