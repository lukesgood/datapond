"""Protected notebook and kernel APIs backed by Jupyter's REST API."""

from datetime import datetime
import json
import os
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.runtime import component_secret

router = APIRouter()

JUPYTER_URL = os.getenv("JUPYTER_URL", "http://jupyterlab:8888/jupyter").rstrip("/")
REQUEST_TIMEOUT = 30.0
MAX_NOTEBOOK_UPLOAD_BYTES = 10 * 1024 * 1024


def _jupyter_token() -> str:
    return component_secret("JUPYTER_TOKEN", "jupyter", component="jupyter")


class NotebookContent(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    created: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    mimetype: Optional[str] = None
    content: Optional[Any] = None
    format: Optional[str] = None
    writable: bool = True


class NotebookListResponse(BaseModel):
    notebooks: List[NotebookContent]
    total: int


class NotebookCreateRequest(BaseModel):
    path: str = Field(..., description="Relative POSIX path for the new notebook")
    type: str = Field(default="notebook")


class NotebookUpdateRequest(BaseModel):
    content: Dict[str, Any]
    type: str = Field(default="notebook")
    format: str = Field(default="json")


class NotebookRenameRequest(BaseModel):
    new_path: str


class NotebookTemplateRequest(BaseModel):
    path: str
    template: str = Field(default="python", description="python, spark, or blank")


class KernelInfo(BaseModel):
    id: str
    name: str
    last_activity: Optional[datetime] = None
    execution_state: Optional[str] = None
    connections: int = 0


class SessionInfo(BaseModel):
    id: str
    name: str
    path: str
    type: str
    kernel: Optional[KernelInfo] = None


def _validated_notebook_path(path: str, *, allow_empty: bool = False) -> str:
    """Return a safe relative POSIX path for the Jupyter contents API."""
    if path == "" and allow_empty:
        return ""
    if not path or "\x00" in path or "\\" in path or path.startswith("/"):
        raise HTTPException(400, "Notebook path must be a relative POSIX path")
    raw_parts = path.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise HTTPException(400, "Notebook path contains an unsafe segment")
    parts = PurePosixPath(path).parts
    normalized = str(PurePosixPath(*parts))
    if not normalized.lower().endswith(".ipynb"):
        raise HTTPException(400, "Notebook path must end with .ipynb")
    return normalized


def _validated_directory_path(path: str) -> str:
    if path == "":
        return ""
    if not path or "\x00" in path or "\\" in path or path.startswith("/"):
        raise HTTPException(400, "Directory path must be a relative POSIX path")
    raw_parts = path.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise HTTPException(400, "Directory path contains an unsafe segment")
    parts = PurePosixPath(path).parts
    return str(PurePosixPath(*parts))


def _contents_endpoint(path: str = "", *, notebook: bool = False) -> str:
    safe_path = (
        _validated_notebook_path(path)
        if notebook
        else _validated_directory_path(path)
    )
    # Preserve separators while percent-encoding every individual path segment.
    encoded = "/".join(quote(part, safe="") for part in PurePosixPath(safe_path).parts)
    return f"/api/contents/{encoded}" if encoded else "/api/contents"


def _api_segment(value: str, label: str) -> str:
    if not value or "\x00" in value or "/" in value or "\\" in value or value in (".", ".."):
        raise HTTPException(400, f"Invalid {label}")
    return quote(value, safe="")


def _validate_notebook_json(value: Any) -> Dict[str, Any]:
    """Validate the structural requirements of a JSON ``.ipynb`` document."""
    if not isinstance(value, dict):
        raise HTTPException(400, "Notebook JSON must be an object")
    cells = value.get("cells")
    metadata = value.get("metadata")
    nbformat = value.get("nbformat")
    nbformat_minor = value.get("nbformat_minor")
    if not isinstance(cells, list):
        raise HTTPException(400, "Notebook JSON must contain a cells array")
    if not isinstance(metadata, dict):
        raise HTTPException(400, "Notebook JSON must contain a metadata object")
    if not isinstance(nbformat, int) or isinstance(nbformat, bool) or nbformat < 1:
        raise HTTPException(400, "Notebook JSON must contain a valid integer nbformat")
    if not isinstance(nbformat_minor, int) or isinstance(nbformat_minor, bool) or nbformat_minor < 0:
        raise HTTPException(400, "Notebook JSON must contain a valid integer nbformat_minor")

    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise HTTPException(400, f"Notebook cell {index} must be an object")
        if cell.get("cell_type") not in ("code", "markdown", "raw"):
            raise HTTPException(400, f"Notebook cell {index} has an invalid cell_type")
        source = cell.get("source")
        if not (
            isinstance(source, str)
            or isinstance(source, list) and all(isinstance(line, str) for line in source)
        ):
            raise HTTPException(400, f"Notebook cell {index} source must be text or an array of text")
        if not isinstance(cell.get("metadata", {}), dict):
            raise HTTPException(400, f"Notebook cell {index} metadata must be an object")
        if cell.get("cell_type") == "code" and not isinstance(cell.get("outputs", []), list):
            raise HTTPException(400, f"Notebook code cell {index} outputs must be an array")
    return value


def _download_disposition(path: str) -> str:
    filename = PurePosixPath(path).name
    ascii_name = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_"
        for ch in filename
    ) or "notebook.ipynb"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def get_jupyter_headers() -> Dict[str, str]:
    return {
        "Authorization": f"token {_jupyter_token()}",
        "Content-Type": "application/json",
    }


