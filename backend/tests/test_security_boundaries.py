"""Focused security-boundary tests that do not require live services."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import ai_backends, ai_vectors, auth, storage, system_settings


USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ID = "00000000-0000-0000-0000-000000000002"


_TEST_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_TEST_LOOP)


def _run(coro):
    return _TEST_LOOP.run_until_complete(coro)


def _request(method=None, path=None, key=None):
    if method is None or path is None:
        headers = {"X-Internal-Key": key} if key is not None else {}
        return SimpleNamespace(state=SimpleNamespace(), headers=headers)
    raw_headers = []
    if key is not None:
        raw_headers.append((b"x-internal-key", key.encode()))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    })


def _route_dependencies(router, path, method):
    route = next(
        route for route in router.routes
        if route.path == path and method.upper() in route.methods
    )
    return {dependency.call for dependency in route.dependant.dependencies}


def test_internal_key_accepts_only_exact_post_callback_routes(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "service-secret")
    allowed = (
        "/api/ai/collections/knowledge/ingest-source",
        "/api/connectors/connector-id/sync",
    )
    for path in allowed:
        request = _request("POST", path, "service-secret")
        assert auth.is_internal_automation_request(request) is True
        principal = _run(auth.require_user_or_internal(request, None))
        assert principal == {
            "id": None,
            "username": "system",
            "role": "admin",
            "internal": True,
        }

    denied = (
        ("GET", allowed[0]),
        ("POST", allowed[0] + "/extra"),
        ("POST", "/api/ai/collections/knowledge/schedule"),
        ("GET", "/api/connectors/connector-id/sync"),
        ("POST", "/api/connectors/connector-id/sync/stream"),
        ("POST", "/api/settings/system"),
    )
    for method, path in denied:
        assert auth.is_internal_automation_request(
            _request(method, path, "service-secret")
        ) is False


def test_internal_key_fails_closed_without_method_or_url(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "service-secret")
    request_double = _request(key="service-secret")
    assert auth.is_internal_automation_request(request_double) is False

    monkeypatch.setattr(auth, "get_current_user", lambda credentials: _async_value(None))
    with pytest.raises(HTTPException) as exc:
        _run(auth.require_user_or_internal(request_double, None))
    assert exc.value.status_code == 401


async def _async_value(value):
    return value


def test_main_wires_scoped_helper_in_middleware_and_connector_dependency():
    """AST inspection avoids importing unrelated Kubernetes/notebook modules."""
    main_path = Path(__file__).parents[1] / "main.py"
    tree = ast.parse(main_path.read_text())

    auth_dispatch = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dispatch"
    )
    dispatch_calls = {
        node.func.id for node in ast.walk(auth_dispatch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "is_internal_automation_request" in dispatch_calls
    assert "getenv" not in dispatch_calls

    connector_include = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "connectors_router"
    )
    dependencies = next(
        keyword.value for keyword in connector_include.keywords
        if keyword.arg == "dependencies"
    )
    assert any(
        isinstance(node, ast.Name) and node.id == "require_user_or_internal"
        for node in ast.walk(dependencies)
    )


def test_sensitive_routes_have_admin_dependencies():
    for path, method in (
        ("/settings/ai/backends", "GET"),
        ("/settings/ai/backends", "POST"),
        ("/settings/ai/backends/{model_id}", "DELETE"),
        ("/settings/ai/active", "POST"),
        ("/settings/ai/backends/{model_name}/test", "POST"),
        ("/settings/ai/keys", "GET"),
        ("/settings/ai/keys", "POST"),
        ("/settings/ai/keys/{token}", "DELETE"),
        ("/settings/ai/spend", "GET"),
        ("/settings/ai/usage", "GET"),
        ("/settings/ai/spend/report", "GET"),
        ("/settings/ai/budget-alerts", "GET"),
    ):
        assert auth.require_admin in _route_dependencies(ai_backends.router, path, method)

    for path, method in (
        ("/storage/buckets/{bucket_name}", "POST"),
        ("/storage/buckets/{bucket_name}", "DELETE"),
    ):
        assert auth.require_admin in _route_dependencies(storage.router, path, method)

    for path, method in (
        ("/settings/system", "GET"),
        ("/settings/system", "PATCH"),
        ("/settings/system/ai", "GET"),
    ):
        assert auth.require_admin in _route_dependencies(system_settings.router, path, method)


def test_knowledge_write_routes_have_intended_dependencies():
    assert auth.require_admin_or_internal in _route_dependencies(
        ai_vectors.router, "/ai/collections/{name}/ingest-source", "POST"
    )
    # /schedule is NOT in the internal-automation allowlist, so it uses plain
    # require_admin (not require_admin_or_internal, whose internal branch would be
    # unreachable here).
    assert auth.require_admin in _route_dependencies(
        ai_vectors.router, "/ai/collections/{name}/schedule", "POST"
    )
    assert auth.require_admin_or_internal not in _route_dependencies(
        ai_vectors.router, "/ai/collections/{name}/schedule", "POST"
    )
    assert auth.require_user in _route_dependencies(
        ai_vectors.router, "/ai/collections/{name}/ingest", "POST"
    )
    assert auth.require_user in _route_dependencies(
        ai_vectors.router, "/ai/collections/{name}/schedule", "DELETE"
    )


class _CollectionConn:
    def __init__(self, owner_id):
        self.row = {"id": "collection-id", "owner_id": owner_id}

    async def fetchrow(self, query, *args):
        return self.row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def test_shared_collection_is_read_only_to_non_admin():
    conn = _CollectionConn(owner_id=None)
    viewer = {"id": USER_ID, "role": "viewer"}
    admin = {"id": OTHER_ID, "role": "admin"}

    assert _run(ai_vectors._collection_id(conn, "shared", viewer)) == "collection-id"
    for mode in ({"write": True}, {"destroy": True}):
        with pytest.raises(HTTPException) as exc:
            _run(ai_vectors._collection_id(conn, "shared", viewer, **mode))
        assert exc.value.status_code == 403
    assert _run(
        ai_vectors._collection_id(conn, "shared", admin, write=True)
    ) == "collection-id"


def test_shared_collection_mutation_handlers_all_use_write_gate(monkeypatch):
    pool = _Pool(_CollectionConn(owner_id=None))
    monkeypatch.setattr(ai_vectors, "get_db_pool", lambda: _async_value(pool))
    monkeypatch.setattr(ai_vectors, "ensure_vector_schema", lambda pool: _async_value(None))
    viewer = {"id": USER_ID, "role": "viewer"}
    source = ai_vectors.SourceIngest(type="s3", bucket="docs")

    calls = (
        ai_vectors.ingest("shared", ai_vectors.IngestRequest(documents=[]), viewer),
        ai_vectors.ingest_source("shared", source, viewer),
        ai_vectors.schedule_ingest(
            "shared", ai_vectors.ScheduleRequest(source=source), viewer
        ),
        ai_vectors.delete_schedule("shared", viewer),
    )
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            _run(call)
        assert exc.value.status_code == 403


def test_non_admin_write_requires_collection_ownership():
    owner = {"id": USER_ID, "role": "viewer"}
    other = {"id": OTHER_ID, "role": "viewer"}
    conn = _CollectionConn(owner_id=uuid.UUID(USER_ID))

    assert _run(
        ai_vectors._collection_id(conn, "owned", owner, write=True)
    ) == "collection-id"
    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors._collection_id(conn, "owned", other, write=True))
    assert exc.value.status_code == 403


class _CreateConn:
    def __init__(self, duplicate=False):
        self.duplicate = duplicate
        self.queries = []

    async def execute(self, query, *args):
        self.queries.append(query)
        if self.duplicate and query.lstrip().startswith("INSERT INTO ai_collections"):
            raise ai_vectors.asyncpg.UniqueViolationError("duplicate name")
        return "INSERT 0 1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def test_create_collection_never_updates_existing_name_and_returns_409(monkeypatch):
    conn = _CreateConn(duplicate=True)
    monkeypatch.setattr(ai_vectors, "get_db_pool", lambda: _async_value(_Pool(conn)))
    monkeypatch.setattr(ai_vectors, "ensure_vector_schema", lambda pool: _async_value(None))

    with pytest.raises(HTTPException) as exc:
        _run(ai_vectors.create_collection(
            ai_vectors.CollectionCreate(name="existing", description="replacement"),
            {"id": USER_ID, "role": "viewer"},
        ))
    assert exc.value.status_code == 409
    assert all("ON CONFLICT" not in query.upper() for query in conn.queries)


def test_scan_bucket_tolerates_error_instead_of_raising():
    """One unlistable bucket must degrade to a per-bucket error marker, not raise —
    otherwise a single restricted bucket 500s the whole /storage/overview."""
    class _Paginator:
        def paginate(self, **kwargs):
            raise RuntimeError("access denied")

    class _S3:
        def get_paginator(self, name):
            return _Paginator()

    stat = storage._scan_bucket(_S3(), {"Name": "private"})
    assert stat.name == "private"
    assert stat.error is not None and "access denied" in stat.error
    assert stat.object_count == 0 and stat.total_size_bytes == 0


def test_collect_overview_survives_one_bad_bucket(monkeypatch):
    """A mix of a readable and an unlistable bucket yields partial stats + an error
    marker, never an exception."""
    class _Paginator:
        def paginate(self, **kwargs):
            if kwargs.get("Bucket") == "bad":
                raise RuntimeError("denied")
            return [{"Contents": [{"Size": 10}, {"Size": 5}]}]

    class _S3:
        def get_paginator(self, name):
            return _Paginator()
        def list_buckets(self):
            return {"Buckets": [{"Name": "ok"}, {"Name": "bad"}]}

    monkeypatch.setattr(storage, "S3_ENDPOINT", "http://seaweed", raising=False)
    monkeypatch.setattr(storage, "get_s3_client", lambda: _S3())
    overview = storage._collect_overview()
    by_name = {b.name: b for b in overview.buckets}
    assert by_name["ok"].total_size_bytes == 15
    assert by_name["bad"].error is not None
    assert overview.total_object_count == 2  # only the readable bucket contributes


def test_storage_object_upload_is_admin_gated():
    assert auth.require_admin in _route_dependencies(
        storage.router, "/storage/objects/{bucket}/{key:path}", "PUT"
    )


def test_collection_name_validation_rejects_injection_and_junk():
    """create_collection must 400 on names that aren't a tidy URL-safe token,
    before any DB access."""
    # NB: leading/trailing spaces are trimmed (valid), so these are genuinely-invalid
    # tokens: control chars/quotes, slash, glob char, empty, over-length, non-ASCII.
    bad_names = [
        'x\n"""', "a/b", "bad*char", "semi;colon", "", "x" * 65, "드롭",
    ]
    for name in bad_names:
        with pytest.raises(HTTPException) as exc:
            _run(ai_vectors.create_collection(
                ai_vectors.CollectionCreate(name=name, description=None),
                {"id": USER_ID, "role": "admin"},
            ))
        assert exc.value.status_code == 400, name


def test_mlflow_experiment_mutations_are_admin_gated():
    pytest.importorskip("mlflow")
    from app.api import mlflow_integration
    assert auth.require_admin in _route_dependencies(
        mlflow_integration.router, "/mlflow/experiments/{experiment_id}", "DELETE"
    )
    assert auth.require_admin in _route_dependencies(
        mlflow_integration.router, "/mlflow/experiments/{experiment_id}/archive", "POST"
    )
