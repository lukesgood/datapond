"""API keys for non-human callers.

An AI app or agent had no identity of its own: it had to carry a person's JWT, which
expires in a day, cannot be revoked without disabling that person, grants everything
they can do, and points spend attribution and the audit log at the wrong actor — in a
product whose differentiator is per-user spend attribution.

A service account is a `users` row, so roles, RLS context, audit, collection
ownership, and spend attribution all keep working unchanged. This module is only the
credential.
"""
import pytest

from app.service_accounts import (
    KEY_PREFIX,
    effective_permissions,
    generate_key,
    hash_key,
    looks_like_api_key,
)


# ── credential generation ─────────────────────────────────────────────────────

def test_a_generated_key_is_prefixed_so_a_client_can_route_it():
    key, _prefix, _hash = generate_key()
    assert key.startswith(KEY_PREFIX)
    assert looks_like_api_key(key)


def test_a_jwt_is_not_mistaken_for_an_api_key():
    assert not looks_like_api_key("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def")
    assert not looks_like_api_key("")
    assert not looks_like_api_key(None)


def test_keys_are_unique_and_high_entropy():
    keys = {generate_key()[0] for _ in range(200)}
    assert len(keys) == 200
    assert len(generate_key()[0]) >= len(KEY_PREFIX) + 40


def test_the_stored_prefix_identifies_a_key_without_revealing_it():
    key, prefix, _ = generate_key()
    assert key.startswith(prefix)
    assert len(prefix) <= 16, "column is VARCHAR(16)"
    assert len(prefix) < len(key), "a prefix that is the whole key is not a prefix"


def test_the_stored_hash_is_sha256_and_fits_the_column():
    key, _prefix, digest = generate_key()
    assert digest == hash_key(key)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert digest != key


def test_hashing_is_stable_and_distinguishes_keys():
    a, b = generate_key()[0], generate_key()[0]
    assert hash_key(a) == hash_key(a)
    assert hash_key(a) != hash_key(b)


# ── what a key may do ─────────────────────────────────────────────────────────

def test_a_key_with_no_scopes_inherits_the_accounts_role():
    from app.permissions import permissions_for
    assert effective_permissions("ai_engineer", []) == permissions_for("ai_engineer")


def test_scopes_narrow_a_key_but_never_widen_it():
    """A key must not be able to do more than the account it belongs to."""
    granted = effective_permissions("viewer", ["settings:write", "user:manage", "catalog:read"])
    assert granted == {"catalog:read"}


def test_scopes_are_intersected_not_trusted():
    granted = effective_permissions("ai_engineer", ["knowledge:write"])
    assert granted == {"knowledge:write"}
    assert "ai:generate" not in granted, "the key was scoped narrower than its role"


def test_an_unknown_scope_is_ignored_rather_than_granted():
    assert effective_permissions("admin", ["not:a:permission"]) == set()


def test_a_service_account_can_never_hold_administrative_permissions():
    """Even an admin-role service account: a credential in a config file must not be
    able to add users or change model providers."""
    granted = effective_permissions("admin", [])
    for forbidden in ("user:manage", "settings:write"):
        assert forbidden not in granted, forbidden


# ── resolving a key into an identity ──────────────────────────────────────────

def test_require_permission_uses_the_keys_scopes_not_just_the_role():
    """A scoped key must be refused a permission its role would otherwise allow."""
    import asyncio
    import pytest as _pytest
    from fastapi import HTTPException
    from app.api.auth import require_permission

    scoped = {"id": "svc1", "role": "ai_engineer", "permissions": ["knowledge:write"]}

    assert asyncio.run(require_permission("knowledge:write")(user=scoped))["id"] == "svc1"
    with _pytest.raises(HTTPException) as ei:
        asyncio.run(require_permission("ai:generate")(user=scoped))
    assert ei.value.status_code == 403


def test_a_human_identity_is_still_judged_by_role_alone():
    """People carry no `permissions` key; nothing about them changes."""
    import asyncio
    from app.api.auth import require_permission
    assert asyncio.run(require_permission("ai:generate")(
        user={"id": "u1", "role": "ai_engineer"}))["id"] == "u1"


def test_an_empty_permission_list_grants_nothing():
    """A revoked-down-to-nothing key must not fall back to its role."""
    import asyncio
    import pytest as _pytest
    from fastapi import HTTPException
    from app.api.auth import require_permission
    with _pytest.raises(HTTPException):
        asyncio.run(require_permission("catalog:read")(
            user={"id": "svc1", "role": "admin", "permissions": []}))


def test_resolving_an_unknown_key_returns_none_instead_of_raising():
    """The middleware turns any exception here into a bare 401, so a bug in the
    resolver is indistinguishable from a wrong credential. It cost a live debugging
    round: a missing `import time` made every key 401 with nothing in the logs.

    The lookup has to succeed and find nothing, so the path reaches the cache write
    at the end — an early return on a database error skips it.
    """
    import asyncio
    from app.api import auth

    class _Conn:
        async def fetchrow(self, *a, **k):
            return None
        async def execute(self, *a, **k):
            return "UPDATE 0"

    class _Acquire:
        async def __aenter__(self):
            return _Conn()
        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Acquire()

    async def _pool():
        return _Pool()

    original = auth._get_pool
    auth._get_pool = _pool
    auth._KEY_CACHE.clear()
    try:
        assert asyncio.run(auth._resolve_api_key("dp_sk_definitely-not-a-key")) is None
    finally:
        auth._get_pool = original
        auth._KEY_CACHE.clear()
