"""Operational-flow regressions that import no application or live-service clients."""

import ast
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).parents[2]
BACKEND = ROOT / "backend/app/api"


def _run(coro):
    return asyncio.run(coro)


def _tree(filename: str):
    return ast.parse((BACKEND / filename).read_text())


def _load_functions(filename: str, names: tuple[str, ...], namespace=None):
    """Compile only selected top-level functions, with route decorators removed."""
    tree = _tree(filename)
    functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            functions.append(node)
    assert {node.name for node in functions} == set(names)
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {"Any": Any, **dict(namespace or {})}
    exec(compile(module, filename, "exec"), scope)
    return scope


def _route_dependency_name(tree, path: str, method: str):
    decorator_name = method.lower()
    for function in (node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)):
        for decorator in function.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == decorator_name
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and decorator.args[0].value == path
            ):
                continue
            dependencies = next(
                (keyword.value for keyword in decorator.keywords if keyword.arg == "dependencies"),
                None,
            )
            if not isinstance(dependencies, ast.List) or len(dependencies.elts) != 1:
                return None
            depends = dependencies.elts[0]
            if not isinstance(depends, ast.Call) or not depends.args:
                return None
            target = depends.args[0]
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                return f"{target.value.id}.{target.attr}"
    return None


def test_generated_sync_dag_uses_runtime_internal_key(monkeypatch):
    functions = _load_functions("connectors.py", ("_generate_sync_dag",))
    monkeypatch.setenv("DATAPOND_INTERNAL_KEY", "must-not-be-generated-into-dag")

    dag = functions["_generate_sync_dag"](
        "connector-id", "Orders", "0 * * * *"
    )

    assert 'os.getenv("DATAPOND_INTERNAL_KEY", "").strip()' in dag
    assert 'headers={"X-Internal-Key": internal_api_key}' in dag
    assert "DATAPOND_INTERNAL_KEY is required for scheduled connector sync" in dag
    assert "resp.raise_for_status()" in dag
    assert "must-not-be-generated-into-dag" not in dag

    chart = (ROOT / "helm/datapond/templates/airflow-deployment.yaml").read_text()
    secret_env = """- name: DATAPOND_INTERNAL_KEY
          valueFrom:
            secretKeyRef:
              name: datapond-secrets
              key: INTERNAL_API_KEY"""
    assert secret_env in chart
    assert "must-not-be-generated-into-dag" not in chart


def test_service_http_routes_have_explicit_auth_dependencies():
    tree = _tree("services.py")
    user_routes = (
        ("/services/{service}", "GET"),
        ("/services/{service}/pods", "GET"),
        ("/services/{service}/pods/{pod}/describe", "GET"),
        ("/services/{service}/logs", "GET"),
        ("/services/{service}/metrics", "GET"),
        ("/services/{service}/metrics/history", "GET"),
        ("/services/{service}/health", "GET"),
        ("/services/{service}/events", "GET"),
    )
    for path, method in user_routes:
        assert _route_dependency_name(tree, path, method) == "auth.require_user"

    admin_routes = (
        ("/services/{service}/restart", "POST"),
        ("/services/{service}/scale", "POST"),
        ("/services/{service}/pods/{pod}", "DELETE"),
    )
    for path, method in admin_routes:
        assert _route_dependency_name(tree, path, method) == "auth.require_admin"


def _service_functions(core_v1):
    class ApiException(Exception):
        def __init__(self, status=None):
            self.status = status

    scope = _load_functions(
        "services.py",
        (
            "get_service_label_selector",
            "_pod_belongs_to_service",
            "describe_pod",
            "get_service_logs",
            "delete_service_pod",
        ),
        {
            "core_v1": core_v1,
            "NAMESPACE": "datapond",
            "HTTPException": HTTPException,
            "ApiException": ApiException,
            "Query": lambda default, **kwargs: default,
            "Optional": __import__("typing").Optional,
            "ServiceLogsResponse": lambda **kwargs: kwargs,
            "datetime": datetime,
            "logger": SimpleNamespace(error=lambda *args, **kwargs: None),
        },
    )
    scope["_ApiException"] = ApiException
    return scope


def test_delete_pod_rejects_wrong_service_label():
    class FakeCoreV1:
        deleted = False

        def read_namespaced_pod(self, name, namespace):
            return SimpleNamespace(
                metadata=SimpleNamespace(name=name, labels={"app": "other-service"})
            )

        def delete_namespaced_pod(self, name, namespace):
            self.deleted = True

    fake = FakeCoreV1()
    functions = _service_functions(fake)

    with pytest.raises(HTTPException) as exc:
        _run(functions["delete_service_pod"]("backend", "other-pod"))

    assert exc.value.status_code == 404
    assert fake.deleted is False


