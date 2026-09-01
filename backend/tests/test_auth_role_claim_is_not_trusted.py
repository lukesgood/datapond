"""A forged role claim must not survive contact with the database.

On 2026-08-24 someone proving out a new permission gate on the live deployment
minted a JWT with `role: "viewer"` for the *admin* account's user id, sent
`DROP TABLE products` through the query endpoint, and the statement ran — a real
table, dropped. The permission gate was not broken. `_recheck_user`
(app/api/auth.py, ~line 187) refreshes `role` from the `users` row on every
authenticated request and overwrites whatever the token claims, before any
permission check runs. A "viewer" claim riding on the admin account's id resolves
to admin, because the id is what is authoritative and the claim is not. That is
exactly what let the DROP TABLE through, and it is *correct* — the token's own
claims are unrevocable for up to 24h otherwise, so trusting them at all would mean
a demoted or deactivated account keeps acting on its old privileges until the JWT
expires.

Until now this was proved by reading `_recheck_user`. These tests drive it
directly against a fake pool/connection, so a future change that starts trusting
the token's role claim — "the DB round-trip is slow", "we already checked this
upstream", whatever the reasoning — fails the suite instead of shipping to a
customer and being discovered the same way this one was: live, with DDL.
"""
import asyncio
import re
import uuid
from types import SimpleNamespace

import main
from app.api import auth as auth_module
from app.api.auth import require_user

VALID_UID = "00000000-0000-0000-0000-0000000000ee"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── fakes (same shape as tests/test_auth_recheck.py) ─────────────────────────

class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *a, **k):
        return self._row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, row):
        self._row = row

    def acquire(self, *a, **k):   # real asyncpg Pool.acquire accepts timeout=
        return _FakeConn(self._row)


def _patch_pool(monkeypatch, row):
    async def _get_pool():
        return _FakePool(row)
    monkeypatch.setattr(auth_module, "_get_pool", _get_pool)


def _claims(role, uid=VALID_UID):
    return {"id": uid, "username": "someone", "role": role}


# ── 1. the incident itself: a claim higher than the database loses ──────────

def test_a_role_claim_higher_than_the_database_is_downgraded(monkeypatch):
    """The forged-token shape from the incident: token says admin, the users row
    says viewer. The permission check that runs after `_recheck_user` must see
    viewer, or the whole gate is theatre."""
    _patch_pool(monkeypatch, row={"is_active": True, "role": "viewer"})
    out = _run(auth_module._recheck_user(VALID_UID, _claims(role="admin")))
    assert out is not None
    assert out["role"] == "viewer", (
        "a token claiming 'admin' was not downgraded to the database's 'viewer' — "
        "this is the exact gap that let a forged claim run DROP TABLE live"
    )


# ── 2. the mirror image: a claim lower than the database also loses ─────────

def test_a_role_claim_lower_than_the_database_is_upgraded(monkeypatch):
    """This direction is what actually made the incident possible, and it is
    correct behaviour, not a bug: the token used to attack the gate claimed
    "viewer" for the *admin* account's id, and `_recheck_user` resolved it to
    admin — the id is real, the claim is not, in both directions. Do not "fix"
    this into trusting the lower claim. That would only trade one exploit for
    another: a stolen high-privilege token, hand-edited to look demoted, would
    then keep its real privileges for a session that believes it de-escalated,
    and nothing downstream would know to check twice."""
    _patch_pool(monkeypatch, row={"is_active": True, "role": "admin"})
    out = _run(auth_module._recheck_user(VALID_UID, _claims(role="viewer")))
    assert out is not None
    assert out["role"] == "admin"


# ── 3. inactive beats every claim, in either direction ───────────────────────

def test_an_inactive_user_is_rejected_no_matter_what_the_token_claims(monkeypatch):
    """A deactivated account must lose access before its up-to-24h JWT expires.
    The claimed role is irrelevant here — even a claim that matches the
    database's last-known role for that user does not save it once
    `is_active` is false."""
    _patch_pool(monkeypatch, row={"is_active": False, "role": "admin"})
    out = _run(auth_module._recheck_user(VALID_UID, _claims(role="admin")))
    assert out is None


# ── 4. inventory: does every write-shaped permission actually reach the recheck? ─

