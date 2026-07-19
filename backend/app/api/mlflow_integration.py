"""
MLflow API Integration - Complete experiment tracking and model registry API
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
import asyncio
from datetime import datetime

# MLflow client (lazy import to handle missing dependency gracefully)
try:
    from mlflow.tracking import MlflowClient
    from mlflow.entities import ViewType
    from mlflow.exceptions import MlflowException
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

router = APIRouter()

# Configuration
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.datapond.svc.cluster.local:5000")
REQUEST_TIMEOUT = 30  # seconds


# ============================================================================
# Pydantic Models
# ============================================================================

class ExperimentInfo(BaseModel):
    experiment_id: str
    name: str
    lifecycle_stage: str
    artifact_location: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    creation_time: Optional[int] = None
    last_update_time: Optional[int] = None


class ExperimentCreateRequest(BaseModel):
    name: str
    artifact_location: Optional[str] = None
    tags: Optional[Dict[str, str]] = None


class RunInfo(BaseModel):
    run_id: str
    run_name: Optional[str] = None
    experiment_id: str
    status: str
    start_time: int
    end_time: Optional[int] = None
    artifact_uri: Optional[str] = None
    lifecycle_stage: str
    user_id: Optional[str] = None


class MetricValue(BaseModel):
    key: str
    value: float
    timestamp: int
    step: int


class ParamValue(BaseModel):
    key: str
    value: str


class RunTag(BaseModel):
    key: str
    value: str


class RunData(BaseModel):
    metrics: List[MetricValue] = []
    params: List[ParamValue] = []
    tags: List[RunTag] = []


class RunDetails(BaseModel):
    info: RunInfo
    data: RunData


class MetricHistory(BaseModel):
    key: str
    values: List[Dict[str, Any]]  # [{timestamp, step, value}]


class ArtifactInfo(BaseModel):
    path: str
    is_dir: bool
    file_size: Optional[int] = None


class SearchRunsRequest(BaseModel):
    experiment_ids: Optional[List[str]] = None
    filter_string: Optional[str] = ""
    run_view_type: str = "ACTIVE_ONLY"  # ACTIVE_ONLY, DELETED_ONLY, ALL
    max_results: int = 100
    order_by: Optional[List[str]] = None


class CompareRunsRequest(BaseModel):
    run_ids: List[str] = Field(..., min_items=2, description="List of run IDs to compare")


class CompareRunsResponse(BaseModel):
    runs: List[RunDetails]
    common_params: List[str]
    common_metrics: List[str]
    diff_params: List[str]
    diff_metrics: List[str]


class ModelVersion(BaseModel):
    name: str
    version: str
    creation_timestamp: int
    last_updated_timestamp: Optional[int] = None
    description: Optional[str] = None
    user_id: Optional[str] = None
    current_stage: str  # None, Staging, Production, Archived
    source: Optional[str] = None
    run_id: Optional[str] = None
    status: str
    status_message: Optional[str] = None
    tags: Optional[Dict[str, str]] = None


class RegisteredModel(BaseModel):
    name: str
    creation_timestamp: int
    last_updated_timestamp: Optional[int] = None
    description: Optional[str] = None
    latest_versions: List[ModelVersion] = []
    tags: Optional[Dict[str, str]] = None


class ModelTransitionRequest(BaseModel):
    stage: str = Field(..., description="Target stage: Staging, Production, or Archived")
    archive_existing_versions: bool = False


# ============================================================================
# Helper Functions
# ============================================================================

def get_mlflow_client() -> MlflowClient:
    """Get MLflow client instance"""
    if not MLFLOW_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="MLflow client not available. Install mlflow package."
        )

    try:
        return MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to MLflow: {str(e)}"
        )


def run_to_dict(run) -> RunDetails:
    """Convert MLflow Run entity to RunDetails model"""
    return RunDetails(
        info=RunInfo(
            run_id=run.info.run_id,
            run_name=run.data.tags.get("mlflow.runName"),
            experiment_id=run.info.experiment_id,
            status=run.info.status,
            start_time=run.info.start_time,
            end_time=run.info.end_time,
            artifact_uri=run.info.artifact_uri,
            lifecycle_stage=run.info.lifecycle_stage,
            user_id=run.info.user_id
        ),
        data=RunData(
            metrics=[
                MetricValue(key=k, value=v, timestamp=0, step=0)
                for k, v in (run.data.metrics or {}).items()
            ],
            params=[
                ParamValue(key=k, value=v)
                for k, v in run.data.params.items()
            ],
            tags=[
                RunTag(key=k, value=v)
                for k, v in run.data.tags.items()
            ]
        )
    )


# ============================================================================
# Experiment Endpoints
# ============================================================================

@router.get("/mlflow/experiments", response_model=List[ExperimentInfo])
async def list_experiments():
    """
    List all experiments from MLflow

    Returns:
        List of experiments with metadata
    """
    try:
        client = get_mlflow_client()
        # MLflow 클라이언트는 동기(HTTP) — 이벤트루프 블로킹 방지
        experiments = await asyncio.to_thread(
            client.search_experiments, view_type=ViewType.ACTIVE_ONLY
        )

        return [
            ExperimentInfo(
                experiment_id=exp.experiment_id,
                name=exp.name,
                lifecycle_stage=exp.lifecycle_stage,
                artifact_location=exp.artifact_location,
                tags=exp.tags if exp.tags else {},
                creation_time=exp.creation_time if hasattr(exp, 'creation_time') else None,
                last_update_time=exp.last_update_time if hasattr(exp, 'last_update_time') else None
            )
            for exp in experiments
        ]

    except MlflowException as e:
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/mlflow/experiments", response_model=ExperimentInfo)
async def create_experiment(request: ExperimentCreateRequest):
    """
    Create a new experiment

    Args:
        request: Experiment creation parameters

    Returns:
        Created experiment info
    """
    try:
        client = get_mlflow_client()

        experiment_id = client.create_experiment(
            name=request.name,
            artifact_location=request.artifact_location,
            tags=request.tags
        )

        # Get the created experiment
        experiment = client.get_experiment(experiment_id)

        return ExperimentInfo(
            experiment_id=experiment.experiment_id,
            name=experiment.name,
            lifecycle_stage=experiment.lifecycle_stage,
            artifact_location=experiment.artifact_location,
            tags=experiment.tags if experiment.tags else {},
            creation_time=experiment.creation_time if hasattr(experiment, 'creation_time') else None,
            last_update_time=experiment.last_update_time if hasattr(experiment, 'last_update_time') else None
        )

    except MlflowException as e:
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Experiment '{request.name}' already exists")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/mlflow/experiments/{experiment_id}", response_model=ExperimentInfo)
async def get_experiment(experiment_id: str):
    """
    Get experiment details by ID

    Args:
        experiment_id: Experiment ID

    Returns:
        Experiment details
    """
    try:
        client = get_mlflow_client()
        experiment = client.get_experiment(experiment_id)

        if experiment is None:
            raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")

        return ExperimentInfo(
            experiment_id=experiment.experiment_id,
            name=experiment.name,
            lifecycle_stage=experiment.lifecycle_stage,
            artifact_location=experiment.artifact_location,
            tags=experiment.tags if experiment.tags else {},
            creation_time=experiment.creation_time if hasattr(experiment, 'creation_time') else None,
            last_update_time=experiment.last_update_time if hasattr(experiment, 'last_update_time') else None
        )

    except MlflowException as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


async def _archive_experiment(experiment_id: str):
    """Archive an MLflow experiment using MLflow's delete lifecycle operation."""
    try:
        client = get_mlflow_client()
        await asyncio.to_thread(client.delete_experiment, experiment_id)
        return {
            "experiment_id": experiment_id,
            "lifecycle_stage": "deleted",
            "archived": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        message = str(e)
        if "does not exist" in message.lower() or "not found" in message.lower():
            raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
        raise HTTPException(
            status_code=502,
            detail=f"MLflow failed to archive experiment {experiment_id}: {message}",
        )


@router.delete("/mlflow/experiments/{experiment_id}")
async def delete_experiment(experiment_id: str):
    """Archive an experiment; MLflow deletion is a reversible lifecycle change."""
    return await _archive_experiment(experiment_id)


@router.post("/mlflow/experiments/{experiment_id}/archive")
async def archive_experiment(experiment_id: str):
    """Explicit archive alias used by the DataPond frontend proxy."""
    return await _archive_experiment(experiment_id)


@router.get("/mlflow/experiments/{experiment_id}/runs", response_model=List[RunDetails])
async def list_experiment_runs(
    experiment_id: str,
    max_results: int = Query(100, ge=1, le=1000, description="Maximum number of runs to return")
):
    """
    List all runs for a specific experiment

    Args:
        experiment_id: Experiment ID
        max_results: Maximum number of runs to return

    Returns:
        List of runs with metrics and parameters
    """
    try:
        client = get_mlflow_client()
        runs = await asyncio.to_thread(
            client.search_runs,
            experiment_ids=[experiment_id],
            max_results=max_results,
            order_by=["start_time DESC"],
        )

        return [run_to_dict(run) for run in runs]

    except MlflowException as e:
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# ============================================================================
# Run Endpoints
# ============================================================================

@router.get("/mlflow/runs/{run_id}", response_model=RunDetails)
async def get_run(run_id: str):
    """
    Get run details by ID

    Args:
        run_id: Run ID

    Returns:
        Run details with metrics, parameters, and tags
    """
    try:
        client = get_mlflow_client()
        run = client.get_run(run_id)

        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        return run_to_dict(run)

    except MlflowException as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/mlflow/runs/{run_id}/metrics", response_model=List[MetricHistory])
async def get_run_metrics(run_id: str):
    """
    Get metric history for a run

    Args:
        run_id: Run ID

    Returns:
        List of metrics with full history (all logged values)
    """
    try:
        client = get_mlflow_client()
        run = client.get_run(run_id)

        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Get metric history for each metric
        metric_histories = []
        for metric_key in run.data.metrics.keys():
            history = client.get_metric_history(run_id, metric_key)

            metric_histories.append(MetricHistory(
                key=metric_key,
                values=[
                    {
                        "timestamp": metric.timestamp,
                        "step": metric.step,
                        "value": metric.value
                    }
                    for metric in history
                ]
            ))

        return metric_histories

    except MlflowException as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/mlflow/runs/{run_id}/artifacts", response_model=List[ArtifactInfo])
async def list_run_artifacts(run_id: str, path: str = ""):
    """
    List artifacts for a run

    Args:
        run_id: Run ID
        path: Artifact path (relative to run's artifact root)

    Returns:
        List of artifacts in the specified path
    """
    try:
        client = get_mlflow_client()
        artifacts = client.list_artifacts(run_id, path)

        return [
            ArtifactInfo(
                path=artifact.path,
                is_dir=artifact.is_dir,
                file_size=artifact.file_size if not artifact.is_dir else None
            )
            for artifact in artifacts
        ]

    except MlflowException as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# ============================================================================
# Search & Compare Endpoints
# ============================================================================

@router.post("/mlflow/search", response_model=List[RunDetails])
async def search_runs(request: SearchRunsRequest):
    """
    Search runs with filters

    Args:
        request: Search parameters (experiment IDs, filters, ordering)

    Returns:
        List of matching runs

    Example filter_string:
        - "metrics.accuracy > 0.9"
        - "params.model = 'RandomForest'"
        - "tags.team = 'ml-platform'"
    """
    try:
        client = get_mlflow_client()

        # Convert run_view_type string to ViewType enum
        view_type_map = {
            "ACTIVE_ONLY": ViewType.ACTIVE_ONLY,
            "DELETED_ONLY": ViewType.DELETED_ONLY,
            "ALL": ViewType.ALL
        }
        view_type = view_type_map.get(request.run_view_type, ViewType.ACTIVE_ONLY)

        runs = client.search_runs(
            experiment_ids=request.experiment_ids,
            filter_string=request.filter_string,
            run_view_type=view_type,
            max_results=request.max_results,
            order_by=request.order_by
        )

        return [run_to_dict(run) for run in runs]

    except MlflowException as e:
        if "invalid" in str(e).lower():
            raise HTTPException(status_code=400, detail=f"Invalid search query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/mlflow/runs/compare", response_model=CompareRunsResponse)
async def compare_runs(request: CompareRunsRequest):
    """
    Compare multiple runs side-by-side

    Args:
        request: List of run IDs to compare

    Returns:
        Comparison data highlighting differences and commonalities
    """
    try:
        client = get_mlflow_client()

        # Fetch all runs
        runs = []
        for run_id in request.run_ids:
            try:
                run = client.get_run(run_id)
                runs.append(run)
            except MlflowException:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Analyze common and different params/metrics
        all_params = [set(run.data.params.keys()) for run in runs]
        all_metrics = [set(run.data.metrics.keys()) for run in runs]

        common_params = list(set.intersection(*all_params)) if all_params else []
        common_metrics = list(set.intersection(*all_metrics)) if all_metrics else []

        all_params_union = set.union(*all_params) if all_params else set()
        all_metrics_union = set.union(*all_metrics) if all_metrics else set()

        diff_params = list(all_params_union - set(common_params))
        diff_metrics = list(all_metrics_union - set(common_metrics))

        return CompareRunsResponse(
            runs=[run_to_dict(run) for run in runs],
            common_params=sorted(common_params),
            common_metrics=sorted(common_metrics),
            diff_params=sorted(diff_params),
            diff_metrics=sorted(diff_metrics)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# ============================================================================
# Model Registry Endpoints
# ============================================================================

@router.get("/mlflow/models", response_model=List[RegisteredModel])
async def list_registered_models(max_results: int = Query(100, ge=1, le=1000)):
    """
    List all registered models

    Args:
        max_results: Maximum number of models to return

    Returns:
        List of registered models with latest versions
    """
    try:
        client = get_mlflow_client()
        models = client.search_registered_models(max_results=max_results)

        return [
            RegisteredModel(
                name=model.name,
                creation_timestamp=model.creation_timestamp,
                last_updated_timestamp=model.last_updated_timestamp,
                description=model.description,
                latest_versions=[
                    ModelVersion(
                        name=version.name,
                        version=version.version,
                        creation_timestamp=version.creation_timestamp,
                        last_updated_timestamp=version.last_updated_timestamp,
                        description=version.description,
                        user_id=version.user_id,
                        current_stage=version.current_stage,
                        source=version.source,
                        run_id=version.run_id,
                        status=version.status,
                        status_message=version.status_message,
                        tags=version.tags if version.tags else {}
                    )
                    for version in model.latest_versions
                ],
                tags=model.tags if model.tags else {}
            )
            for model in models
        ]

    except MlflowException as e:
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/mlflow/models/{name}", response_model=RegisteredModel)
async def get_registered_model(name: str):
    """
    Get registered model details by name

    Args:
        name: Model name

    Returns:
        Model details with all versions
    """
    try:
        client = get_mlflow_client()
        model = client.get_registered_model(name)

        return RegisteredModel(
            name=model.name,
            creation_timestamp=model.creation_timestamp,
            last_updated_timestamp=model.last_updated_timestamp,
            description=model.description,
            latest_versions=[
                ModelVersion(
                    name=version.name,
                    version=version.version,
                    creation_timestamp=version.creation_timestamp,
                    last_updated_timestamp=version.last_updated_timestamp,
                    description=version.description,
                    user_id=version.user_id,
                    current_stage=version.current_stage,
                    source=version.source,
                    run_id=version.run_id,
                    status=version.status,
                    status_message=version.status_message,
                    tags=version.tags if version.tags else {}
                )
                for version in model.latest_versions
            ],
            tags=model.tags if model.tags else {}
        )

    except MlflowException as e:
        if "does not exist" in str(e).lower() or "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Model '{name}' not found")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/mlflow/models/{name}/versions", response_model=List[ModelVersion])
async def list_model_versions(name: str):
    """
    List all versions of a registered model

    Args:
        name: Model name

    Returns:
        List of model versions
    """
    try:
        client = get_mlflow_client()
        versions = client.search_model_versions(f"name='{name}'")

        return [
            ModelVersion(
                name=version.name,
                version=version.version,
                creation_timestamp=version.creation_timestamp,
                last_updated_timestamp=version.last_updated_timestamp,
                description=version.description,
                user_id=version.user_id,
                current_stage=version.current_stage,
                source=version.source,
                run_id=version.run_id,
                status=version.status,
                status_message=version.status_message,
                tags=version.tags if version.tags else {}
            )
            for version in versions
        ]

    except MlflowException as e:
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/mlflow/models/{name}/versions/{version}/transition")
async def transition_model_version_stage(
    name: str,
    version: str,
    request: ModelTransitionRequest
):
    """
    Transition model version to a new stage

    Args:
        name: Model name
        version: Model version
        request: Transition parameters (stage, archive_existing_versions)

    Returns:
        Updated model version

    Stages: None, Staging, Production, Archived
    """
    try:
        client = get_mlflow_client()

        # Validate stage
        valid_stages = ["None", "Staging", "Production", "Archived"]
        if request.stage not in valid_stages:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage '{request.stage}'. Must be one of: {', '.join(valid_stages)}"
            )

        # Transition model version
        model_version = client.transition_model_version_stage(
            name=name,
            version=version,
            stage=request.stage,
            archive_existing_versions=request.archive_existing_versions
        )

        return ModelVersion(
            name=model_version.name,
            version=model_version.version,
            creation_timestamp=model_version.creation_timestamp,
            last_updated_timestamp=model_version.last_updated_timestamp,
            description=model_version.description,
            user_id=model_version.user_id,
            current_stage=model_version.current_stage,
            source=model_version.source,
            run_id=model_version.run_id,
            status=model_version.status,
            status_message=model_version.status_message,
            tags=model_version.tags if model_version.tags else {}
        )

    except MlflowException as e:
        if "does not exist" in str(e).lower() or "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Model version '{name}/{version}' not found")
        raise HTTPException(status_code=500, detail=f"MLflow error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


# ============================================================================
# Query Lab Bridge — log SQL query results directly to MLflow
# ============================================================================

class LogQueryRequest(BaseModel):
    experiment_id: str
    run_name: Optional[str] = None
    query_text: str
    row_count: int
    execution_time_ms: float
    columns: List[str]
    params: Optional[Dict[str, str]] = None   # user-defined key/value params
    metrics: Optional[Dict[str, float]] = None  # user-defined key/value metrics
    tags: Optional[Dict[str, str]] = None


class LogQueryResponse(BaseModel):
    run_id: str
    experiment_id: str
    run_name: str
    mlflow_url: str


@router.post("/mlflow/log-query", response_model=LogQueryResponse)
async def log_query_to_mlflow(request: LogQueryRequest):
    """
    Create an MLflow run from a SQL query execution.
    Called from Query Lab to log queries, results, and metadata.
    """
    client = get_mlflow_client()
    try:
        run_name = request.run_name or f"query_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        run = client.create_run(
            experiment_id=request.experiment_id,
            run_name=run_name,
            tags={
                "source": "query_lab",
                "query_text": request.query_text[:500],  # MLflow tag max 5000 chars
                "columns": ",".join(request.columns[:20]),
                **(request.tags or {})
            }
        )
        run_id = run.info.run_id

        # Log built-in metrics
        client.log_metric(run_id, "row_count", request.row_count)
        client.log_metric(run_id, "execution_time_ms", request.execution_time_ms)
        client.log_metric(run_id, "column_count", len(request.columns))

        # Log user-defined metrics
        for k, v in (request.metrics or {}).items():
            client.log_metric(run_id, k, v)

        # Log user-defined params
        client.log_param(run_id, "query", request.query_text[:500])
        for k, v in (request.params or {}).items():
            client.log_param(run_id, k, str(v))

        client.set_terminated(run_id, status="FINISHED")

        # 상대경로 — 브라우저가 현재 호스트 기준으로 해석(도메인 무관). 프론트는 href로 직접 사용.
        mlflow_url = f"/mlflow/#/experiments/{request.experiment_id}/runs/{run_id}"

        return LogQueryResponse(
            run_id=run_id,
            experiment_id=request.experiment_id,
            run_name=run_name,
            mlflow_url=mlflow_url
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log query: {str(e)}")


@router.post("/mlflow/experiments", response_model=ExperimentInfo)
async def create_experiment_alias(request: ExperimentCreateRequest):
    """Create a new MLflow experiment (alias for /mlflow/experiments POST)"""
    client = get_mlflow_client()
    try:
        experiment_id = client.create_experiment(
            name=request.name,
            artifact_location=request.artifact_location,
            tags=request.tags
        )
        experiment = client.get_experiment(experiment_id)
        return ExperimentInfo(
            experiment_id=experiment.experiment_id,
            name=experiment.name,
            lifecycle_stage=experiment.lifecycle_stage,
            artifact_location=experiment.artifact_location,
            tags=dict(experiment.tags) if experiment.tags else {},
            creation_time=experiment.creation_time,
            last_update_time=experiment.last_update_time
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create experiment: {str(e)}")


# ============================================================================
# Health Check
# ============================================================================

@router.get("/mlflow/health")
async def mlflow_health():
    """Check MLflow service health"""
    try:
        client = get_mlflow_client()
        # Try to list experiments as a health check
        experiments = client.search_experiments(max_results=1)

        return {
            "service": "mlflow",
            "status": "healthy",
            "tracking_uri": MLFLOW_TRACKING_URI,
            "experiment_count": len(experiments) if experiments else 0
        }
    except HTTPException as e:
        return {
            "service": "mlflow",
            "status": "unavailable",
            "tracking_uri": MLFLOW_TRACKING_URI,
            "error": e.detail
        }
    except Exception as e:
        return {
            "service": "mlflow",
            "status": "unhealthy",
            "tracking_uri": MLFLOW_TRACKING_URI,
            "error": str(e)
        }
