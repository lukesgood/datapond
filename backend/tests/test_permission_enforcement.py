"""Hiding a menu is not access control. The API is where a role has to hold.

Before this, every authenticated user could create and delete connectors and
knowledge collections regardless of role — the only check in the product was
admin/not-admin.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api.auth import require_permission


def _check(perm, role):
    return asyncio.run(require_permission(perm)(user={"id": "u1", "role": role}))


def test_a_role_holding_the_permission_passes_through():
    user = _check("connector:write", "data_engineer")
    assert user["role"] == "data_engineer"


def test_a_role_without_the_permission_is_refused():
    with pytest.raises(HTTPException) as ei:
        _check("connector:write", "viewer")
    assert ei.value.status_code == 403


def test_the_refusal_names_the_permission_so_the_user_can_ask_for_it():
    with pytest.raises(HTTPException) as ei:
        _check("connector:write", "viewer")
    assert "connector:write" in ei.value.detail


def test_admin_passes_every_permission():
    for perm in ("connector:write", "settings:write", "governance:write", "ai:generate"):
        assert _check(perm, "admin")["role"] == "admin"


def test_model_spend_is_refused_to_a_viewer():
    """The whole point of splitting ai:generate out."""
    with pytest.raises(HTTPException) as ei:
        _check("ai:generate", "viewer")
    assert ei.value.status_code == 403


def test_a_viewer_can_still_run_queries():
    """Regression guard: the upgrade must not take away what people do all day."""
    assert _check("query:run", "viewer")["role"] == "viewer"


def test_an_auditor_reads_governance_but_cannot_change_it():
    assert _check("governance:read", "auditor")["role"] == "auditor"
    with pytest.raises(HTTPException):
        _check("governance:write", "auditor")


def test_a_missing_role_claim_is_treated_as_viewer():
    assert asyncio.run(require_permission("query:run")(user={"id": "u1"}))["id"] == "u1"
    with pytest.raises(HTTPException):
        asyncio.run(require_permission("connector:write")(user={"id": "u1"}))


# ── The two guards must decide identically ───────────────────────────────────────
#
# `require_permission_or_internal` was a verbatim fork of `require_permission`:
# not just the internal-principal branch that justifies its existence, but the
# granted/allowed resolution, the route/method/address extraction, the
# security_audit denial record, the 403 wording and the privileged-allow record —
# all duplicated. A change to the audit contract or the refusal sentence could be
# made in one and missed in the other, and nothing would have caught it. These
# tests pin the equivalence so the shared body can be extracted and can stay
# extracted.

class _Req:
    def __init__(self, method="POST", path="/api/x"):
        self.method = method
        self.url = type("U", (), {"path": path})()
        self.headers = {}
        self.client = type("C", (), {"host": "10.0.0.9"})()
        self.state = type("S", (), {})()


def _both_guards(permission):
    from app.api import auth
    return auth.require_permission(permission), auth.require_permission_or_internal(permission)


def _run_or_internal(guard, request, user, monkeypatch):
    """`require_permission_or_internal` calls `require_user` as a plain function
    (it cannot use Depends — see its docstring), so the caller is installed by
    patching the module attribute."""
    from app.api import auth

    async def _fake_require_user(req, credentials=None):
        return user
    monkeypatch.setattr(auth, "require_user", _fake_require_user)
    return asyncio.run(guard(request, None))


def test_both_guards_refuse_with_the_same_sentence(monkeypatch):
    plain, or_internal = _both_guards("connector:write")
    viewer = {"id": "u1", "username": "v", "role": "viewer"}

    with pytest.raises(HTTPException) as plain_err:
        asyncio.run(plain(request=_Req(), user=viewer))
    with pytest.raises(HTTPException) as internal_err:
        _run_or_internal(or_internal, _Req(), viewer, monkeypatch)

    assert plain_err.value.status_code == internal_err.value.status_code == 403
    assert plain_err.value.detail == internal_err.value.detail


def test_both_guards_write_the_same_audit_record(monkeypatch):
    """The denial record is the auditor's only view of a refusal the caller cannot
    see. Its fields must not depend on which of the two guards happened to be on
    the route."""
    import app.security_audit as security_audit

    records = []

    async def _capture(**kwargs):
        records.append(kwargs)
    monkeypatch.setattr(security_audit, "record", _capture)

    plain, or_internal = _both_guards("connector:write")
    viewer = {"id": "u1", "username": "v", "role": "viewer"}
    request = _Req(method="DELETE", path="/api/connectors/7")

    with pytest.raises(HTTPException):
        asyncio.run(plain(request=request, user=viewer))
    with pytest.raises(HTTPException):
        _run_or_internal(or_internal, request, viewer, monkeypatch)

    assert len(records) == 2
    assert records[0] == records[1]
    assert records[0]["outcome"] == "denied"
    assert records[0]["route"] == "/api/connectors/7"
    assert records[0]["method"] == "DELETE"


def test_both_guards_record_a_privileged_allow_identically(monkeypatch):
    import app.security_audit as security_audit

    records = []

    async def _capture(**kwargs):
        records.append(kwargs)
    monkeypatch.setattr(security_audit, "record", _capture)

    permission = next(p for p in ("user:manage", "settings:write", "connector:write")
                      if security_audit.is_privileged(p))
    plain, or_internal = _both_guards(permission)
    admin = {"id": "u2", "username": "a", "role": "admin"}
    request = _Req()

    asyncio.run(plain(request=request, user=admin))
    _run_or_internal(or_internal, request, admin, monkeypatch)

    assert len(records) == 2
    assert records[0] == records[1]
    assert records[0]["outcome"] == "allowed"


def test_both_guards_treat_a_scoped_key_permission_set_as_authoritative(monkeypatch):
    """An empty or narrowed `permissions` set wins over the role in both guards —
    the property that makes a service-account key's scopes mean anything."""
    plain, or_internal = _both_guards("connector:write")
    scoped_admin = {"id": "u3", "username": "k", "role": "admin",
                    "permissions": frozenset()}

    with pytest.raises(HTTPException):
        asyncio.run(plain(request=_Req(), user=scoped_admin))
    with pytest.raises(HTTPException):
        _run_or_internal(or_internal, _Req(), scoped_admin, monkeypatch)
