"""
JupyterLab Notebooks API - Manage notebooks via JupyterLab REST API
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
import httpx
import os
from datetime import datetime
import json

router = APIRouter()

# Configuration
JUPYTER_URL = os.getenv("JUPYTER_URL", "http://jupyterlab:8888")
JUPYTER_TOKEN = os.getenv("JUPYTER_TOKEN", "jupyter")
REQUEST_TIMEOUT = 30.0


# Pydantic Models
class NotebookCell(BaseModel):
    cell_type: str  # "code", "markdown", "raw"
    source: List[str] | str
    execution_count: Optional[int] = None
    outputs: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NotebookMetadata(BaseModel):
    kernelspec: Optional[Dict[str, str]] = None
    language_info: Optional[Dict[str, Any]] = None


class NotebookContent(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    created: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    mimetype: Optional[str] = None
    content: Optional[Any] = None  # Full notebook JSON or None
    format: Optional[str] = None
    writable: bool = True


class NotebookListResponse(BaseModel):
    notebooks: List[NotebookContent]
    total: int


class NotebookCreateRequest(BaseModel):
    path: str = Field(..., description="Path where to create notebook (e.g., 'Untitled.ipynb' or 'folder/notebook.ipynb')")
    type: str = Field(default="notebook", description="Content type (always 'notebook')")


class NotebookUpdateRequest(BaseModel):
    content: Dict[str, Any] = Field(..., description="Full notebook JSON content")
    type: str = Field(default="notebook")
    format: str = Field(default="json")


class NotebookRenameRequest(BaseModel):
    new_path: str = Field(..., description="New path for the notebook")


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


class NotebookTemplateRequest(BaseModel):
    path: str
    template: str = Field(default="python", description="Template type: python, spark, or blank")


# Helper functions
def get_jupyter_headers():
    """Get headers for JupyterLab API requests"""
    return {
        "Authorization": f"token {JUPYTER_TOKEN}",
        "Content-Type": "application/json"
    }


async def make_jupyter_request(method: str, endpoint: str, **kwargs):
    """Make HTTP request to JupyterLab API"""
    url = f"{JUPYTER_URL}{endpoint}"
    headers = get_jupyter_headers()

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )

            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="Resource not found in JupyterLab")
            elif response.status_code == 403:
                raise HTTPException(status_code=403, detail="Access denied to JupyterLab resource")
            elif response.status_code >= 400:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"JupyterLab API error: {response.text}"
                )

            return response.json() if response.text else None

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="JupyterLab service unavailable. Check if JupyterLab is running."
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="JupyterLab request timeout"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JupyterLab request failed: {str(e)}")


def filter_notebooks(contents: List[Dict]) -> List[Dict]:
    """Filter only notebook files from contents"""
    return [
        item for item in contents
        if item.get("type") == "notebook" or item.get("name", "").endswith(".ipynb")
    ]


def create_notebook_template(template_type: str = "python") -> Dict[str, Any]:
    """Create notebook template content"""
    base_notebook = {
        "cells": [],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.10.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }

    if template_type == "python":
        base_notebook["cells"] = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# DataPond Notebook\n", "\n", "Welcome to DataPond JupyterLab!"]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": ["# Import libraries\n", "import pandas as pd\n", "import numpy as np"]
            }
        ]
    elif template_type == "spark":
        base_notebook["cells"] = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Spark Notebook\n", "\n", "PySpark data processing notebook"]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from pyspark.sql import SparkSession\n",
                    "\n",
                    "spark = SparkSession.builder \\\n",
                    "    .appName('DataPond') \\\n",
                    "    .getOrCreate()"
                ]
            }
        ]

    return base_notebook


# API Endpoints

@router.get("/notebooks", response_model=NotebookListResponse)
async def list_notebooks(
    path: str = Query(default="", description="Directory path to list notebooks from"),
    recursive: bool = Query(default=False, description="Recursively list all notebooks")
):
    """
    List all notebooks in JupyterLab

    - **path**: Directory path (empty for root)
    - **recursive**: If true, list all notebooks recursively
    """
    contents = await make_jupyter_request("GET", f"/api/contents/{path}")

    notebooks = []

    if isinstance(contents, dict):
        # Single file or directory
        if contents.get("type") == "directory":
            # Directory listing
            content_items = contents.get("content", [])
            notebooks = filter_notebooks(content_items)

            # Recursive listing
            if recursive:
                for item in content_items:
                    if item.get("type") == "directory":
                        subdir_path = item.get("path", "")
                        subdir_contents = await make_jupyter_request("GET", f"/api/contents/{subdir_path}")
                        if subdir_contents.get("content"):
                            notebooks.extend(filter_notebooks(subdir_contents["content"]))
        else:
            # Single notebook
            notebooks = [contents] if contents.get("type") == "notebook" else []

    return NotebookListResponse(
        notebooks=[NotebookContent(**nb) for nb in notebooks],
        total=len(notebooks)
    )


@router.get("/notebooks/{path:path}", response_model=NotebookContent)
async def get_notebook(path: str):
    """
    Get notebook content by path

    - **path**: Notebook path (e.g., 'Untitled.ipynb' or 'folder/notebook.ipynb')
    - Returns full notebook content including cells
    """
    contents = await make_jupyter_request("GET", f"/api/contents/{path}")

    if contents.get("type") != "notebook":
        raise HTTPException(status_code=400, detail="Path does not point to a notebook")

    return NotebookContent(**contents)


@router.post("/notebooks", response_model=NotebookContent)
async def create_notebook(request: NotebookCreateRequest):
    """
    Create a new notebook

    - **path**: Path where to create notebook (e.g., 'Untitled.ipynb')
    - Creates empty notebook with default Python kernel
    """
    # Create notebook with empty content
    notebook_content = create_notebook_template("python")

    payload = {
        "type": "notebook",
        "format": "json",
        "content": notebook_content
    }

    result = await make_jupyter_request(
        "PUT",
        f"/api/contents/{request.path}",
        json=payload
    )

    return NotebookContent(**result)


@router.post("/notebooks/from-template", response_model=NotebookContent)
async def create_notebook_from_template(request: NotebookTemplateRequest):
    """
    Create notebook from template

    - **path**: Notebook path
    - **template**: Template type (python, spark, blank)
    """
    notebook_content = create_notebook_template(request.template)

    payload = {
        "type": "notebook",
        "format": "json",
        "content": notebook_content
    }

    result = await make_jupyter_request(
        "PUT",
        f"/api/contents/{request.path}",
        json=payload
    )

    return NotebookContent(**result)


@router.put("/notebooks/{path:path}", response_model=NotebookContent)
async def update_notebook(path: str, request: NotebookUpdateRequest):
    """
    Update notebook content

    - **path**: Notebook path
    - **content**: Full notebook JSON content
    """
    payload = {
        "type": request.type,
        "format": request.format,
        "content": request.content
    }

    result = await make_jupyter_request(
        "PUT",
        f"/api/contents/{path}",
        json=payload
    )

    return NotebookContent(**result)


@router.delete("/notebooks/{path:path}")
async def delete_notebook(path: str):
    """
    Delete notebook

    - **path**: Notebook path to delete
    """
    await make_jupyter_request("DELETE", f"/api/contents/{path}")

    return {"message": f"Notebook '{path}' deleted successfully"}


@router.post("/notebooks/{path:path}/rename", response_model=NotebookContent)
async def rename_notebook(path: str, request: NotebookRenameRequest):
    """
    Rename or move notebook

    - **path**: Current notebook path
    - **new_path**: New path for the notebook
    """
    payload = {
        "path": request.new_path
    }

    result = await make_jupyter_request(
        "PATCH",
        f"/api/contents/{path}",
        json=payload
    )

    return NotebookContent(**result)


@router.post("/notebooks/{path:path}/duplicate", response_model=NotebookContent)
async def duplicate_notebook(path: str):
    """
    Duplicate notebook (copy)

    - **path**: Notebook path to duplicate
    - Creates copy with '-Copy' suffix
    """
    payload = {
        "copy_from": path
    }

    result = await make_jupyter_request(
        "POST",
        f"/api/contents/",
        json=payload
    )

    return NotebookContent(**result)


# Kernel Management

@router.get("/notebooks/kernels/list", response_model=List[KernelInfo])
async def list_kernels():
    """
    List all running kernels

    Returns information about active kernel sessions
    """
    kernels = await make_jupyter_request("GET", "/api/kernels")

    return [KernelInfo(**kernel) for kernel in kernels]


@router.post("/notebooks/kernels/start")
async def start_kernel(name: str = Query(default="python3", description="Kernel name to start")):
    """
    Start a new kernel

    - **name**: Kernel name (default: python3)
    """
    payload = {
        "name": name
    }

    result = await make_jupyter_request("POST", "/api/kernels", json=payload)

    return KernelInfo(**result)


@router.delete("/notebooks/kernels/{kernel_id}")
async def stop_kernel(kernel_id: str):
    """
    Stop a running kernel

    - **kernel_id**: Kernel ID to stop
    """
    await make_jupyter_request("DELETE", f"/api/kernels/{kernel_id}")

    return {"message": f"Kernel '{kernel_id}' stopped successfully"}


@router.post("/notebooks/kernels/{kernel_id}/interrupt")
async def interrupt_kernel(kernel_id: str):
    """
    Interrupt a running kernel

    - **kernel_id**: Kernel ID to interrupt
    """
    await make_jupyter_request("POST", f"/api/kernels/{kernel_id}/interrupt")

    return {"message": f"Kernel '{kernel_id}' interrupted"}


@router.post("/notebooks/kernels/{kernel_id}/restart")
async def restart_kernel(kernel_id: str):
    """
    Restart a kernel

    - **kernel_id**: Kernel ID to restart
    """
    await make_jupyter_request("POST", f"/api/kernels/{kernel_id}/restart")

    return {"message": f"Kernel '{kernel_id}' restarted"}


# Session Management

@router.get("/notebooks/sessions/list", response_model=List[SessionInfo])
async def list_sessions():
    """
    List all active notebook sessions

    Returns notebook sessions with their associated kernels
    """
    sessions = await make_jupyter_request("GET", "/api/sessions")

    return [SessionInfo(**session) for session in sessions]


@router.post("/notebooks/sessions/create")
async def create_session(
    path: str = Query(..., description="Notebook path"),
    name: str = Query(default="", description="Session name"),
    kernel_name: str = Query(default="python3", description="Kernel name")
):
    """
    Create a new session for a notebook

    - **path**: Notebook path
    - **name**: Session name (optional)
    - **kernel_name**: Kernel to use (default: python3)
    """
    payload = {
        "path": path,
        "name": name or path,
        "type": "notebook",
        "kernel": {
            "name": kernel_name
        }
    }

    result = await make_jupyter_request("POST", "/api/sessions", json=payload)

    return SessionInfo(**result)


@router.delete("/notebooks/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session

    - **session_id**: Session ID to delete
    """
    await make_jupyter_request("DELETE", f"/api/sessions/{session_id}")

    return {"message": f"Session '{session_id}' deleted successfully"}


