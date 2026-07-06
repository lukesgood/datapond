"""
Airflow API Integration - Complete pipeline orchestration and DAG management API
Provides REST API endpoints for Airflow DAG management
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import httpx
import os
from datetime import datetime

from app.runtime import component_secret

router = APIRouter()

# Airflow API configuration
AIRFLOW_API_BASE = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver.datapond.svc.cluster.local:8080/api/v1")
REQUEST_TIMEOUT = 30


def _airflow_auth() -> tuple:
    """Resolved per-request: fail-closed in prod when Airflow creds are missing."""
    return (
        os.getenv("AIRFLOW_USERNAME", "airflow"),
        component_secret("AIRFLOW_PASSWORD", "airflow", component="airflow"),
    )


# ============================================================================
# Pydantic Models
# ============================================================================

class DAG(BaseModel):
    dag_id: str
    is_paused: bool
    is_active: bool
    is_subdag: bool = False
    description: Optional[str] = None
    schedule_interval: Optional[str] = None
    last_parsed_time: Optional[str] = None
    fileloc: Optional[str] = None
    tags: List[str] = []
    owners: List[str] = []
    max_active_runs: Optional[int] = None
    max_active_tasks: Optional[int] = None
    has_task_concurrency_limits: bool = False
    has_import_errors: bool = False


class DAGDetails(BaseModel):
    dag_id: str
    is_paused: bool
    is_active: bool
    description: Optional[str] = None
    schedule_interval: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    tags: List[str] = []
    owners: List[str] = []
    timezone: Optional[str] = None
    catchup: bool = False
    orientation: Optional[str] = None
    concurrency: Optional[int] = None
    max_active_runs: Optional[int] = None
    max_active_tasks: Optional[int] = None
    dagrun_timeout: Optional[float] = None
    doc_md: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    fileloc: Optional[str] = None


class DagRun(BaseModel):
    dag_run_id: str
    dag_id: str
    execution_date: str
    logical_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    state: str  # queued, running, success, failed
    run_type: str  # manual, scheduled, backfill
    external_trigger: bool = False
    conf: Optional[Dict[str, Any]] = None
    data_interval_start: Optional[str] = None
    data_interval_end: Optional[str] = None
    note: Optional[str] = None


class TaskInstance(BaseModel):
    task_id: str
    dag_id: str
    execution_date: str
    dag_run_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    duration: Optional[float] = None
    state: Optional[str] = None
    try_number: Optional[int] = None
    max_tries: Optional[int] = None
    operator: Optional[str] = None
    pool: Optional[str] = None
    pool_slots: Optional[int] = None
    queue: Optional[str] = None
    priority_weight: Optional[int] = None
    hostname: Optional[str] = None


class DAGTask(BaseModel):
    task_id: str
    owner: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    trigger_rule: str = "all_success"
    depends_on_past: bool = False
    wait_for_downstream: bool = False
    retries: int = 0
    queue: str = "default"
    pool: str = "default_pool"
    pool_slots: int = 1
    execution_timeout: Optional[float] = None
    retry_delay: Optional[float] = None
    priority_weight: int = 1
    weight_rule: str = "downstream"
    ui_color: str = "#fff"
    ui_fgcolor: str = "#000"
    downstream_task_ids: List[str] = []
    operator_name: Optional[str] = None


class TriggerDagRequest(BaseModel):
    conf: Optional[Dict[str, Any]] = None
    execution_date: Optional[str] = None
    logical_date: Optional[str] = None
    note: Optional[str] = None
    dag_run_id: Optional[str] = None


class DAGUpdateRequest(BaseModel):
    is_paused: Optional[bool] = None


class TaskInstanceClearRequest(BaseModel):
    dry_run: bool = False
    reset_dag_runs: bool = False
    only_failed: bool = False
    only_running: bool = False
    include_subdags: bool = False
    include_parentdag: bool = False
    include_upstream: bool = False
    include_downstream: bool = False


class DagStats(BaseModel):
    dag_id: str
    total_runs: int
    success_runs: int
    failed_runs: int
    running_runs: int
    queued_runs: int
    success_rate: float
    avg_duration: Optional[float] = None


class TaskLog(BaseModel):
    task_id: str
    try_number: int
    content: str
    continuation_token: Optional[str] = None


class Connection(BaseModel):
    connection_id: str
    conn_type: str
    description: Optional[str] = None
    host: Optional[str] = None
    login: Optional[str] = None
    schema_: Optional[str] = Field(None, alias="schema")
    port: Optional[int] = None
    extra: Optional[str] = None


class ConnectionCreateRequest(BaseModel):
    connection_id: str
    conn_type: str
    description: Optional[str] = None
    host: Optional[str] = None
    login: Optional[str] = None
    schema_: Optional[str] = Field(None, alias="schema")
    port: Optional[int] = None
    password: Optional[str] = None
    extra: Optional[str] = None


class AirflowStats(BaseModel):
    total_dags: int
    active_dags: int
    paused_dags: int
    total_dag_runs: int
    queued_dag_runs: int
    running_dag_runs: int
    success_dag_runs: int
    failed_dag_runs: int


class AirflowHealth(BaseModel):
    status: str
    version: Optional[str] = None
    metadatabase: Optional[Dict[str, Any]] = None
    scheduler: Optional[Dict[str, Any]] = None


class DAGGraphNode(BaseModel):
    id: str
    type: str = "default"
    data: Dict[str, Any]
    position: Dict[str, float] = {"x": 0, "y": 0}


class DAGGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str = "smoothstep"


# ============================================================================
# Helper Functions
# ============================================================================

async def airflow_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    allow_404: bool = False
) -> Dict[str, Any]:
    """Make authenticated request to Airflow API"""
    url = f"{AIRFLOW_API_BASE}{endpoint}"
    auth = _airflow_auth()

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(
                method=method,
                url=url,
                auth=auth,
                params=params,
                json=json_data
            )

            if response.status_code == 404 and allow_404:
                raise HTTPException(status_code=404, detail="Resource not found")

            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except:
                    error_detail = response.text
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Airflow API error: {error_detail}"
                )

            return response.json() if response.text else {}

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Airflow service timeout")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot connect to Airflow service")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# ============================================================================
# DAG Management Endpoints
# ============================================================================

@router.get("/airflow/dags", response_model=Dict[str, Any])
async def list_dags(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    only_active: bool = Query(False),
    paused: Optional[bool] = Query(None),
    tags: Optional[str] = Query(None)
):
    """
    List all DAGs from Airflow

    Args:
        limit: Number of DAGs to return
        offset: Offset for pagination
        only_active: Only show active DAGs
        paused: Filter by paused status
        tags: Filter by tags (comma-separated)

    Returns:
        List of DAGs with pagination info
    """
    params = {"limit": limit, "offset": offset, "only_active": only_active}
    if paused is not None:
        params["paused"] = paused
    if tags:
        params["tags"] = tags

    data = await airflow_request("GET", "/dags", params=params)

    dags = []
    for dag_data in data.get("dags", []):
        schedule_interval = dag_data.get("schedule_interval")
        if isinstance(schedule_interval, dict):
            schedule_interval = schedule_interval.get("value")
        schedule_interval = str(schedule_interval) if schedule_interval else None

        dags.append(DAG(
            dag_id=dag_data["dag_id"],
            is_paused=dag_data.get("is_paused", True),
            is_active=dag_data.get("is_active", False),
            is_subdag=dag_data.get("is_subdag", False),
            description=dag_data.get("description"),
            schedule_interval=schedule_interval,
            last_parsed_time=dag_data.get("last_parsed_time"),
            fileloc=dag_data.get("fileloc"),
            tags=[tag["name"] if isinstance(tag, dict) else tag for tag in dag_data.get("tags", [])],
            owners=dag_data.get("owners", []),
            max_active_runs=dag_data.get("max_active_runs"),
            max_active_tasks=dag_data.get("max_active_tasks"),
            has_task_concurrency_limits=dag_data.get("has_task_concurrency_limits", False),
            has_import_errors=dag_data.get("has_import_errors", False)
        ).dict())

    return {
        "dags": dags,
        "total_entries": data.get("total_entries", len(dags))
    }


@router.get("/airflow/dags/{dag_id}", response_model=DAGDetails)
async def get_dag(dag_id: str):
    """
    Get DAG details by ID

    Args:
        dag_id: DAG ID

    Returns:
        DAG details
    """
    data = await airflow_request("GET", f"/dags/{dag_id}", allow_404=True)

    schedule_interval = data.get("schedule_interval")
    if isinstance(schedule_interval, dict):
        schedule_interval = schedule_interval.get("value")
    schedule_interval = str(schedule_interval) if schedule_interval else None

    return DAGDetails(
        dag_id=data["dag_id"],
        is_paused=data.get("is_paused", True),
        is_active=data.get("is_active", False),
        description=data.get("description"),
        schedule_interval=schedule_interval,
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        tags=[tag["name"] if isinstance(tag, dict) else tag for tag in data.get("tags", [])],
        owners=data.get("owners", []),
        timezone=data.get("timezone"),
        catchup=data.get("catchup", False),
        orientation=data.get("orientation"),
        concurrency=data.get("concurrency"),
        max_active_runs=data.get("max_active_runs"),
        max_active_tasks=data.get("max_active_tasks"),
        dagrun_timeout=data.get("dagrun_timeout"),
        doc_md=data.get("doc_md"),
        params=data.get("params"),
        fileloc=data.get("fileloc")
    )


@router.patch("/airflow/dags/{dag_id}", response_model=DAG)
async def update_dag(dag_id: str, request: DAGUpdateRequest):
    """
    Update DAG (pause/unpause)

    Args:
        dag_id: DAG ID
        request: Update parameters

    Returns:
        Updated DAG info
    """
    data = await airflow_request(
        "PATCH",
        f"/dags/{dag_id}",
        json_data=request.dict(exclude_none=True),
        allow_404=True
    )

    schedule_interval = data.get("schedule_interval")
    if isinstance(schedule_interval, dict):
        schedule_interval = schedule_interval.get("value")
    schedule_interval = str(schedule_interval) if schedule_interval else None

    return DAG(
        dag_id=data["dag_id"],
        is_paused=data.get("is_paused", True),
        is_active=data.get("is_active", False),
        is_subdag=data.get("is_subdag", False),
        description=data.get("description"),
        schedule_interval=schedule_interval,
        last_parsed_time=data.get("last_parsed_time"),
        fileloc=data.get("fileloc"),
        tags=[tag["name"] if isinstance(tag, dict) else tag for tag in data.get("tags", [])],
        owners=data.get("owners", []),
        max_active_runs=data.get("max_active_runs"),
        max_active_tasks=data.get("max_active_tasks"),
        has_task_concurrency_limits=data.get("has_task_concurrency_limits", False),
        has_import_errors=data.get("has_import_errors", False)
    )


@router.get("/airflow/dags/{dag_id}/tasks", response_model=Dict[str, Any])
async def list_dag_tasks(
    dag_id: str,
    order_by: Optional[str] = Query(None)
):
    """
    List tasks in a DAG

    Args:
        dag_id: DAG ID
        order_by: Field to order by

    Returns:
        List of tasks in the DAG
    """
    params = {}
    if order_by:
        params["order_by"] = order_by

    data = await airflow_request("GET", f"/dags/{dag_id}/tasks", params=params, allow_404=True)

    tasks = []
    for task_data in data.get("tasks", []):
        tasks.append(DAGTask(
            task_id=task_data["task_id"],
            owner=task_data.get("owner", "airflow"),
            start_date=task_data.get("start_date"),
            end_date=task_data.get("end_date"),
            trigger_rule=task_data.get("trigger_rule", "all_success"),
            depends_on_past=task_data.get("depends_on_past", False),
            wait_for_downstream=task_data.get("wait_for_downstream", False),
            retries=task_data.get("retries", 0),
            queue=task_data.get("queue", "default"),
            pool=task_data.get("pool", "default_pool"),
            pool_slots=task_data.get("pool_slots", 1),
            execution_timeout=task_data.get("execution_timeout"),
            retry_delay=task_data.get("retry_delay", {}).get("seconds") if isinstance(task_data.get("retry_delay"), dict) else task_data.get("retry_delay"),
            priority_weight=task_data.get("priority_weight", 1),
            weight_rule=task_data.get("weight_rule", "downstream"),
            ui_color=task_data.get("ui_color", "#fff"),
            ui_fgcolor=task_data.get("ui_fgcolor", "#000"),
            downstream_task_ids=task_data.get("downstream_task_ids", []),
            operator_name=task_data.get("operator_name")
        ).dict())

    return {
        "tasks": tasks,
        "total_entries": data.get("total_entries", len(tasks))
    }


@router.get("/airflow/dags/{dag_id}/details")
async def get_dag_details(dag_id: str):
    """
    Get DAG details (alias for backwards compatibility)

    Args:
        dag_id: DAG ID

    Returns:
        DAG details
    """
    return await airflow_request("GET", f"/dags/{dag_id}/details", allow_404=True)


@router.get("/airflow/dags/{dag_id}/structure")
async def get_dag_structure(dag_id: str):
    """
    Get DAG structure as a Data Asset Lineage Graph.
    Interprets Airflow tasks through DataPond DSL conventions:
    - Tasks with 'source'/'extract'/'ingest' → Source nodes (bronze)
    - Tasks with 'quality'/'check'/'validate' → Quality gate nodes
    - Other tasks → Table/Transform nodes (silver/gold)

    Returns asset-centric graph with metadata for rich visualization.
    """
    data = await airflow_request("GET", f"/dags/{dag_id}/tasks", allow_404=True)

    nodes = []
    edges = []
    tasks = data.get("tasks", [])

    # Classify tasks into asset types based on naming conventions
    source_keywords = {"source", "extract", "ingest", "load_raw", "import", "fetch"}
    quality_keywords = {"quality", "check", "validate", "test", "assert", "expect"}
    gold_keywords = {"report", "agg", "summary", "mart", "serve", "export", "publish"}

    def classify_task(task_id: str, operator: str) -> dict:
        tid = task_id.lower()
        op = operator.lower()

        if any(k in tid for k in source_keywords) or "sensor" in op:
            return {"asset_type": "source", "layer": "bronze"}
        if any(k in tid for k in quality_keywords):
            return {"asset_type": "quality", "layer": "quality"}
        if any(k in tid for k in gold_keywords):
            return {"asset_type": "table", "layer": "gold"}
        # Default: silver transform
        return {"asset_type": "table", "layer": "silver"}

    for task in tasks:
        task_id = task["task_id"]
        operator = task.get("operator_name") or task.get("class_ref", {}).get("class_name", "")
        classification = classify_task(task_id, operator)

        nodes.append({
            "id": task_id,
            "type": classification["asset_type"],
            "data": {
                "label": task_id,
                "asset_type": classification["asset_type"],
                "layer": classification["layer"],
                "operator": operator,
                "mode": "incremental" if "incremental" in task_id.lower() else "full",
                "schedule": None,  # filled from DAG level
            },
            "position": {"x": 0, "y": 0},
        })

        for downstream in task.get("downstream_task_ids", []):
            edges.append({
                "id": f"{task_id}-{downstream}",
                "source": task_id,
                "target": downstream,
            })

    return {
        "dag_id": dag_id,
        "nodes": nodes,
        "edges": edges,
    }


# ============================================================================
# DAG Run Endpoints
# ============================================================================

@router.get("/airflow/dag-runs", response_model=Dict[str, Any])
async def list_all_dag_runs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    state: Optional[str] = Query(None),
    order_by: str = Query("-start_date")
):
    """
    List all DAG runs across all DAGs

    Args:
        limit: Number of runs to return
        offset: Offset for pagination
        state: Filter by state
        order_by: Sort order (e.g. -start_date)

    Returns:
        List of DAG runs
    """
    # Airflow API uses page_limit and page_offset, not limit and offset
    params = {"page_limit": limit, "page_offset": offset, "order_by": order_by}
    if state:
        params["state"] = state

    data = await airflow_request("POST", "/dags/~/dagRuns/list", json_data=params)

    dag_runs = []
    for run_data in data.get("dag_runs", []):
        dag_runs.append(DagRun(
            dag_run_id=run_data["dag_run_id"],
            dag_id=run_data["dag_id"],
            execution_date=run_data.get("execution_date", run_data.get("logical_date", "")),
            logical_date=run_data.get("logical_date"),
            start_date=run_data.get("start_date"),
            end_date=run_data.get("end_date"),
            state=run_data.get("state", "unknown"),
            run_type=run_data.get("run_type", "scheduled"),
            external_trigger=run_data.get("external_trigger", False),
            conf=run_data.get("conf"),
            data_interval_start=run_data.get("data_interval_start"),
            data_interval_end=run_data.get("data_interval_end"),
            note=run_data.get("note")
        ).dict())

    return {
        "dag_runs": dag_runs,
        "total_entries": data.get("total_entries", len(dag_runs))
    }


async def _fetch_dag_runs(
    dag_id: str,
    limit: int = 100,
    offset: int = 0,
    state: Optional[str] = None,
    order_by: str = "-execution_date"
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset, "order_by": order_by}
    if state:
        params["state"] = state
    data = await airflow_request("GET", f"/dags/{dag_id}/dagRuns", params=params, allow_404=True)
    dag_runs = []
    for run_data in data.get("dag_runs", []):
        dag_runs.append(DagRun(
            dag_run_id=run_data["dag_run_id"],
            dag_id=run_data["dag_id"],
            execution_date=run_data.get("execution_date", run_data.get("logical_date", "")),
            logical_date=run_data.get("logical_date"),
            start_date=run_data.get("start_date"),
            end_date=run_data.get("end_date"),
            state=run_data.get("state", "unknown"),
            run_type=run_data.get("run_type", "scheduled"),
            external_trigger=run_data.get("external_trigger", False),
            conf=run_data.get("conf"),
            data_interval_start=run_data.get("data_interval_start"),
            data_interval_end=run_data.get("data_interval_end"),
            note=run_data.get("note")
        ).dict())
    return {"dag_runs": dag_runs, "total_entries": data.get("total_entries", len(dag_runs))}


@router.get("/airflow/dags/{dag_id}/dag-runs", response_model=Dict[str, Any])
async def list_dag_runs(
    dag_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    state: Optional[str] = Query(None),
    order_by: str = Query("-execution_date")
):
    """List runs for a specific DAG"""
    return await _fetch_dag_runs(dag_id, limit=limit, offset=offset, state=state, order_by=order_by)


# Alias endpoint for backwards compatibility
@router.get("/airflow/dags/{dag_id}/runs", response_model=List[DagRun])
async def list_dag_runs_alias(
    dag_id: str,
    limit: int = Query(25, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    state: Optional[str] = Query(None)
):
    """
    List runs for a specific DAG (backwards compatibility alias)
    """
    result = await _fetch_dag_runs(dag_id, limit=limit, offset=offset, state=state)
    return result["dag_runs"]


@router.post("/airflow/dags/{dag_id}/dag-runs", response_model=DagRun)
async def trigger_dag_run(dag_id: str, request: TriggerDagRequest):
    """
    Trigger a new DAG run (alias: /airflow/dags/{dag_id}/runs)

    Args:
        dag_id: DAG ID
        request: DAG run parameters

    Returns:
        Created DAG run info
    """
    json_data = {}
    if request.logical_date:
        json_data["logical_date"] = request.logical_date
    elif request.execution_date:
        json_data["execution_date"] = request.execution_date
    if request.conf:
        json_data["conf"] = request.conf
    if request.note:
        json_data["note"] = request.note
    if request.dag_run_id:
        json_data["dag_run_id"] = request.dag_run_id

    data = await airflow_request("POST", f"/dags/{dag_id}/dagRuns", json_data=json_data, allow_404=True)

    return DagRun(
        dag_run_id=data["dag_run_id"],
        dag_id=data["dag_id"],
        execution_date=data.get("execution_date", data.get("logical_date", "")),
        logical_date=data.get("logical_date"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        state=data.get("state", "unknown"),
        run_type=data.get("run_type", "manual"),
        external_trigger=data.get("external_trigger", True),
        conf=data.get("conf"),
        data_interval_start=data.get("data_interval_start"),
        data_interval_end=data.get("data_interval_end"),
        note=data.get("note")
    )


# Alias endpoint for backwards compatibility
@router.post("/airflow/dags/{dag_id}/runs")
async def trigger_dag(dag_id: str, request: TriggerDagRequest):
    """
    Trigger a new DAG run (backwards compatibility alias)
    """
    return await trigger_dag_run(dag_id, request)


@router.get("/airflow/dags/{dag_id}/dag-runs/{dag_run_id}", response_model=DagRun)
async def get_dag_run(dag_id: str, dag_run_id: str):
    """
    Get DAG run details

    Args:
        dag_id: DAG ID
        dag_run_id: DAG run ID

    Returns:
        DAG run details
    """
    data = await airflow_request("GET", f"/dags/{dag_id}/dagRuns/{dag_run_id}", allow_404=True)

    return DagRun(
        dag_run_id=data["dag_run_id"],
        dag_id=data["dag_id"],
        execution_date=data.get("execution_date", data.get("logical_date", "")),
        logical_date=data.get("logical_date"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        state=data.get("state", "unknown"),
        run_type=data.get("run_type", "scheduled"),
        external_trigger=data.get("external_trigger", False),
        conf=data.get("conf"),
        data_interval_start=data.get("data_interval_start"),
        data_interval_end=data.get("data_interval_end"),
        note=data.get("note")
    )


# Alias endpoint for backwards compatibility
@router.get("/airflow/runs/{run_id}", response_model=DagRun)
async def get_dag_run_alias(run_id: str, dag_id: str):
    """
    Get a specific DAG run (backwards compatibility alias)
    """
    return await get_dag_run(dag_id, run_id)


@router.delete("/airflow/dags/{dag_id}/dag-runs/{dag_run_id}")
async def delete_dag_run(dag_id: str, dag_run_id: str):
    """
    Delete a DAG run

    Args:
        dag_id: DAG ID
        dag_run_id: DAG run ID

    Returns:
        Success message
    """
    await airflow_request("DELETE", f"/dags/{dag_id}/dagRuns/{dag_run_id}", allow_404=True)
    return {"message": f"DAG run {dag_run_id} deleted successfully"}


# ============================================================================
# Task Instance Endpoints
# ============================================================================

@router.get("/airflow/dags/{dag_id}/dag-runs/{dag_run_id}/task-instances", response_model=Dict[str, Any])
async def list_task_instances(dag_id: str, dag_run_id: str):
    """
    List task instances for a DAG run

    Args:
        dag_id: DAG ID
        dag_run_id: DAG run ID

    Returns:
        List of task instances
    """
    data = await airflow_request("GET", f"/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances", allow_404=True)

    tasks = []
    for task_data in data.get("task_instances", []):
        tasks.append(TaskInstance(
            task_id=task_data["task_id"],
            dag_id=task_data["dag_id"],
            execution_date=task_data.get("execution_date", ""),
            dag_run_id=task_data.get("dag_run_id"),
            start_date=task_data.get("start_date"),
            end_date=task_data.get("end_date"),
            duration=task_data.get("duration"),
            state=task_data.get("state"),
            try_number=task_data.get("try_number"),
            max_tries=task_data.get("max_tries"),
            operator=task_data.get("operator"),
            pool=task_data.get("pool"),
            pool_slots=task_data.get("pool_slots"),
            queue=task_data.get("queue"),
            priority_weight=task_data.get("priority_weight"),
            hostname=task_data.get("hostname")
        ).dict())

    return {
        "task_instances": tasks,
        "total_entries": data.get("total_entries", len(tasks))
    }


# Alias endpoint for backwards compatibility
@router.get("/airflow/runs/{run_id}/tasks", response_model=List[TaskInstance])
async def list_task_instances_alias(run_id: str, dag_id: str):
    """
    List task instances for a DAG run (backwards compatibility alias)
    """
    result = await list_task_instances(dag_id, run_id)
    return result["task_instances"]


@router.get("/airflow/dags/{dag_id}/dag-runs/{dag_run_id}/task-instances/{task_id}", response_model=TaskInstance)
async def get_task_instance(dag_id: str, dag_run_id: str, task_id: str):
    """
    Get task instance details

    Args:
        dag_id: DAG ID
        dag_run_id: DAG run ID
        task_id: Task ID

    Returns:
        Task instance details
    """
    data = await airflow_request("GET", f"/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}", allow_404=True)

    return TaskInstance(
        task_id=data["task_id"],
        dag_id=data["dag_id"],
        execution_date=data.get("execution_date", ""),
        dag_run_id=data.get("dag_run_id"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        duration=data.get("duration"),
        state=data.get("state"),
        try_number=data.get("try_number"),
        max_tries=data.get("max_tries"),
        operator=data.get("operator"),
        pool=data.get("pool"),
        pool_slots=data.get("pool_slots"),
        queue=data.get("queue"),
        priority_weight=data.get("priority_weight"),
        hostname=data.get("hostname")
    )


@router.get("/airflow/dags/{dag_id}/dag-runs/{dag_run_id}/task-instances/{task_id}/logs/{task_try_number}", response_model=TaskLog)
async def get_task_logs(
    dag_id: str,
    dag_run_id: str,
    task_id: str,
    task_try_number: int = 1,
    full_content: bool = Query(False),
    token: Optional[str] = Query(None)
):
    """
    Get task instance logs

    Args:
        dag_id: DAG ID
        dag_run_id: DAG run ID
        task_id: Task ID
        task_try_number: Task try number
        full_content: Return full log content
        token: Continuation token

    Returns:
        Task logs
    """
    params = {"full_content": full_content}
    if token:
        params["token"] = token

    data = await airflow_request(
        "GET",
        f"/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/{task_try_number}",
        params=params,
        allow_404=True
    )

    return TaskLog(
        task_id=task_id,
        try_number=task_try_number,
        content=data.get("content", "No logs available"),
        continuation_token=data.get("continuation_token")
    )


# Alias endpoint for backwards compatibility
@router.get("/airflow/tasks/{task_id}/logs", response_model=TaskLog)
async def get_task_logs_alias(
    task_id: str,
    dag_id: str,
    run_id: str,
    try_number: int = 1
):
    """
    Get logs for a specific task instance (backwards compatibility alias)
    """
    return await get_task_logs(dag_id, run_id, task_id, try_number)


@router.post("/airflow/dags/{dag_id}/clear-task-instances")
async def clear_task_instances(dag_id: str, request: TaskInstanceClearRequest):
    """
    Clear task instances (for retry)

    Args:
        dag_id: DAG ID
        request: Clear parameters

    Returns:
        List of cleared task instances
    """
    data = await airflow_request(
        "POST",
        f"/dags/{dag_id}/clearTaskInstances",
        json_data=request.dict(),
        allow_404=True
    )

    return {
        "task_instances": data.get("task_instances", []),
        "message": "Task instances cleared successfully"
    }


# ============================================================================
# Connection Endpoints
# ============================================================================

@router.get("/airflow/connections", response_model=Dict[str, Any])
async def list_connections(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List Airflow connections

    Args:
        limit: Number of connections to return
        offset: Offset for pagination

    Returns:
        List of connections (passwords masked)
    """
    params = {"limit": limit, "offset": offset}
    data = await airflow_request("GET", "/connections", params=params)

    connections = []
    for conn_data in data.get("connections", []):
        connections.append(Connection(
            connection_id=conn_data["connection_id"],
            conn_type=conn_data["conn_type"],
            description=conn_data.get("description"),
            host=conn_data.get("host"),
            login=conn_data.get("login"),
            schema_=conn_data.get("schema"),
            port=conn_data.get("port"),
            extra=conn_data.get("extra")
        ).dict())

    return {
        "connections": connections,
        "total_entries": data.get("total_entries", len(connections))
    }


