"""The auditor role could not read what its own permissions name — B1.

`app/permissions.py` grants `auditor` both `governance:read` and `audit:read`, and
several governance/audit GET routes already carry a `require_permission(...)`
dependency naming one of those two strings — the route's own declaration that a
holder of that permission may call it. But the handler body then called
`_require_admin(user)`, which checks only `role == "admin"` and nothing else. The
permission matrix said an auditor may read the audit log and the policy list, and
the code said no anyway, because the dependency was never wired to the check that
actually ran. This file is the regression test for that disagreement: it reads the
governance router's own route graph and source, the same way
test_route_authorization_inventory.py does for mutating routes, so a future GET
handler can't reintroduce a body-level admin check that quietly overrides whatever
permission its decorator advertises.
"""
import inspect

import main

MUTATING = {"POST", "PATCH", "DELETE"}


def _governance_routes():
    for route in main.app.routes:
        if not hasattr(route, "dependant") or not hasattr(route, "endpoint"):
            continue
        if not route.path.startswith("/api/governance"):
            continue
        for method in sorted(getattr(route, "methods", set())):
            yield method, route.path, route


def _authorization_markers(route) -> set:
    """Every authorization marker reachable from this route's dependency tree.

    Mirrors test_route_authorization_inventory.py's walk: a permission is equally
    valid on the decorator's `dependencies=[...]` as on a signature parameter, and
    reading only the signature would miss every route fixed by this task, since all
    of them declare `require_permission(...)` in `dependencies=[...]`.
    """
    found, seen = set(), set()

    def walk(dependant):
        if id(dependant) in seen:
            return
        seen.add(id(dependant))
        marker = getattr(dependant.call, "__datapond_authorization__", None)
        if marker:
            found.add(marker)
        for sub in dependant.dependencies:
            walk(sub)

    walk(route.dependant)
    return found


# GET routes that were never behind _require_admin and are not part of the
# auditor/permission mismatch this task fixes. Naming them is the same discipline
# as UNGATED_BY_DESIGN in test_route_authorization_inventory.py: an exemption is a
# decision recorded in a reviewed commit, not code nobody looked at.
OPEN_BY_DESIGN = {
    ("GET", "/api/governance/stats"): "no _require_admin before this task; any "
        "authenticated user could already reach it — a separate, pre-existing gap",
    ("GET", "/api/governance/pii-report"): "no _require_admin before this task; "
        "same pre-existing gap as /governance/stats",
    ("GET", "/api/governance/rls/sensitive-tables"): "documented auth-optional in "
        "its own docstring — the Jupyter DuckDB guard calls it pre-auth",
}

# Read-modify-delete routes over rls_policies / column_masking_policies / the Trino
# ACL configmap. B1 fixes reads only; these must still refuse anyone but admin.
WRITE_ROUTES = {
    ("POST", "/api/governance/rls/policies"),
    ("PATCH", "/api/governance/rls/policies/{policy_id}"),
    ("DELETE", "/api/governance/rls/policies/{policy_id}"),
    ("POST", "/api/governance/masking/policies"),
    ("DELETE", "/api/governance/masking/policies/{policy_id}"),
    ("POST", "/api/governance/rls/trino-rules/apply"),
}


def test_no_get_route_in_governance_calls_require_admin():
    """A GET route gated by `require_permission("governance:read")` or
    `"audit:read"` that also calls `_require_admin` in its body is not
    double-gated, it is mis-gated: the permission dependency runs first and passes
    the auditor through, and then the body check rejects the same request anyway.
    Before this fix, six such routes existed (audit-log, audit-stream, roles,
    rls/policies list, masking/policies list, trino-rules, ai-safety) and every one
    of them turned an auditor's permitted read into a 403.
    """
    offenders = []
    for method, path, route in _governance_routes():
        if method != "GET":
            continue
        src = inspect.getsource(route.endpoint)
        if "_require_admin" in src:
            offenders.append(path)
    assert not offenders, (
        "GET route(s) still call _require_admin in the handler body, overriding "
        f"whatever permission their dependency advertises: {sorted(offenders)}"
    )


def test_every_governance_get_route_declares_its_permission():
    """Deleting the `_require_admin` call is only a fix if the route's own
    dependency graph still carries the permission that call used to enforce.
    Removing the check without adding `require_permission(...)` doesn't correct
    "wrong role required" to "the right role required" — it silently downgrades the
    route to "any authenticated user", which nobody decided on purpose. A route may
    skip the permission dependency only by being named in OPEN_BY_DESIGN, with a
    reason, same as the mutating-route inventory's exception list.
    """
    unmarked = [
        path
        for method, path, route in _governance_routes()
        if method == "GET"
        and (method, path) not in OPEN_BY_DESIGN
        and not _authorization_markers(route)
    ]
    assert not unmarked, (
        "GET route(s) carry neither _require_admin nor a require_permission "
        f"dependency, and are not in OPEN_BY_DESIGN: {sorted(unmarked)}"
    )


def test_policy_write_routes_still_require_admin():
    """B1 only touches reads. A change that, while stripping the read-side
    `_require_admin` calls, also strips one from a write handler by mistake would
    let anyone holding `governance:write` alone create or delete RLS and masking
    policies as themselves — no longer the audited admin-attributed action
    `_audit_policy_event` was written to record. This is the tripwire for that
    mistake: every policy-mutating route must still name `_require_admin` in its
    own source.
    """
    found = set()
    missing = []
    for method, path, route in _governance_routes():
        if (method, path) not in WRITE_ROUTES:
            continue
        found.add((method, path))
        src = inspect.getsource(route.endpoint)
        if "_require_admin" not in src:
            missing.append(f"{method} {path}")
    assert not missing, f"write route(s) lost their admin gate: {missing}"
    assert found == WRITE_ROUTES, (
        f"expected write route(s) not found in the app (renamed/removed?): "
        f"{WRITE_ROUTES - found}"
    )