async def make_jupyter_request(method: str, endpoint: str, **kwargs: Any) -> Any:
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(
                method=method,
                url=f"{JUPYTER_URL}{endpoint}",
                headers=get_jupyter_headers(),
                **kwargs,
            )
    except httpx.ConnectError as exc:
        raise HTTPException(503, "JupyterLab service is unavailable") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "JupyterLab request timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"JupyterLab request failed: {exc}") from exc

    if response.status_code == 404:
        raise HTTPException(404, "Notebook resource was not found in JupyterLab")
    if response.status_code in (401, 403):
        raise HTTPException(502, "JupyterLab rejected the configured service credentials")
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise HTTPException(response.status_code, f"JupyterLab API error: {detail}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "JupyterLab returned an invalid JSON response") from exc


def filter_notebooks(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        item for item in contents
        if item.get("type") == "notebook" or str(item.get("name", "")).endswith(".ipynb")
    ]


def create_notebook_template(template_type: str = "python") -> Dict[str, Any]:
    if template_type not in ("python", "spark", "blank"):
        raise HTTPException(400, "Template must be one of: python, spark, blank")
    notebook: Dict[str, Any] = {
        "cells": [],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    if template_type == "python":
        notebook["cells"] = [
            {"cell_type": "markdown", "metadata": {}, "source": ["# DataPond Notebook\n", "\n", "Welcome to DataPond JupyterLab!"]},
            {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["# Import libraries\n", "import pandas as pd\n", "import numpy as np"]},
        ]
    elif template_type == "spark":
        notebook["cells"] = [
            {"cell_type": "markdown", "metadata": {}, "source": ["# Spark Notebook\n", "\n", "PySpark data processing notebook"]},
            {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["from pyspark.sql import SparkSession\n", "\n", "spark = SparkSession.builder.appName('DataPond').getOrCreate()"]},
        ]
    return notebook


async def _collect_notebooks(path: str, recursive: bool) -> List[Dict[str, Any]]:
    contents = await make_jupyter_request("GET", _contents_endpoint(path))
    if not isinstance(contents, dict):
        raise HTTPException(502, "JupyterLab returned an invalid contents response")
    if contents.get("type") != "directory":
        return [contents] if contents.get("type") == "notebook" else []

    items = contents.get("content", [])
    if not isinstance(items, list):
        raise HTTPException(502, "JupyterLab returned an invalid directory listing")
    notebooks = filter_notebooks(items)
    if recursive:
        for item in items:
            if item.get("type") == "directory" and isinstance(item.get("path"), str):
                notebooks.extend(await _collect_notebooks(_validated_directory_path(item["path"]), True))
    return notebooks


# Static GET routes must be declared before /notebooks/{path:path}.
@router.get("/notebooks", response_model=NotebookListResponse)
async def list_notebooks(
    path: str = Query(default=""),
    recursive: bool = Query(default=False),
):
    notebooks = await _collect_notebooks(_validated_directory_path(path), recursive)
    return NotebookListResponse(
        notebooks=[NotebookContent(**notebook) for notebook in notebooks],
        total=len(notebooks),
    )


@router.get("/notebooks/download")
async def download_notebook(path: str = Query(...)):
    safe_path = _validated_notebook_path(path)
    result = await make_jupyter_request("GET", _contents_endpoint(safe_path, notebook=True))
    if not isinstance(result, dict) or result.get("type") != "notebook":
        raise HTTPException(400, "Path does not point to a notebook")
    content = _validate_notebook_json(result.get("content"))
    body = json.dumps(content, ensure_ascii=False, indent=1).encode("utf-8")
    return Response(
        content=body,
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": _download_disposition(safe_path)},
    )


@router.get("/notebooks/kernels/list", response_model=List[KernelInfo])
async def list_kernels():
    kernels = await make_jupyter_request("GET", "/api/kernels")
    return [KernelInfo(**kernel) for kernel in kernels]


@router.get("/notebooks/sessions/list", response_model=List[SessionInfo])
async def list_sessions():
    sessions = await make_jupyter_request("GET", "/api/sessions")
    return [SessionInfo(**session) for session in sessions]


@router.get("/notebooks/recent")
async def get_recent_notebooks(limit: int = Query(default=10, ge=1, le=50)):
    result = await list_notebooks(recursive=True)
    notebooks = sorted(
        result.notebooks,
        key=lambda notebook: notebook.last_modified or datetime.min,
        reverse=True,
    )
    return {"notebooks": notebooks[:limit], "total": len(notebooks)}


@router.get("/notebooks/search")
async def search_notebooks(query: str = Query(...), path: str = Query(default="")):
    result = await list_notebooks(path=path, recursive=True)
    lowered = query.lower()
    matches = [
        notebook for notebook in result.notebooks
        if lowered in notebook.name.lower() or lowered in notebook.path.lower()
    ]
    return {"notebooks": matches, "total": len(matches), "query": query}


@router.get("/notebooks/stats")
async def get_notebooks_stats():
    result = await list_notebooks(recursive=True)
    kernels = await list_kernels()
    sessions = await list_sessions()
    return {
        "total_notebooks": result.total,
        "running_kernels": len(kernels),
        "active_sessions": len(sessions),
    }


@router.get("/notebooks/health")
async def check_jupyter_health():
    await make_jupyter_request("GET", "/api/status")
    return {"status": "healthy", "message": "JupyterLab is accessible"}


# Static POST routes.
@router.post("/notebooks", response_model=NotebookContent)
async def create_notebook(request: NotebookCreateRequest):
    if request.type != "notebook":
        raise HTTPException(400, "Only notebook content can be created")
    safe_path = _validated_notebook_path(request.path)
    result = await make_jupyter_request(
        "PUT",
        _contents_endpoint(safe_path, notebook=True),
        json={"type": "notebook", "format": "json", "content": create_notebook_template("python")},
    )
    return NotebookContent(**result)


@router.post("/notebooks/from-template", response_model=NotebookContent)
async def create_notebook_from_template(request: NotebookTemplateRequest):
    safe_path = _validated_notebook_path(request.path)
    result = await make_jupyter_request(
        "PUT",
        _contents_endpoint(safe_path, notebook=True),
        json={"type": "notebook", "format": "json", "content": create_notebook_template(request.template)},
    )
    return NotebookContent(**result)


@router.post("/notebooks/upload", response_model=NotebookContent)
async def upload_notebook(
    file: UploadFile = File(...),
    path: Optional[str] = Form(default=None),
):
    target = path or PurePosixPath(file.filename or "").name
    safe_path = _validated_notebook_path(target)
    raw = await file.read(MAX_NOTEBOOK_UPLOAD_BYTES + 1)
    if len(raw) > MAX_NOTEBOOK_UPLOAD_BYTES:
        raise HTTPException(413, f"Notebook upload exceeds {MAX_NOTEBOOK_UPLOAD_BYTES // (1024 * 1024)} MiB")
    try:
        content = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Uploaded notebook must be valid UTF-8 JSON") from exc
    notebook = _validate_notebook_json(content)
    result = await make_jupyter_request(
        "PUT",
        _contents_endpoint(safe_path, notebook=True),
        json={"type": "notebook", "format": "json", "content": notebook},
    )
    return NotebookContent(**result)


@router.post("/notebooks/kernels/start", response_model=KernelInfo)
async def start_kernel(name: str = Query(default="python3")):
    result = await make_jupyter_request("POST", "/api/kernels", json={"name": name})
    return KernelInfo(**result)


@router.post("/notebooks/sessions/create", response_model=SessionInfo)
async def create_session(
    path: str = Query(...),
    name: str = Query(default=""),
    kernel_name: str = Query(default="python3"),
):
    safe_path = _validated_notebook_path(path)
    result = await make_jupyter_request(
        "POST",
        "/api/sessions",
        json={
            "path": safe_path,
            "name": name or safe_path,
            "type": "notebook",
            "kernel": {"name": kernel_name},
        },
    )
    return SessionInfo(**result)


# More-specific dynamic routes must precede the catch-all CRUD routes.
@router.post("/notebooks/{path:path}/rename", response_model=NotebookContent)
async def rename_notebook(path: str, request: NotebookRenameRequest):
    safe_path = _validated_notebook_path(path)
    new_path = _validated_notebook_path(request.new_path)
    result = await make_jupyter_request(
        "PATCH",
        _contents_endpoint(safe_path, notebook=True),
        json={"path": new_path},
    )
    return NotebookContent(**result)


@router.post("/notebooks/{path:path}/duplicate", response_model=NotebookContent)
async def duplicate_notebook(path: str):
    safe_path = _validated_notebook_path(path)
    parent = str(PurePosixPath(safe_path).parent)
    destination = "" if parent == "." else _validated_directory_path(parent)
    result = await make_jupyter_request(
        "POST",
        _contents_endpoint(destination),
        json={"copy_from": safe_path},
    )
    return NotebookContent(**result)


@router.post("/notebooks/kernels/{kernel_id}/interrupt")
async def interrupt_kernel(kernel_id: str):
    encoded = _api_segment(kernel_id, "kernel id")
    await make_jupyter_request("POST", f"/api/kernels/{encoded}/interrupt")
    return {"message": f"Kernel '{kernel_id}' interrupted"}


@router.post("/notebooks/kernels/{kernel_id}/restart")
async def restart_kernel(kernel_id: str):
    encoded = _api_segment(kernel_id, "kernel id")
    await make_jupyter_request("POST", f"/api/kernels/{encoded}/restart")
    return {"message": f"Kernel '{kernel_id}' restarted"}


@router.delete("/notebooks/kernels/{kernel_id}")
async def stop_kernel(kernel_id: str):
    encoded = _api_segment(kernel_id, "kernel id")
    await make_jupyter_request("DELETE", f"/api/kernels/{encoded}")
    return {"message": f"Kernel '{kernel_id}' stopped successfully"}


@router.delete("/notebooks/sessions/{session_id}")
async def delete_session(session_id: str):
    encoded = _api_segment(session_id, "session id")
    await make_jupyter_request("DELETE", f"/api/sessions/{encoded}")
    return {"message": f"Session '{session_id}' deleted successfully"}


@router.get("/notebooks/{path:path}", response_model=NotebookContent)
async def get_notebook(path: str):
    safe_path = _validated_notebook_path(path)
    result = await make_jupyter_request("GET", _contents_endpoint(safe_path, notebook=True))
    if not isinstance(result, dict) or result.get("type") != "notebook":
        raise HTTPException(400, "Path does not point to a notebook")
    _validate_notebook_json(result.get("content"))
    return NotebookContent(**result)


@router.put("/notebooks/{path:path}", response_model=NotebookContent)
async def update_notebook(path: str, request: NotebookUpdateRequest):
    safe_path = _validated_notebook_path(path)
    if request.type != "notebook" or request.format != "json":
        raise HTTPException(400, "Notebook updates must use notebook/json content")
    content = _validate_notebook_json(request.content)
    result = await make_jupyter_request(
        "PUT",
        _contents_endpoint(safe_path, notebook=True),
        json={"type": "notebook", "format": "json", "content": content},
    )
    return NotebookContent(**result)


@router.delete("/notebooks/{path:path}")
async def delete_notebook(path: str):
    safe_path = _validated_notebook_path(path)
    await make_jupyter_request("DELETE", _contents_endpoint(safe_path, notebook=True))
    return {"message": f"Notebook '{safe_path}' deleted successfully"}
