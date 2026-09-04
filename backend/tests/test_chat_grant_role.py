"""Granting a role, with the three things that must never be possible.

Permission changes are the one category where a mistake grants the mistake-maker
more room to make mistakes. The constraints live at execution because that is
where a forged proposal arrives.

The identifier is `username`, not `email`: see the module docstring in
`app/chat/analysis/users.py` for why — login, the default-admin seed, and the LDAP
directory upsert all resolve a person by `username`, and `knowledge.py`'s collection
membership actions already made the same choice for the same reason.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind
from app.chat.analysis import users as mod


def _run(c):
    return asyncio.run(c)


from app.permissions import ALL_PERMISSIONS

ADMIN = {"id": "u-admin", "username": "admin",
         "permissions": sorted(ALL_PERMISSIONS)}
LIMITED = {"id": "u-eng", "username": "eng",
           "permissions": ["user:manage", "catalog:read", "knowledge:read"]}


def test_it_is_destructive_and_targets_the_person():
    action = REGISTRY["users.grant_role"]
    assert action.kind is ActionKind.DESTRUCTIVE
    assert action.target_field == "username"
    assert action.permission == "user:manage"


def test_a_grant_within_the_callers_own_permissions_is_allowed(monkeypatch):
    seen = {}

    async def _fake(user_id, body, admin=None):
        seen.update(user_id=user_id, body=body)
        return {"ok": True}

    monkeypatch.setattr("app.api.auth.update_user", _fake)
    monkeypatch.setattr(mod, "_user_by_username",
                        lambda u: _coro({"id": "u-2", "username": u, "role": "viewer"}))
    _run(mod.grant_role({"username": "someone", "role": "business_analyst"},
                        ADMIN))
    assert seen["body"]["role"] == "business_analyst"


async def _coro(v):
    return v


def test_a_grant_beyond_the_callers_own_permissions_is_refused(monkeypatch):
    """You cannot hand out what you do not hold — the rule that stops the assistant
    becoming a way around the permission matrix."""
    monkeypatch.setattr(mod, "_user_by_username",
                        lambda u: _coro({"id": "u-2", "username": u, "role": "viewer"}))
    called = []
    monkeypatch.setattr("app.api.auth.update_user",
                        lambda *a, **k: called.append(a))
    with pytest.raises(PermissionError):
        _run(mod.grant_role({"username": "someone", "role": "admin"}, LIMITED))
    assert called == []


def test_user_manage_is_never_grantable(monkeypatch):
    """An assistant that can make administrators is a different product."""
    monkeypatch.setattr(mod, "_user_by_username",
                        lambda u: _coro({"id": "u-2", "username": u, "role": "viewer"}))
    called = []
    monkeypatch.setattr("app.api.auth.update_user", lambda *a, **k: called.append(a))
    with pytest.raises(PermissionError):
        _run(mod.grant_role({"username": "someone", "role": "admin"}, ADMIN))
    assert called == []


def test_nobody_may_change_their_own_role(monkeypatch):
    """Costs an admin nothing — the UI still does it — and closes the path injected
    content aims at first."""
    monkeypatch.setattr(mod, "_user_by_username",
                        lambda u: _coro({"id": ADMIN["id"], "username": u, "role": "viewer"}))
    called = []
    monkeypatch.setattr("app.api.auth.update_user", lambda *a, **k: called.append(a))
    with pytest.raises(PermissionError):
        _run(mod.grant_role({"username": ADMIN["username"], "role": "data_engineer"}, ADMIN))
    assert called == []


def test_the_dependents_name_the_permissions_gained_not_the_role(monkeypatch):
    """"admin" tells the approver nothing they can weigh. The list of things this
    person will be able to do that they cannot do today does."""
    monkeypatch.setattr(mod, "_user_by_username",
                        lambda u: _coro({"id": "u-2", "username": u, "role": "viewer"}))
    out = _run(mod.dependents_grant_role(
        {"username": "someone", "role": "data_engineer"}, ADMIN))
    rendered = repr(out)
    assert "connector:write" in rendered
    assert "viewer" in rendered or "data_engineer" in rendered


def test_an_unknown_person_is_refused_rather_than_created(monkeypatch):
    monkeypatch.setattr(mod, "_user_by_username", lambda u: _coro(None))
    with pytest.raises(ValueError):
        _run(mod.grant_role({"username": "nobody", "role": "viewer"}, ADMIN))


def test_a_user_that_cannot_be_looked_up_is_not_checked(monkeypatch):
    async def _boom(_):
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "_user_by_username", _boom)
    out = _run(mod.dependents_grant_role(
        {"username": "someone", "role": "viewer"}, ADMIN))
    assert out["items"] == [] and out["not_checked"]
