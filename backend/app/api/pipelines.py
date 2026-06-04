"""
REST API for declarative pipeline management.
Provides endpoints for validation, compilation, and deployment.
"""
from fastapi import APIRouter, HTTPException, File, UploadFile, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
import tempfile
import os
import base64
import httpx
from pathlib import Path

from app.pipelines.compiler import PipelineCompiler
from app.pipelines.models import CompilationResult
from app.pipelines.dependency_graph import DependencyGraphBuilder
from app.database.connection import get_db, engine, Base
from app.models.pipeline import SavedPipeline

router = APIRouter()

# Ensure pipelines table exists
Base.metadata.create_all(bind=engine, tables=[SavedPipeline.__table__], checkfirst=True)


# === Request/Response Models ===

class PipelineValidateRequest(BaseModel):
    """Request to validate a pipeline"""
    code: str = Field(..., description="Pipeline Python code")
    filename: Optional[str] = Field("pipeline.py", description="Filename for error messages")


class PipelineCompileRequest(BaseModel):
    """Request to compile a pipeline"""
    code: str = Field(..., description="Pipeline Python code")
    filename: Optional[str] = Field("pipeline.py", description="Source filename")


class PipelineDeployRequest(BaseModel):
    """Request to deploy a compiled pipeline"""
    pipeline_name: str = Field(..., description="Pipeline name")
    dag_code: str = Field(None, description="Generated Airflow DAG code (optional if deploying from saved)")
    overwrite: bool = Field(False, description="Overwrite existing pipeline")


