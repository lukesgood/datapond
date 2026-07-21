"""Focused regressions for notebook, MLflow, and transform integrations."""

import ast
import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

import pytest
from fastapi import HTTPException, UploadFile

from app.api import notebooks


ROOT = Path(__file__).parents[2]
TRANSFORMS_PATH = ROOT / "backend/app/api/transforms.py"
MLFLOW_BACKEND_PATH = ROOT / "backend/app/api/mlflow_integration.py"
MLFLOW_ROUTES = ROOT / "frontend/app/api/mlflow"


def _run(coro):
    return asyncio.run(coro)


def _valid_notebook():
    return {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "source": ["print('ok')\n"],
                "execution_count": None,
                "outputs": [],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


@pytest.mark.parametrize(
    "path",
    ["", "/root.ipynb", "../escape.ipynb", "a/../escape.ipynb", "a//b.ipynb", "a/./b.ipynb", "a\\b.ipynb", "note.txt"],
)
def test_notebook_paths_reject_unsafe_or_non_notebook_values(path):
    with pytest.raises(HTTPException) as exc:
        notebooks._validated_notebook_path(path)
    assert exc.value.status_code == 400


def test_notebook_content_path_is_segment_encoded():
    assert notebooks._contents_endpoint("folder/a b#c.ipynb", notebook=True) == (
        "/api/contents/folder/a%20b%23c.ipynb"
    )


def test_notebook_json_validation_rejects_invalid_cells():
    invalid = _valid_notebook()
    invalid["cells"][0]["source"] = ["ok", 7]
    with pytest.raises(HTTPException) as exc:
        notebooks._validate_notebook_json(invalid)
    assert exc.value.status_code == 400
    assert "source" in exc.value.detail


def test_upload_validates_json_and_uses_encoded_contents_path(monkeypatch):
    seen = {}

    async def request(method, endpoint, **kwargs):
        seen.update(method=method, endpoint=endpoint, payload=kwargs["json"])
        return {
            "name": "space name.ipynb",
            "path": "team/space name.ipynb",
            "type": "notebook",
            "content": kwargs["json"]["content"],
        }

    monkeypatch.setattr(notebooks, "make_jupyter_request", request)
    upload = UploadFile(
        filename="space name.ipynb",
        file=BytesIO(__import__("json").dumps(_valid_notebook()).encode()),
    )
    result = _run(notebooks.upload_notebook(upload, "team/space name.ipynb"))

    assert result.path == "team/space name.ipynb"
    assert seen["method"] == "PUT"
    assert seen["endpoint"] == "/api/contents/team/space%20name.ipynb"
    assert seen["payload"]["type"] == "notebook"


def test_upload_enforces_size_limit():
    upload = UploadFile(
        filename="large.ipynb",
        file=BytesIO(b"x" * (notebooks.MAX_NOTEBOOK_UPLOAD_BYTES + 1)),
    )
    with pytest.raises(HTTPException) as exc:
        _run(notebooks.upload_notebook(upload, None))
    assert exc.value.status_code == 413


def test_download_returns_notebook_media_type_and_safe_disposition(monkeypatch):
    async def request(method, endpoint, **kwargs):
        assert method == "GET"
        assert endpoint == "/api/contents/team/report%20%CE%B1.ipynb"
        return {
            "name": "report α.ipynb",
            "path": "team/report α.ipynb",
            "type": "notebook",
            "content": _valid_notebook(),
        }

    monkeypatch.setattr(notebooks, "make_jupyter_request", request)
    response = _run(notebooks.download_notebook("team/report α.ipynb"))
    assert response.media_type == "application/x-ipynb+json"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''report%20%CE%B1.ipynb" in disposition


def test_static_notebook_routes_precede_catch_all_get_route():
    paths = [route.path for route in notebooks.router.routes if "GET" in route.methods]
    catch_all = paths.index("/notebooks/{path:path}")
    for path in (
        "/notebooks/download",
        "/notebooks/kernels/list",
        "/notebooks/sessions/list",
        "/notebooks/recent",
        "/notebooks/search",
        "/notebooks/stats",
        "/notebooks/health",
    ):
        assert paths.index(path) < catch_all


def test_notebook_router_is_protected_by_api_auth_and_component_guard():
    source = (ROOT / "backend/main.py").read_text()
    assert "class AuthMiddleware" in source
    assert 'if not path.startswith("/api/")' in source
    assert 'app.include_router(notebooks_router, prefix="/api"' in source
    assert 'Depends(require_component("JUPYTER", "Notebooks"))' in source


def test_mlflow_route_handlers_all_use_shared_authenticated_proxy():
    route_files = sorted(MLFLOW_ROUTES.glob("**/route.ts"))
    assert route_files
    for route_file in route_files:
        source = route_file.read_text()
        assert "proxyMlflow" in source, route_file
        assert "NextResponse.json(data)" not in source, route_file

    helper = (MLFLOW_ROUTES / "_proxy.ts").read_text()
    assert 'request.headers.get("authorization")' in helper
    assert 'headers.set("authorization", authorization)' in helper
    assert "status: upstream.status" in helper
    assert '"content-type"' in helper
    assert "new Response(upstream.body" in helper


def test_owned_frontend_has_no_direct_jupyter_api_or_hardcoded_token():
    owned = [
        ROOT / "frontend/app/notebooks",
        ROOT / "frontend/components/notebooks",
        ROOT / "frontend/components/query/open-in-notebook-modal.tsx",
    ]
    source_parts = []
    for path in owned:
        if path.is_dir():
            source_parts.extend(file.read_text() for file in path.rglob("*.tsx"))
        else:
            source_parts.append(path.read_text())
    source = "\n".join(source_parts)
    assert "/jupyter/api" not in source
    assert "/api/contents" not in source
    assert "token=jupyter" not in source
    assert "?token=" not in source


def test_experiment_consumers_do_not_use_nested_proxy_envelopes():
    paths = [
        *list((ROOT / "frontend/app/experiments").rglob("*.tsx")),
        *list((ROOT / "frontend/components/mlflow").rglob("*.tsx")),
        ROOT / "frontend/components/query/log-to-mlflow-modal.tsx",
    ]
    source = "\n".join(path.read_text() for path in paths)
    for nested in (
        ".registered_models",
        "data.experiments",
        "data.runs",
        "expData.experiment",
        "runData.run",
        "runsData.runs",
    ):
        assert nested not in source


class _Field:
    def __eq__(self, other):
        return ("eq", other)

    def __ne__(self, other):
        return ("ne", other)


class _SavedTransform:
    id = _Field()
    name = _Field()
    dag_id = _Field()

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args):
        return self

    def first(self):
        return self.value