# Utility Endpoints

@router.get("/notebooks/recent")
async def get_recent_notebooks(limit: int = Query(default=10, ge=1, le=50)):
    """
    Get recently modified notebooks

    - **limit**: Number of notebooks to return (1-50)
    """
    # Get all notebooks
    result = await list_notebooks(recursive=True)

    # Sort by last_modified
    sorted_notebooks = sorted(
        result.notebooks,
        key=lambda x: x.last_modified or datetime.min,
        reverse=True
    )

    return {
        "notebooks": sorted_notebooks[:limit],
        "total": len(sorted_notebooks)
    }


@router.get("/notebooks/search")
async def search_notebooks(
    query: str = Query(..., description="Search query"),
    path: str = Query(default="", description="Directory to search in")
):
    """
    Search notebooks by name

    - **query**: Search query (case-insensitive)
    - **path**: Directory path to search in
    """
    # Get all notebooks
    result = await list_notebooks(path=path, recursive=True)

    # Filter by name
    query_lower = query.lower()
    matching_notebooks = [
        nb for nb in result.notebooks
        if query_lower in nb.name.lower() or query_lower in nb.path.lower()
    ]

    return {
        "notebooks": matching_notebooks,
        "total": len(matching_notebooks),
        "query": query
    }


@router.get("/notebooks/stats")
async def get_notebooks_stats():
    """
    Get notebook statistics

    Returns counts and metrics about notebooks
    """
    try:
        # Get all notebooks
        result = await list_notebooks(recursive=True)

        # Get kernels
        kernels = await list_kernels()

        # Get sessions
        sessions = await list_sessions()

        return {
            "total_notebooks": result.total,
            "running_kernels": len(kernels),
            "active_sessions": len(sessions),
            "jupyter_url": JUPYTER_URL
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/notebooks/health")
async def check_jupyter_health():
    """
    Check JupyterLab service health

    Returns connection status to JupyterLab
    """
    try:
        # Try to connect to JupyterLab API
        await make_jupyter_request("GET", "/api/status")

        return {
            "status": "healthy",
            "jupyter_url": JUPYTER_URL,
            "message": "JupyterLab is accessible"
        }
    except HTTPException as e:
        return {
            "status": "unhealthy",
            "jupyter_url": JUPYTER_URL,
            "message": f"JupyterLab connection failed: {e.detail}"
        }