class PipelineSaveRequest(BaseModel):
    """Request to save a pipeline definition"""
    name: str = Field(..., description="Pipeline name")
    description: Optional[str] = None
    schedule: Optional[str] = None
    code: str = Field(..., description="Generated Python DSL code")
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Validation result response"""
    success: bool
    pipeline_name: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    dependency_graph: Optional[Dict[str, Any]] = None
    execution_batches: Optional[List[List[str]]] = None


class CompilationResultResponse(BaseModel):
    """Compilation result response"""
    success: bool
    pipeline_name: str
    artifacts: List[Dict[str, str]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    compiled_at: datetime
    dependency_graph: Optional[Dict[str, Any]] = None


class PipelineInfo(BaseModel):
    """Pipeline information"""
    name: str
    status: str
    schedule: Optional[str] = None
    owner: Optional[str] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None


class PipelineListResponse(BaseModel):
    """List of pipelines"""
    pipelines: List[PipelineInfo]
    total: int


# === Endpoints ===

@router.post("/pipelines/save")
async def save_pipeline(request: PipelineSaveRequest, db: Session = Depends(get_db)):
    """Save or update a pipeline definition (draft state)."""
    existing = db.query(SavedPipeline).filter(SavedPipeline.name == request.name).first()
    if existing:
        existing.description = request.description
        existing.schedule = request.schedule
        existing.code = request.code
        existing.nodes_json = request.nodes
        existing.edges_json = request.edges
        existing.config_json = request.config
        existing.updated_at = datetime.utcnow()
        # Keep status as-is if already deployed, otherwise draft
    else:
        existing = SavedPipeline(
            name=request.name,
            description=request.description,
            schedule=request.schedule,
            status="draft",
            code=request.code,
            nodes_json=request.nodes,
            edges_json=request.edges,
            config_json=request.config,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return {"success": True, "id": str(existing.id), "name": existing.name, "status": existing.status}


@router.post("/pipelines/validate", response_model=ValidationResult)
async def validate_pipeline(request: PipelineValidateRequest):
    """
    Validate a pipeline definition without compiling.

    Checks:
    - Syntax errors
    - Circular dependencies
    - Missing references
    - Quality check validity
    """
    try:
        # Write code to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(request.code)
            temp_file = f.name

        try:
            # Validate
            compiler = PipelineCompiler()
            result = compiler.validate_only(temp_file)

            # Build response
            response = ValidationResult(
                success=result.success,
                pipeline_name=result.pipeline_name,
                errors=result.validation_errors,
                warnings=result.warnings
            )

            # Add dependency graph visualization
            if result.dependency_graph:
                graph_data = {
                    "nodes": [
                        {
                            "name": name,
                            "type": node.type,
                            "dependencies": node.dependencies,
                            "dependents": node.dependents
                        }
                        for name, node in result.dependency_graph.nodes.items()
                    ],
                    "edges": result.dependency_graph.edges
                }
                response.dependency_graph = graph_data

                # Add execution batches
                batches = DependencyGraphBuilder.get_execution_order(result.dependency_graph)
                response.execution_batches = batches

            return response

        finally:
            # Clean up temp file
            Path(temp_file).unlink(missing_ok=True)

    except Exception as e:
        return ValidationResult(
            success=False,
            errors=[f"Validation error: {str(e)}"]
        )


@router.post("/pipelines/compile", response_model=CompilationResultResponse)
async def compile_pipeline(request: PipelineCompileRequest):
    """
    Compile a pipeline definition to Airflow DAG.

    Returns:
    - Generated DAG code
    - Dependency graph
    - Validation warnings/errors
    """
    try:
        # Write code to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(request.code)
            temp_file = f.name

        try:
            # Compile
            compiler = PipelineCompiler()
            result = compiler.compile_file(temp_file)

            # Build response
            artifacts = [
                {"type": artifact_type, "content": content}
                for artifact_type, content in result.artifacts
            ]

            response = CompilationResultResponse(
                success=result.success,
                pipeline_name=result.pipeline_name,
                artifacts=artifacts,
                errors=result.validation_errors,
                warnings=result.warnings,
                compiled_at=result.compiled_at
            )

            # Add dependency graph
            if result.dependency_graph:
                graph_data = {
                    "nodes": [
                        {
                            "name": name,
                            "type": node.type,
                            "dependencies": node.dependencies,
                            "dependents": node.dependents
                        }
                        for name, node in result.dependency_graph.nodes.items()
                    ],
                    "edges": result.dependency_graph.edges
                }
                response.dependency_graph = graph_data

            return response

        finally:
            # Clean up temp file
            Path(temp_file).unlink(missing_ok=True)

    except Exception as e:
        return CompilationResultResponse(
            success=False,
            pipeline_name="unknown",
            errors=[f"Compilation error: {str(e)}"],
            compiled_at=datetime.utcnow()
        )


@router.post("/pipelines/deploy")
async def deploy_pipeline(request: PipelineDeployRequest, db: Session = Depends(get_db)):
    """
    Deploy a pipeline to Airflow.
    If dag_code provided, uses it directly. Otherwise compiles from saved pipeline.
    """
    DAGS_PATH = Path(os.getenv("AIRFLOW_DAGS_PATH", "/opt/airflow/dags"))
    AIRFLOW_API = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver.datapond.svc.cluster.local:8080/api/v1")
    AIRFLOW_AUTH = (os.getenv("AIRFLOW_USERNAME", "airflow"), os.getenv("AIRFLOW_PASSWORD", "airflow"))

    dag_code = request.dag_code

    # If no dag_code, compile from saved pipeline
    if not dag_code:
        saved = db.query(SavedPipeline).filter(SavedPipeline.name == request.pipeline_name).first()
        if not saved:
            raise HTTPException(404, f"Pipeline '{request.pipeline_name}' not found. Save it first.")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(saved.code)
            temp_file = f.name
        try:
            compiler = PipelineCompiler()
            result = compiler.compile_file(temp_file)
            if not result.success:
                raise HTTPException(400, f"Compilation failed: {'; '.join(result.validation_errors)}")
            dag_code = next((c for t, c in result.artifacts if t == "airflow_dag"), None)
            if not dag_code:
                raise HTTPException(500, "No DAG artifact generated")
        finally:
            Path(temp_file).unlink(missing_ok=True)

    dag_filename = f"datapond_{request.pipeline_name}.py"
    dag_path = DAGS_PATH / dag_filename

    if dag_path.exists() and not request.overwrite:
        raise HTTPException(409, f"Pipeline '{request.pipeline_name}' already exists. Set overwrite=true.")

    try:
        DAGS_PATH.mkdir(parents=True, exist_ok=True)
        dag_path.write_text(dag_code, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Failed to write DAG file: {e}")

    # Update DB status
    saved = db.query(SavedPipeline).filter(SavedPipeline.name == request.pipeline_name).first()
    if saved:
        saved.status = "deployed"
        saved.dag_id = f"datapond_{request.pipeline_name}"
        saved.updated_at = datetime.utcnow()
        db.commit()

    # Unpause in Airflow
    airflow_dag_id = f"datapond_{request.pipeline_name}"
    refreshed = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.patch(f"{AIRFLOW_API}/dags/{airflow_dag_id}", auth=AIRFLOW_AUTH, json={"is_paused": False})
            refreshed = True
    except Exception:
        pass

    return {
        "success": True,
        "pipeline_name": request.pipeline_name,
        "dag_id": airflow_dag_id,
        "dag_file": dag_filename,
        "message": "Pipeline deployed. Airflow will pick it up within 30 seconds.",
        "airflow_refreshed": refreshed,
    }


class PipelineUpdateRequest(BaseModel):
    """Request to update pipeline metadata"""
    description: Optional[str] = None
    is_paused: Optional[bool] = None
    tags: Optional[List[str]] = None


# Airflow API config (shared with airflow.py)
AIRFLOW_API = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver.datapond.svc.cluster.local:8080/api/v1")
AIRFLOW_AUTH = (os.getenv("AIRFLOW_USERNAME", "airflow"), os.getenv("AIRFLOW_PASSWORD", "airflow"))
DAGS_PATH = Path(os.getenv("AIRFLOW_DAGS_PATH", "/opt/airflow/dags"))


async def _airflow_request(method: str, path: str, **kwargs) -> httpx.Response:
    """Helper for Airflow API calls."""
    async with httpx.AsyncClient(timeout=15) as client:
        return await getattr(client, method)(
            f"{AIRFLOW_API}{path}", auth=AIRFLOW_AUTH, **kwargs
        )


@router.get("/pipelines", response_model=PipelineListResponse)
async def list_pipelines(db: Session = Depends(get_db)):
    """List all saved pipelines from DB."""
    rows = db.query(SavedPipeline).order_by(SavedPipeline.updated_at.desc()).all()
    pipelines = [
        PipelineInfo(
            name=r.name,
            status=r.status,
            schedule=r.schedule,
            owner=r.config_json.get("advanced", {}).get("owner") if r.config_json else None,
            last_run=None,
            next_run=None,
        )
        for r in rows
    ]
    return PipelineListResponse(pipelines=pipelines, total=len(pipelines))


@router.get("/pipelines/{pipeline_name}")
async def get_pipeline(pipeline_name: str, db: Session = Depends(get_db)):
    """Get detailed information about a saved pipeline."""
    saved = db.query(SavedPipeline).filter(SavedPipeline.name == pipeline_name).first()
    if not saved:
        raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")
    return {
        "id": str(saved.id),
        "name": saved.name,
        "description": saved.description,
        "schedule": saved.schedule,
        "status": saved.status,
        "code": saved.code,
        "nodes": saved.nodes_json,
        "edges": saved.edges_json,
        "config": saved.config_json,
        "dag_id": saved.dag_id,
        "created_at": saved.created_at.isoformat() if saved.created_at else None,
        "updated_at": saved.updated_at.isoformat() if saved.updated_at else None,
    }


@router.put("/pipelines/{pipeline_name}")
async def update_pipeline(pipeline_name: str, request: PipelineUpdateRequest):
    """Update pipeline metadata (pause/unpause, description, tags)."""
    dag_id = pipeline_name if pipeline_name.startswith("datapond_") else f"datapond_{pipeline_name}"
    body: Dict[str, Any] = {}
    if request.is_paused is not None:
        body["is_paused"] = request.is_paused
    if not body:
        raise HTTPException(400, "No updatable fields provided")

    try:
        resp = await _airflow_request("patch", f"/dags/{dag_id}", json=body)
        if resp.status_code == 404:
            raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")
        if resp.status_code not in (200, 204):
            raise HTTPException(502, f"Airflow update failed: {resp.text}")
        return {"success": True, "dag_id": dag_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Airflow connection error: {e}")


@router.get("/pipelines/{pipeline_name}/runs")
async def get_pipeline_runs(pipeline_name: str, limit: int = 10):
    """Get execution history for a pipeline."""
    dag_id = pipeline_name if pipeline_name.startswith("datapond_") else f"datapond_{pipeline_name}"
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


@router.post("/pipelines/{pipeline_name}/trigger")
async def trigger_pipeline(pipeline_name: str):
    """Manually trigger a pipeline run."""
    dag_id = pipeline_name if pipeline_name.startswith("datapond_") else f"datapond_{pipeline_name}"
    try:
        resp = await _airflow_request("post", f"/dags/{dag_id}/dagRuns", json={"conf": {}})
        if resp.status_code == 404:
            raise HTTPException(404, f"Pipeline '{pipeline_name}' not found")
        if resp.status_code not in (200, 201):
            raise HTTPException(502, f"Failed to trigger: {resp.text}")
        return {"success": True, "dag_id": dag_id, "run": resp.json()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Airflow connection error: {e}")


@router.delete("/pipelines/{pipeline_name}")
async def delete_pipeline(pipeline_name: str):
    """Delete a pipeline: remove DAG file and pause in Airflow."""
    dag_id = pipeline_name if pipeline_name.startswith("datapond_") else f"datapond_{pipeline_name}"

    # Remove DAG file
    dag_file = DAGS_PATH / f"{dag_id}.py"
    file_removed = False
    if dag_file.exists():
        dag_file.unlink()
        file_removed = True

    # Pause and delete via Airflow API
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


OPENMETADATA_URL = os.getenv("OPENMETADATA_URL", "http://openmetadata-server.datapond.svc.cluster.local:8585")
_om_token_cache: str | None = None


async def _get_om_token() -> str | None:
    global _om_token_cache
    if _om_token_cache:
        return _om_token_cache
    # OM (>=1.x) requires the basic-auth password Base-64 encoded on /users/login.
    email = os.getenv("OPENMETADATA_EMAIL", "admin@open-metadata.org")
    pw_b64 = base64.b64encode(os.getenv("OPENMETADATA_PASSWORD", "admin").encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(f"{OPENMETADATA_URL}/api/v1/users/login",
                             json={"email": email, "password": pw_b64})
            if r.status_code == 200:
                _om_token_cache = r.json().get("accessToken")
                return _om_token_cache
    except Exception:
        pass
    return None


@router.get("/pipelines/{pipeline_name}/lineage")
async def get_pipeline_lineage(pipeline_name: str):
    """Get lineage graph for a pipeline from OpenMetadata."""
    token = await _get_om_token()
    empty = {"pipeline_name": pipeline_name, "lineage": {"nodes": [], "edges": []}}
    if not token:
        return empty
    try:
        fqn = f"datapond.{pipeline_name}"
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                f"{OPENMETADATA_URL}/api/v1/lineage/pipeline/name/{fqn}",
                headers={"Authorization": f"Bearer {token}"},
                params={"upstreamDepth": 2, "downstreamDepth": 2},
            )
        if r.status_code != 200:
            return empty
        data = r.json()
        nodes = [
            {"id": n.get("id"), "name": n.get("name"), "type": n.get("type")}
            for n in data.get("nodes", [])
        ]
        edges = data.get("edges", [])
        return {"pipeline_name": pipeline_name, "lineage": {"nodes": nodes, "edges": edges}}
    except Exception:
        return empty


@router.get("/pipelines/{pipeline_name}/quality")
async def get_pipeline_quality(pipeline_name: str):
    """Get latest data quality results from OpenMetadata."""
    token = await _get_om_token()
    empty = {"pipeline_name": pipeline_name, "checks": [], "last_updated": None}
    if not token:
        return empty
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                f"{OPENMETADATA_URL}/api/v1/dataQuality/testSuites",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": pipeline_name, "limit": 10},
            )
        if r.status_code != 200:
            return empty
        data = r.json()
        checks = [
            {
                "name": s.get("name"),
                "status": s.get("testCaseResultSummary", {}).get("statusCounts", {}),
                "updated": s.get("updatedAt"),
            }
            for s in data.get("data", [])
        ]
        return {"pipeline_name": pipeline_name, "checks": checks,
                "last_updated": checks[0]["updated"] if checks else None}
    except Exception:
        return empty


# === File upload endpoint ===

@router.post("/pipelines/upload/validate")
async def upload_and_validate(file: UploadFile = File(...)):
    """
    Upload and validate a pipeline file.

    Useful for IDE/editor integrations.
    """
    try:
        # Read file content
        content = await file.read()
        code = content.decode('utf-8')

        # Validate
        request = PipelineValidateRequest(code=code, filename=file.filename)
        return await validate_pipeline(request)

    except Exception as e:
        return ValidationResult(
            success=False,
            errors=[f"Upload error: {str(e)}"]
        )


@router.post("/pipelines/upload/compile")
async def upload_and_compile(file: UploadFile = File(...)):
    """
    Upload and compile a pipeline file.
    """
    try:
        # Read file content
        content = await file.read()
        code = content.decode('utf-8')

        # Compile
        request = PipelineCompileRequest(code=code, filename=file.filename)
        return await compile_pipeline(request)

    except Exception as e:
        return CompilationResultResponse(
            success=False,
            pipeline_name="unknown",
            errors=[f"Upload error: {str(e)}"],
            compiled_at=datetime.utcnow()
        )