class _Db:
    def __init__(self, query_values):
        self.query_values = list(query_values)
        self.commits = 0
        self.rollbacks = 0
        self.added = []
        self.deleted = []

    def query(self, model):
        return _Query(self.query_values.pop(0))

    def add(self, row):
        self.added.append(row)

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, row):
        return None


def _load_transform_function(name: str, extra: dict[str, Any]):
    tree = ast.parse(TRANSFORMS_PATH.read_text())
    node = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {
        "Any": Any,
        "Depends": lambda dependency: None,
        "get_db": object(),
        "Session": object,
        "TransformCreateRequest": object,
        "TransformUpdateRequest": object,
        "SavedTransform": _SavedTransform,
        "HTTPException": HTTPException,
        "SimpleNamespace": SimpleNamespace,
        "NAMESPACES": ["raw", "refined", "serving"],
        "uuid": uuid,
        **extra,
    }
    exec(compile(module, str(TRANSFORMS_PATH), "exec"), scope)
    return scope[name]


def test_transform_create_rolls_back_without_commit_when_deploy_fails():
    async def explain(sql):
        return None

    async def deploy(dag_id, code):
        raise HTTPException(503, "Airflow unavailable")

    create = _load_transform_function(
        "create_transform",
        {
            "_validate_transform_sql": lambda sql: None,
            "_explain_check": explain,
            "_safe_id": lambda name: name.lower(),
            "_generate_dag": lambda candidate: "dag",
            "_deploy_dag": deploy,
            "datetime": __import__("datetime").datetime,
        },
    )
    db = _Db([None, None])
    request = SimpleNamespace(
        name="Orders",
        description=None,
        source_namespace="raw",
        target_namespace="refined",
        target_table="orders",
        sql="SELECT 1",
        schedule=None,
        overwrite=True,
    )
    with pytest.raises(HTTPException) as exc:
        _run(create(request, db))
    assert exc.value.status_code == 503
    assert db.commits == 0
    assert db.added == []
    assert db.rollbacks == 1


