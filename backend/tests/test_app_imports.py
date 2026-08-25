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
