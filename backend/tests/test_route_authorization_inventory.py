"""Every mutating route must be gated. This test is the gate on the gate.

Closing 55 routes once is worthless if the 56th arrives ungated. So the check does
not name routes — it walks the application's own route graph and requires that each
mutating endpoint carries an authorization dependency, with a written-down exception
list for the handful that genuinely cannot have one.

The exception list is the point. A route may only skip authorization by being added
here, in a commit someone reviews, with a reason. It cannot skip by omission.
"""
import pytest

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Routes that are correctly reachable without a permission, and why.
#
# Three kinds only:
#   public      — the caller has no identity yet; this is how they get one.
#   self-scoped — acts solely on the caller's own account, so a permission would
#                 mean "may you edit yourself", which is not a thing a role decides.
#   per-object  — authorization is enforced against the specific object, not the
#                 role, so there is no permission that would express it.
UNGATED_BY_DESIGN = {
    ("POST", "/api/auth/login"): "public — establishes identity",
    ("POST", "/api/auth/logout"): "public — ends a session, needs no privilege",
    ("POST", "/api/auth/forgot-password"): "public — pre-authentication recovery",
    ("POST", "/api/auth/reset-password"): "public — consumes a mailed token",
    ("POST", "/api/auth/change-password"): "self-scoped — the caller's own password",
    ("PATCH", "/api/auth/me"): "self-scoped — the caller's own profile",
    ("POST", "/api/auth/webauthn/authenticate/begin"): "public — passwordless login, step 1",
    ("POST", "/api/auth/webauthn/authenticate/complete"): "public — passwordless login, step 2",
    ("POST", "/api/auth/webauthn/register/begin"): "self-scoped — enrols the caller's own key",
    ("POST", "/api/auth/webauthn/register/complete"): "self-scoped — enrols the caller's own key",
    ("DELETE", "/api/auth/webauthn/credentials/{cred_id}"): "self-scoped — the caller's own key",

    # A third kind, and the only one: authorization exists but is per-object rather
    # than per-role, so no permission can express it. app/chat/gate.py refuses any
    # caller who is not the user who proposed that invocation — a stricter rule than
    # a permission, since holding the permission is not enough.
    ("POST", "/api/chat/actions/{invocation_id}/approve"): "per-invocation owner check in chat/gate.py",
    ("POST", "/api/chat/actions/{invocation_id}/reject"): "per-invocation owner check in chat/gate.py",
}


def _authorization_of(route) -> set:
    """Every authorization marker reachable from this route's dependency tree.

    Walks the tree rather than reading the signature: a gate is equally valid on the
    decorator's `dependencies=[...]`, and an earlier version of this inventory that
    only read signatures reported 13 open routes where there were 55.
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


def _mutating_routes():
    import main
    for route in main.app.routes:
        methods = getattr(route, "methods", set()) & MUTATING
        if not methods or not hasattr(route, "dependant"):
            continue
        for method in sorted(methods):
            yield method, route.path, route


def test_every_mutating_route_is_authorized():
    open_routes = [
        f"{method} {path}"
        for method, path, route in _mutating_routes()
        if (method, path) not in UNGATED_BY_DESIGN and not _authorization_of(route)
    ]
    assert not open_routes, (
        f"{len(open_routes)} mutating route(s) require only authentication. Add an "
        "authorization dependency, or an entry in UNGATED_BY_DESIGN with a reason:\n  "
        + "\n  ".join(sorted(open_routes))
    )


def test_the_exception_list_has_no_stale_entries():
    """An exception outliving its route is a licence nobody notices is still granted."""
    live = {(method, path) for method, path, _ in _mutating_routes()}
    stale = sorted(f"{m} {p}" for m, p in UNGATED_BY_DESIGN if (m, p) not in live)
    assert not stale, f"UNGATED_BY_DESIGN names routes that no longer exist: {stale}"


def test_a_gated_route_is_actually_detected():
    """Guards the detector itself: if the marker stopped being set, the inventory
    would report zero open routes and pass while enforcing nothing."""
    gated = [f"{m} {p}" for m, p, r in _mutating_routes() if _authorization_of(r)]
    assert len(gated) > 20, f"detector found only {len(gated)} gated routes"