def test_transform_update_keeps_row_unchanged_when_activation_fails():
    async def explain(sql):
        return None

    async def deploy(dag_id, code):
        raise HTTPException(502, "activation failed")

    row = SimpleNamespace(
        id=uuid.uuid4(),
        name="Orders",
        description="old",
        source_namespace="raw",
        target_namespace="refined",
        target_table="orders",
        sql="SELECT old",
        schedule=None,
        dag_id="transform_orders",
        status="deployed",
    )
    update = _load_transform_function(
        "update_transform",
        {
            "_validate_transform_sql": lambda sql: None,
            "_explain_check": explain,
            "_safe_id": lambda name: name.lower(),
            "_generate_dag": lambda candidate: "dag",
            "_deploy_dag": deploy,
            "datetime": __import__("datetime").datetime,
        },
    )
    db = _Db([row])
    request = SimpleNamespace(
        description="new",
        source_namespace=None,
        target_namespace=None,
        target_table=None,
        sql="SELECT new",
        schedule=None,
        model_fields_set={"description", "sql"},
    )
    with pytest.raises(HTTPException) as exc:
        _run(update(str(row.id), request, db))
    assert exc.value.status_code == 502
    assert row.description == "old"
    assert row.sql == "SELECT old"
    assert db.commits == 0
    assert db.rollbacks == 1


def test_transform_delete_preserves_db_and_file_on_remote_failure(tmp_path):
    async def remove(dag_id):
        raise HTTPException(502, "pause failed")

    row = SimpleNamespace(id=uuid.uuid4(), dag_id="transform_orders")
    dag_file = tmp_path / "transform_orders.py"
    dag_file.write_text("existing")
    delete = _load_transform_function(
        "delete_transform",
        {"_remove_remote_dag": remove, "DAGS_PATH": tmp_path},
    )
    db = _Db([row])
    with pytest.raises(HTTPException) as exc:
        _run(delete(str(row.id), db))
    assert exc.value.status_code == 502
    assert dag_file.read_text() == "existing"
    assert db.deleted == []
    assert db.commits == 0
    assert db.rollbacks == 1


def test_transform_delete_removes_db_row_after_remote_success(tmp_path):
    calls = []

    async def remove(dag_id):
        calls.append(dag_id)

    row = SimpleNamespace(id=uuid.uuid4(), dag_id="transform_orders")
    dag_file = tmp_path / "transform_orders.py"
    dag_file.write_text("existing")
    delete = _load_transform_function(
        "delete_transform",
        {"_remove_remote_dag": remove, "DAGS_PATH": tmp_path},
    )
    db = _Db([row])
    assert _run(delete(str(row.id), db)) == {"success": True}
    assert calls == ["transform_orders"]
    assert not dag_file.exists()
    assert db.deleted == [row]
    assert db.commits == 1


def _load_mlflow_archive_functions(client):
    tree = ast.parse(MLFLOW_BACKEND_PATH.read_text())
    names = {"_archive_experiment", "delete_experiment", "archive_experiment"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    assert {node.name for node in nodes} == names
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {
        "asyncio": asyncio,
        "HTTPException": HTTPException,
        "get_mlflow_client": lambda: client,
        "logger": SimpleNamespace(warning=lambda *a, **k: None),
    }
    exec(compile(module, str(MLFLOW_BACKEND_PATH), "exec"), scope)
    return scope


def test_mlflow_experiment_archive_routes_call_delete_experiment():
    class FakeClient:
        def __init__(self):
            self.deleted = []

        def delete_experiment(self, experiment_id):
            self.deleted.append(experiment_id)

    client = FakeClient()
    functions = _load_mlflow_archive_functions(client)

    deleted = _run(functions["delete_experiment"]("exp-delete"))
    archived = _run(functions["archive_experiment"]("exp-archive"))

    assert client.deleted == ["exp-delete", "exp-archive"]
    assert deleted == {
        "experiment_id": "exp-delete",
        "lifecycle_stage": "deleted",
        "archived": True,
    }
    assert archived["archived"] is True

    source = MLFLOW_BACKEND_PATH.read_text()
    # Mutating experiment routes are admin-gated (dependency in the decorator).
    assert '@router.delete("/mlflow/experiments/{experiment_id}", dependencies=[Depends(require_admin)])' in source
    assert '@router.post("/mlflow/experiments/{experiment_id}/archive", dependencies=[Depends(require_admin)])' in source


def test_mlflow_experiment_archive_maps_upstream_failures():
    class FailingClient:
        def __init__(self, message):
            self.message = message

        def delete_experiment(self, experiment_id):
            raise RuntimeError(self.message)

    unavailable = _load_mlflow_archive_functions(FailingClient("upstream timed out"))
    with pytest.raises(HTTPException) as exc:
        _run(unavailable["archive_experiment"]("exp-1"))
    assert exc.value.status_code == 502
    # Raw upstream error text must NOT be echoed to the client.
    assert "upstream timed out" not in exc.value.detail
    assert "exp-1" in exc.value.detail

    missing = _load_mlflow_archive_functions(FailingClient("experiment does not exist"))
    with pytest.raises(HTTPException) as exc:
        _run(missing["delete_experiment"]("missing"))
    assert exc.value.status_code == 404