@router.post("/airflow/connections", response_model=Connection)
async def create_connection(request: ConnectionCreateRequest):
    """
    Create a new Airflow connection

    Args:
        request: Connection parameters

    Returns:
        Created connection info
    """
    data = await airflow_request("POST", "/connections", json_data=request.dict(exclude_none=True))

    return Connection(
        connection_id=data["connection_id"],
        conn_type=data["conn_type"],
        description=data.get("description"),
        host=data.get("host"),
        login=data.get("login"),
        schema_=data.get("schema"),
        port=data.get("port"),
        extra=data.get("extra")
    )


@router.get("/airflow/connections/{connection_id}", response_model=Connection)
async def get_connection(connection_id: str):
    """
    Get connection details

    Args:
        connection_id: Connection ID

    Returns:
        Connection details (password masked)
    """
    data = await airflow_request("GET", f"/connections/{connection_id}", allow_404=True)

    return Connection(
        connection_id=data["connection_id"],
        conn_type=data["conn_type"],
        description=data.get("description"),
        host=data.get("host"),
        login=data.get("login"),
        schema_=data.get("schema"),
        port=data.get("port"),
        extra=data.get("extra")
    )


@router.delete("/airflow/connections/{connection_id}")
async def delete_connection(connection_id: str):
    """
    Delete a connection

    Args:
        connection_id: Connection ID

    Returns:
        Success message
    """
    await airflow_request("DELETE", f"/connections/{connection_id}", allow_404=True)
    return {"message": f"Connection {connection_id} deleted successfully"}