# "write-shaped" per the task this file exists for: anything ending `:write`,
# plus `query:write`, `user:manage`, `service:manage` (the last three don't end
# in `:write` textually but are the same kind of hazard — DDL, account takeover,
# infrastructure control).
_WRITE_SUFFIX = re.compile(r":write$")
_ALSO_WRITE_SHAPED = {"query:write", "user:manage", "service:manage"}


def _is_write_shaped(permission: str) -> bool:
    return bool(_WRITE_SUFFIX.search(permission)) or permission in _ALSO_WRITE_SHAPED


def _inspect(dependant):
    """Walk a route's dependency tree once, collecting every
    `__datapond_authorization__` marker (set by `require_permission`, see
    app/api/auth.py) and whether `require_user` itself is reachable anywhere in
    the tree — which is how the recheck actually happens, since `require_user`
    is the only place that calls `_recheck_user` (via `get_current_user`) or
    reuses its result from `request.state.user`.

    This walks the same `dependant.dependencies` structure
    tests/test_route_authorization_inventory.py uses, for the same reason: a
    marker on `dependencies=[...]` at the route decorator is exactly as valid as
    one on a function parameter, and reading signatures alone under-counts.
    """
    markers = set()
    has_require_user = False
    seen = set()

    def walk(d):
        nonlocal has_require_user
        if id(d) in seen:
            return
        seen.add(id(d))
        marker = getattr(d.call, "__datapond_authorization__", None)
        if marker:
            markers.add(marker)
        if d.call is require_user:
            has_require_user = True
        qualname = getattr(d.call, "__qualname__", "")
        if qualname.startswith(_REQUIRE_PERMISSION_OR_INTERNAL_GUARD_PREFIX):
            has_require_user = True
        for sub in d.dependencies:
            walk(sub)

    walk(dependant)
    return markers, has_require_user


# `require_permission_or_internal`'s guard is the one deliberate exception to "the
# marker means Depends(require_user) is in the tree": it must admit the scoped
# internal-automation principal *before* require_user ever runs — a
# Depends(require_user) node would resolve (and reject) an internal-key request
# before the guard's own internal check got a chance to run at all, taking a
# route like ingest-source's allowlisted internal-automation callback down. So it
# calls
# `require_user` as a plain function once it has decided the request isn't
# internal (see its docstring in app/api/auth.py), which this walk cannot see —
# only `test_require_permission_or_internal_reaches_require_user_when_not_internal`
# below proves that call actually happens, dynamically.
_REQUIRE_PERMISSION_OR_INTERNAL_GUARD_PREFIX = "require_permission_or_internal."


def _all_routes():
    return [r for r in main.app.routes if hasattr(r, "dependant")]


def test_every_permission_marked_write_shaped_reaches_require_user():
    """What this proves: for every route wired through `require_permission(...)`
    (the mechanism that sets `__datapond_authorization__`) with a write-shaped
    permission, `require_user` sits somewhere in that route's own FastAPI
    dependency graph — the actual, resolved graph the running app would build,
    not a hand-kept list of routes.

    What this does NOT prove: that `require_user` calling `_recheck_user`
    happens *before* the permission comparison at runtime (tests 1-3 above prove
    `_recheck_user`'s own behaviour; this test only proves the wiring exists).
    It also cannot see `require_permission`'s internal `Depends(require_user)`
    stop being declared and get replaced by something that reads `user["role"]`
    off a claims dict assembled without going through `require_user` at all —
    if that ever happens, this test still passes, because the marker and the
    `require_user` call would both still be present, just no longer the same
    identity's role. That gap is why tests 1-3 exist: they pin `_recheck_user`'s
    actual behaviour, not just its presence in a call graph.
    """
    checked = []
    for route in _all_routes():
        markers, has_require_user = _inspect(route.dependant)
        write_markers = {m for m in markers if _is_write_shaped(m)}
        if not write_markers:
            continue
        checked.append((route.path, write_markers))
        assert has_require_user, (
            f"{route.path} enforces {sorted(write_markers)} but require_user is not "
            "in its dependency graph — the permission would be checked against a "
            "role that was never rechecked against the database."
        )
    assert len(checked) > 10, (
        f"only found {len(checked)} write-shaped permission-marked routes — the "
        "detector is likely broken (test_a_gated_route_is_actually_detected in "
        "test_route_authorization_inventory.py hits this same failure mode)"
    )