def test_delete_pod_allows_matching_service_label():
    class FakeCoreV1:
        deleted = []

        def read_namespaced_pod(self, name, namespace):
            return SimpleNamespace(
                metadata=SimpleNamespace(name=name, labels={"app": "backend"})
            )

        def delete_namespaced_pod(self, name, namespace):
            self.deleted.append((name, namespace))

    fake = FakeCoreV1()
    functions = _service_functions(fake)

    result = _run(functions["delete_service_pod"]("backend", "backend-abc"))

    assert result == {"status": "deleted", "service": "backend", "pod": "backend-abc"}
    assert fake.deleted == [("backend-abc", "datapond")]


class _Credentials:
    def __init__(self, scheme, credentials):
        self.scheme = scheme
        self.credentials = credentials


class _Disconnect(Exception):
    pass


class _FakeWebSocket:
    def __init__(self, cookies, headers=None):
        self.cookies = cookies
        self.headers = headers or {}
        self.closed = []

    async def close(self, code):
        self.closed.append(code)


def _websocket_functions(get_current_user):
    import os as _os
    auth = SimpleNamespace(get_current_user=get_current_user)
    return _load_functions(
        "services.py",
        ("_safe_websocket_close", "_ws_origin_allowed", "_authorize_log_websocket"),
        {
            "WebSocket": object,
            "WebSocketDisconnect": _Disconnect,
            "HTTPAuthorizationCredentials": _Credentials,
            "auth": auth,
            "os": _os,
        },
    )


def test_websocket_auth_uses_cookie_and_rejects_missing_or_invalid_user():
    seen = []

    async def invalid_user(credentials):
        seen.append(credentials.credentials)
        return None

    functions = _websocket_functions(invalid_user)
    missing = _FakeWebSocket({})
    assert _run(functions["_authorize_log_websocket"](missing)) is False
    assert missing.closed == [4401]

    invalid = _FakeWebSocket({"datapond_token": "bad-token"})
    assert _run(functions["_authorize_log_websocket"](invalid)) is False
    assert seen == ["bad-token"]
    assert invalid.closed == [4401]


def test_websocket_auth_requires_admin_and_never_uses_query_token():
    async def viewer(credentials):
        return {"id": "user-id", "role": "viewer"}

    functions = _websocket_functions(viewer)
    websocket = _FakeWebSocket({"datapond_token": "viewer-token"})
    assert _run(functions["_authorize_log_websocket"](websocket)) is False
    assert websocket.closed == [4403]

    async def admin(credentials):
        return {"id": "admin-id", "role": "admin"}

    functions = _websocket_functions(admin)
    allowed = _FakeWebSocket({"datapond_token": "admin-token"})
    assert _run(functions["_authorize_log_websocket"](allowed)) is True
    assert allowed.closed == []

    source = ast.unparse(
        next(
            node
            for node in _tree("services.py").body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "stream_logs"
        )
    )
    assert "query_params" not in source
    assert source.index("_authorize_log_websocket") < source.index("websocket.accept")


def test_websocket_rejects_cross_site_origin_before_auth():
    async def admin(credentials):
        return {"id": "admin-id", "role": "admin"}

    functions = _websocket_functions(admin)
    # Cross-site Origin (host != request Host) is rejected before the cookie/admin
    # check even for a would-be admin — defense in depth against CSWSH.
    cross = _FakeWebSocket(
        {"datapond_token": "admin-token"},
        headers={"origin": "https://evil.example", "host": "datapond.example"},
    )
    assert _run(functions["_authorize_log_websocket"](cross)) is False
    assert cross.closed == [4403]

    # Same-origin (Origin host == Host) passes the origin gate and proceeds to admin.
    same = _FakeWebSocket(
        {"datapond_token": "admin-token"},
        headers={"origin": "https://datapond.example", "host": "datapond.example"},
    )
    assert _run(functions["_authorize_log_websocket"](same)) is True
    assert same.closed == []


def test_streaming_preview_returns_columns_and_array_rows():
    def execute(sql):
        assert sql == "SELECT * FROM events_mv LIMIT 2"
        return [
            {"event_id": 1, "kind": "open"},
            {"event_id": 2, "kind": "close"},
        ]

    functions = _load_functions(
        "streaming.py",
        ("_serialize", "preview_view"),
        {"datetime": datetime, "_execute": execute, "HTTPException": HTTPException},
    )

    result = _run(functions["preview_view"]("events_mv", limit=2))

    assert result == {
        "columns": ["event_id", "kind"],
        "rows": [[1, "open"], [2, "close"]],
        "row_count": 2,
        "count": 2,
    }


def test_backend_rbac_mutations_are_narrowly_scoped():
    rbac = (ROOT / "helm/datapond/templates/rbac-backend.yaml").read_text()

    assert 'resources: ["pods"]\n    verbs: ["delete"]' in rbac
    assert 'resources: ["deployments"]\n    verbs: ["patch", "update"]' in rbac
    assert 'resources: ["deployments", "statefulsets"]\n    verbs: ["get", "list", "watch"]' in rbac
    assert 'resources: ["pods", "pods/log", "services", "persistentvolumeclaims"]\n    verbs: ["get", "list", "watch"]' in rbac


