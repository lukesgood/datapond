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