# `query:write`, `user:manage`, and `settings:write` are never passed to
# `require_permission(...)`, so no route carries them as a `__datapond_authorization__`
# marker for the scan above to find. `query:write` is checked inline in
# app/api/queries.py against a `user` object the route resolves separately;
# `user:manage` and `settings:write` are enforced by the coarser `require_admin`
# gate, which is correct because admin is the only role `app/permissions.py` grants
# them to. Neither shows up in a call-graph walk as itself, so proving they reach
# `require_user` honestly means naming the routes that carry them — this list is
# the honest form the task description calls out, not a shortcut around one.
_NAMED_WRITE_SHAPED_ROUTES = {
    ("POST", "/api/queries/execute"):
        "query:write — classified inline against a user resolved by an explicit "
        "Depends(require_user) parameter, in addition to the query:run marker",
    ("PATCH", "/api/auth/users/{user_id}"): "user:manage — gated by require_admin",
    ("DELETE", "/api/auth/users/{user_id}"): "user:manage — gated by require_admin",
    ("PATCH", "/api/settings/system"): "settings:write — gated by require_admin",
}


def test_named_write_shaped_routes_without_a_permission_marker_still_require_user():
    """The three permissions that never appear as a `require_permission(...)`
    marker (see comment above), checked by name against the live route table.

    What this proves: today, these specific routes depend on `require_user`
    somewhere in their graph. What it does not prove: that no *other*, unnamed
    route enforces one of these three permissions without going through
    `require_user` — an omission here would be silent, which is the same honesty
    gap `UNGATED_BY_DESIGN` in test_route_authorization_inventory.py accepts for
    its own named exceptions.
    """
    live = {}
    for route in _all_routes():
        for method in getattr(route, "methods", set()):
            live[(method, route.path)] = route

    stale = [f"{m} {p}" for (m, p) in _NAMED_WRITE_SHAPED_ROUTES if (m, p) not in live]
    assert not stale, f"named routes no longer exist — update the list: {stale}"

    for (method, path), why in _NAMED_WRITE_SHAPED_ROUTES.items():
        _, has_require_user = _inspect(live[(method, path)].dependant)
        assert has_require_user, f"{method} {path} does not depend on require_user ({why})"


# ── 6. require_permission_or_internal's manual call really reaches require_user ──

def test_require_permission_or_internal_reaches_require_user_when_not_internal():
    """The static walk above trusts `require_permission_or_internal`'s guard to
    reach `require_user` without seeing a `Depends(require_user)` node for it (see
    the comment beside `_REQUIRE_PERMISSION_OR_INTERNAL_GUARD_PREFIX`). This is
    the dynamic half of that proof: for a request that is not using the internal
    key, the guard must call the module's actual `require_user` — the same one
    tests 1-3 pin the recheck behaviour of — not a shortcut that reads a role off
    an unchecked claims dict.
    """
    calls = []

    async def _spy(request, credentials=None):
        calls.append((request, credentials))
        return {"id": VALID_UID, "role": "admin"}

    original = auth_module.require_user
    auth_module.require_user = _spy
    try:
        request = SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/api/ai/collections/x/ingest-source"),
            headers={},
            state=SimpleNamespace(),
        )
        guard = auth_module.require_permission_or_internal("knowledge:write")
        out = _run(guard(request, None))
    finally:
        auth_module.require_user = original

    assert calls, (
        "require_permission_or_internal did not call require_user for a "
        "non-internal request — the permission would be checked against a role "
        "that was never rechecked against the database."
    )
    assert out["role"] == "admin"


def test_require_permission_or_internal_skips_require_user_for_the_internal_principal(monkeypatch):
    """The other half: a genuine internal-automation request must NOT go through
    require_user at all — there is no user to recheck, and require_user would
    401 it (see the defect this whole guard exists to avoid, in its docstring)."""
    monkeypatch.setenv("INTERNAL_API_KEY", "scheduler-secret")
    calls = []

    async def _spy(request, credentials=None):
        calls.append((request, credentials))
        raise AssertionError("require_user must not be called for an internal request")

    original = auth_module.require_user
    auth_module.require_user = _spy
    try:
        request = SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/api/ai/collections/x/ingest-source"),
            headers={"X-Internal-Key": "scheduler-secret"},
            state=SimpleNamespace(),
        )
        guard = auth_module.require_permission_or_internal("knowledge:write")
        out = _run(guard(request, None))
    finally:
        auth_module.require_user = original

    assert not calls
    assert out == {"id": None, "username": "system", "role": "admin", "internal": True}