def test_describe_and_explicit_logs_reject_wrong_service_pod_identically():
    class FakeCoreV1:
        events_read = False
        logs_read = False

        def read_namespaced_pod(self, name, namespace):
            return SimpleNamespace(
                metadata=SimpleNamespace(name=name, labels={"app": "other-service"})
            )

        def list_namespaced_event(self, **kwargs):
            self.events_read = True
            return SimpleNamespace(items=[])

        def read_namespaced_pod_log(self, **kwargs):
            self.logs_read = True
            return "secret logs"

    fake = FakeCoreV1()
    functions = _service_functions(fake)

    failures = []
    for call in (
        functions["describe_pod"]("backend", "other-pod"),
        functions["get_service_logs"]("backend", lines=25, pod="other-pod"),
    ):
        with pytest.raises(HTTPException) as exc:
            _run(call)
        failures.append((exc.value.status_code, exc.value.detail))

    assert failures == [
        (404, "Pod not found: other-pod"),
        (404, "Pod not found: other-pod"),
    ]
    assert fake.events_read is False
    assert fake.logs_read is False


def test_explicit_service_logs_verify_pod_before_reading_logs():
    class FakeCoreV1:
        calls = []

        def read_namespaced_pod(self, name, namespace):
            self.calls.append(("pod", name, namespace))
            return SimpleNamespace(metadata=SimpleNamespace(labels={"app": "backend"}))

        def read_namespaced_pod_log(self, name, namespace, tail_lines):
            self.calls.append(("logs", name, namespace, tail_lines))
            return "line one\nline two"

    fake = FakeCoreV1()
    functions = _service_functions(fake)
    result = _run(functions["get_service_logs"]("backend", lines=25, pod="backend-abc"))

    assert result["service"] == "backend"
    assert result["pod"] == "backend-abc"
    assert result["lines"] == ["line one", "line two"]
    assert fake.calls == [
        ("pod", "backend-abc", "datapond"),
        ("logs", "backend-abc", "datapond", 25),
    ]


def _load_system_info_handler(k8s_client, cache):
    path = ROOT / "backend/main.py"
    tree = ast.parse(path.read_text())
    node = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_system_info"
    )
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {
        "asyncio": asyncio,
        "time": __import__("time"),
        "k8s_client": k8s_client,
        "_sysinfo_cache": cache,
        "_SYSINFO_TTL": 15.0,
        "_K8S_TIMEOUT": 1.0,
        "_log": SimpleNamespace(warning=lambda *args, **kwargs: None),
        "HTTPException": HTTPException,
    }
    exec(compile(module, str(path), "exec"), scope)
    return scope["get_system_info"]


def test_system_info_initial_failure_is_503_but_cached_fallback_remains():
    class FailingK8s:
        @staticmethod
        def get_system_info():
            raise RuntimeError("cluster unavailable")

    empty_cache = {"data": None, "ts": 0.0}
    handler = _load_system_info_handler(FailingK8s, empty_cache)
    with pytest.raises(HTTPException) as exc:
        _run(handler())
    assert exc.value.status_code == 503
    assert exc.value.detail == "Kubernetes system information is unavailable"

    cached = {"data": {"node": {"name": "last-known"}}, "ts": 0.0}
    handler = _load_system_info_handler(FailingK8s, cached)
    assert _run(handler()) == cached["data"]


def test_service_viewer_ui_hides_admin_mutations_and_streaming():
    page = (ROOT / "frontend/app/services/[id]/page.tsx").read_text()
    viewer = (ROOT / "frontend/components/services/logs-viewer.tsx").read_text()

    assert 'const [isAdmin] = useState(() => getUser()?.role === "admin")' in page
    assert "{isAdmin && !isManaged && (" in page
    assert "onDeletePod={isAdmin ? handleDeletePod : undefined}" in page
    assert "canStream={isAdmin}" in page
    assert "if (!isAdmin) return" in page
    assert "canStream?: boolean" in viewer
    assert "{canStream && (" in viewer
    assert "onToggleStream(!isStreaming)" in viewer
    assert "downloadLogs" in viewer  # static HTTP logs remain usable by viewers


def test_sidebar_sign_out_is_keyboard_visible_with_focus_ring():
    sidebar = (ROOT / "frontend/components/app-sidebar.tsx").read_text()

    assert "group-focus-within:opacity-100" in sidebar
    assert "focus-visible:opacity-100" in sidebar
    assert "focus-visible:ring-2" in sidebar
    assert "focus-visible:ring-ring" in sidebar
    assert 'aria-label="Sign out"' in sidebar