# ============================================================================
# Statistics & Health Endpoints
# ============================================================================

@router.get("/airflow/dags/{dag_id}/stats", response_model=DagStats)
async def get_dag_stats(dag_id: str, limit: int = Query(100, ge=1, le=1000)):
    """
    Get statistics for a DAG

    Args:
        dag_id: DAG ID
        limit: Number of runs to analyze

    Returns:
        DAG statistics
    """
    result = await _fetch_dag_runs(dag_id, limit=limit)
    runs = result["dag_runs"]

    total_runs = len(runs)
    success_runs = sum(1 for r in runs if r.get("state") == "success")
    failed_runs = sum(1 for r in runs if r.get("state") == "failed")
    running_runs = sum(1 for r in runs if r.get("state") == "running")
    queued_runs = sum(1 for r in runs if r.get("state") == "queued")

    success_rate = (success_runs / total_runs * 100) if total_runs > 0 else 0.0

    completed_runs = [r for r in runs if r.get("start_date") and r.get("end_date")]
    avg_duration = None
    if completed_runs:
        durations = []
        for run in completed_runs:
            try:
                start = datetime.fromisoformat(run["start_date"].replace('Z', '+00:00'))
                end = datetime.fromisoformat(run["end_date"].replace('Z', '+00:00'))
                duration = (end - start).total_seconds()
                durations.append(duration)
            except:
                pass
        avg_duration = sum(durations) / len(durations) if durations else None

    return DagStats(
        dag_id=dag_id,
        total_runs=total_runs,
        success_runs=success_runs,
        failed_runs=failed_runs,
        running_runs=running_runs,
        queued_runs=queued_runs,
        success_rate=round(success_rate, 2),
        avg_duration=avg_duration
    )


