"""Every router mounted in main.py must actually be imported.

`app.include_router(service_accounts_router, ...)` shipped with no matching import.
The whole suite passed — nothing imports main.py, because module-level side effects
(kube config, an MLflow client, a SQLAlchemy engine that connects) make it
unimportable outside the cluster — and the pod crash-looped on startup with
`NameError: name 'service_accounts_router' is not defined`.

Importing main is the test one would want, and it is blocked by those side effects.
This reads the module instead: every name passed to include_router must be bound at
module level. It catches exactly the failure that occurred, deterministically and
anywhere, without waiting for the larger refactor.
"""
import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"


def _module():
    return ast.parse(MAIN.read_text())


def _bound_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _included_routers(tree):
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "include_router" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name):
                out.append((first.id, node.lineno))
    return out


def test_every_mounted_router_is_imported():
    tree = _module()
    bound = _bound_names(tree)
    missing = [(name, line) for name, line in _included_routers(tree) if name not in bound]
    assert not missing, (
        "main.py mounts routers it never imports — the app will not start: "
        + ", ".join(f"{n} (line {ln})" for n, ln in missing)
    )


def test_main_mounts_a_plausible_number_of_routers():
    """A guard against an include_router block being deleted wholesale."""
    assert len(_included_routers(_module())) >= 15


def test_main_parses():
    _module()


# ── the test the static check was standing in for ─────────────────────────────

def test_the_application_imports_outside_a_cluster():
    """`import main` must work with no kube config, no database, and no MLflow.

    It did not: `client.CoreV1Api()` in services.py and `K8sClient()` in k8s_client.py
    both raise without a kube config, so nothing in the suite could import the app —
    which is how a router mounted without its import reached production and
    crash-looped. Nothing needs a cluster client until a request arrives.
    """
    import main

    assert main.app is not None


def test_every_route_group_is_mounted():
    import main

    paths = {r.path for r in main.app.routes}
    for path in ("/api/capabilities", "/api/queries/execute", "/api/service-accounts",
                 "/api/catalog/relationships", "/api/me/permissions",
                 "/api/chat", "/api/chat/actions"):
        assert path in paths, f"{path} is not mounted"


def test_importing_the_app_does_not_construct_a_cluster_client():
    """The lazy wrappers must stay lazy — an eager one reintroduces the whole problem."""
    import k8s_client
    import main  # noqa: F401
    from app.api import services

    assert k8s_client._LazyK8sClient._instance is None
    assert services._k8s == {} or "CoreV1Api" not in services._k8s
