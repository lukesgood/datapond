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

B1 found, and deliberately did not fix, a second problem while doing the above:
`/governance/stats` and `/governance/pii-report` carried no authorization dependency
at all — not even the wrong one — and `/governance/rls/preview` kept its
`require_permission("governance:read")` route dependency but *also* still called
`_require_admin(user)` in the body, the exact double-gated-but-mis-gated shape this
file's first two tests police for GET routes, just on a POST that those tests never
walk. B1 recorded all three in `OPEN_BY_DESIGN` rather than widen its own scope; B5
is that follow-up, and its tests are appended below.
"""
import asyncio
import inspect

import main
from app.api import governance as gov

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


# ── B5: stats / pii-report / rls-preview ───────────────────────────────────────

# The three routes B1 named in OPEN_BY_DESIGN rather than fix. B5 closes them, so
# this is the inverse of the exemption list above: these three must now carry a
# real authorization marker.
B5_ROUTES = {
    ("GET", "/api/governance/stats"),
    ("GET", "/api/governance/pii-report"),
    ("POST", "/api/governance/rls/preview"),
}


def test_stats_pii_report_and_rls_preview_now_declare_governance_read():
    """These three were the reason B5 exists: `stats` and `pii-report` carried no
    authorization dependency at all — the plain "nobody checked" gap, not the
    "checked the wrong thing" gap `_require_admin` produces elsewhere in this file —
    and `rls/preview` carried the right route dependency already but a stray body
    call undid it (see below). All three must now surface
    `require_permission("governance:read")` in their own dependency tree, the same
    marker the other governance reads carry, so an auditor can reach a PII report
    the same way they can already reach the audit log.
    """
    missing = []
    for method, path, route in _governance_routes():
        if (method, path) not in B5_ROUTES:
            continue
        if "governance:read" not in _authorization_markers(route):
            missing.append(f"{method} {path}")
    assert not missing, (
        f"route(s) still lack a governance:read dependency: {missing}"
    )
    found = {(m, p) for m, p, _r in _governance_routes() if (m, p) in B5_ROUTES}
    assert found == B5_ROUTES, (
        f"expected route(s) not found in the app (renamed/removed?): "
        f"{B5_ROUTES - found}"
    )


def test_rls_preview_no_longer_body_gates_on_admin():
    """`rls/preview` only simulates a rewrite — it changes nothing — so it belongs
    with the other governance reads, gated on `governance:read`, not walled off to
    `role == "admin"` the way the policy *write* routes correctly still are. Its
    route dependency already said `governance:read`; the leftover
    `await _require_admin(user)` in the handler body silently overrode that promise
    for every caller who was not `admin`, the same disagreement
    test_no_get_route_in_governance_calls_require_admin polices for GET routes. This
    is that same tripwire for the one POST route neither GET-only test walks.
    """
    src = inspect.getsource(gov.preview_rls)
    assert "_require_admin" not in src, (
        "rls/preview still calls _require_admin in its body, overriding the "
        "governance:read dependency its own decorator advertises"
    )


def test_rls_preview_still_previews_for_a_permitted_non_admin_caller():
    """Removing the body-level admin check is only a fix if the route still works —
    a caller holding `governance:read` but not `role == "admin"` (an auditor, say)
    must still get back a preview, not a silent no-op or an exception thrown from
    code that used to assume `_require_admin` had already run. Calling the handler
    coroutine directly bypasses the `require_permission(...)` dependency the same
    way test_governance_audit_admin.py does — a dependency runs before the handler
    body, so this is purely a test of what the body does once a permitted caller
    reaches it. With no policies and no masks loaded, `rls.engine.enforce` is a
    documented byte-for-byte passthrough, which makes the expected response exact
    rather than approximate.
    """
    class _FakeLoader:
        async def load_policies(self):
            return []

        async def load_masks(self):
            return []

    original_loader = gov._rls_loader
    gov._rls_loader = _FakeLoader()
    try:
        body = gov.RlsPreviewIn(sql="SELECT 1", roles=["auditor"], attributes={})
        non_admin_user = {"user_id": "u1", "username": "auditor1", "role": "auditor"}
        result = asyncio.new_event_loop().run_until_complete(
            gov.preview_rls(body, user=non_admin_user)
        )
    finally:
        gov._rls_loader = original_loader

    assert result == {
        "allowed": True,
        "rewritten_sql": "SELECT 1",
        "applied_policies": [],
        "applied_masks": [],
        "tables": [],
    }


def test_open_by_design_entries_all_carry_a_written_reason():
    """The exemption list is the point, not a loophole: a route may skip
    `governance:read` only by being named here, with a reason someone reviewed, the
    same discipline UNGATED_BY_DESIGN enforces for mutating routes. B5 shrinks this
    list from three entries to (at most) the one that was never a gating bug in the
    first place; this test is what stops the next unauthenticated route from being
    "fixed" by quietly re-adding itself here with no explanation.
    """
    for key, reason in OPEN_BY_DESIGN.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 15, (
            f"OPEN_BY_DESIGN entry {key} has no real reason recorded: {reason!r}"
        )