@router.get("/airflow/stats", response_model=AirflowStats)
async def get_airflow_stats():
    """
    Get Airflow statistics

    Returns:
        Overall statistics (DAG count, run success rate, etc.)
    """
    dags_result = await list_dags(limit=1000)
    dags = dags_result["dags"]

    active_dags = sum(1 for dag in dags if dag.get("is_active", True))
    paused_dags = sum(1 for dag in dags if dag.get("is_paused", False))

    runs_result = await list_all_dag_runs(limit=1000)
    runs = runs_result["dag_runs"]

    queued_runs = sum(1 for run in runs if run.get("state") == "queued")
    running_runs = sum(1 for run in runs if run.get("state") == "running")
    success_runs = sum(1 for run in runs if run.get("state") == "success")
    failed_runs = sum(1 for run in runs if run.get("state") == "failed")

    return AirflowStats(
        total_dags=len(dags),
        active_dags=active_dags,
        paused_dags=paused_dags,
        total_dag_runs=len(runs),
        queued_dag_runs=queued_runs,
        running_dag_runs=running_runs,
        success_dag_runs=success_runs,
        failed_dag_runs=failed_runs
    )


@router.get("/airflow/health", response_model=AirflowHealth)
async def airflow_health():
    """
    Check Airflow API health

    Returns:
        Airflow health status and version info
    """
    try:
        data = await airflow_request("GET", "/health")
        return AirflowHealth(
            status="healthy" if data.get("metadatabase", {}).get("status") == "healthy" else "unhealthy",
            version=data.get("version"),
            metadatabase=data.get("metadatabase"),
            scheduler=data.get("scheduler")
        )
    except HTTPException:
        return AirflowHealth(status="unavailable")
    except Exception:
        return AirflowHealth(status="unhealthy")


@router.get("/airflow/version")
async def get_airflow_version():
    """
    Get Airflow version info

    Returns:
        Version information
    """
    try:
        data = await airflow_request("GET", "/version")
        return {
            "version": data.get("version"),
            "git_version": data.get("git_version")
        }
    except:
        return {"version": "unknown", "git_version": "unknown"}
