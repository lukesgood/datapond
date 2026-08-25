"""Role → permission mapping.

Roles existed as five seeded rows that nothing outside the RLS engine ever read,
while the application layer enforced a single admin/not-admin split. This module is
the missing half: what each role may actually do.

Two rules shape the matrix. Money-spending actions are their own permission, because
per-user model spend is a governance claim this product makes and an unbounded
`ai:generate` for everyone contradicts it. And writing is what gets withheld —
reading stays broad, so the change removes privileges that were granted by accident
rather than fencing off the product.
"""
import pytest

from app.permissions import (
    ALL_PERMISSIONS,
    KNOWN_ROLES,
    has_permission,
    permissions_for,
)


def test_admin_holds_every_permission():
    assert permissions_for("admin") == ALL_PERMISSIONS


def test_every_role_maps_to_known_permissions_only():
    for role in KNOWN_ROLES:
        assert permissions_for(role) <= ALL_PERMISSIONS, role


def test_no_two_roles_are_identical():
    """A role indistinguishable from another is a modelling failure, not a role."""
    seen = {}
    for role in KNOWN_ROLES:
        key = frozenset(permissions_for(role))
        assert key not in seen, f"{role} is identical to {seen[key]}"
        seen[key] = role


# ── the two roles this product was missing ────────────────────────────────────

def test_ai_engineer_can_build_knowledge_and_spend_on_models():
    """The product's stated target user — AI application teams — had no role."""
    assert has_permission("ai_engineer", "knowledge:write")
    assert has_permission("ai_engineer", "ai:generate")
    assert has_permission("ai_engineer", "query:run")


def test_ai_engineer_cannot_administer_the_platform():
    for perm in ("settings:write", "user:manage", "service:manage", "governance:write"):
        assert not has_permission("ai_engineer", perm), perm


def test_auditor_can_see_governance_audit_and_spend():
    for perm in ("governance:read", "audit:read", "spend:read"):
        assert has_permission("auditor", perm), perm


def test_auditor_can_run_queries_to_verify_enforcement():
    """Checking that a masking policy actually masks means running a query."""
    assert has_permission("auditor", "query:run")


def test_auditor_writes_nothing():
    writes = {p for p in ALL_PERMISSIONS if p.endswith(":write") or p in
              ("user:manage", "service:manage", "ai:generate")}
    assert not (permissions_for("auditor") & writes)


# ── the split that makes spend governable ─────────────────────────────────────

def test_viewer_may_read_and_query_but_not_spend_on_models():
    assert has_permission("viewer", "catalog:read")
    assert has_permission("viewer", "query:run")
    assert not has_permission("viewer", "ai:generate")


def test_viewer_cannot_write_anything():
    assert not has_permission("viewer", "knowledge:write")
    assert not has_permission("viewer", "connector:write")
    assert not has_permission("viewer", "dashboard:write")


def test_business_analyst_is_distinguished_by_dashboards():
    assert has_permission("business_analyst", "dashboard:write")
    assert not has_permission("business_analyst", "connector:write")


def test_data_engineer_owns_ingestion_but_not_model_spend():
    assert has_permission("data_engineer", "connector:write")
    assert has_permission("data_engineer", "pipeline:write")
    assert not has_permission("data_engineer", "ai:generate")


# ── unknown roles ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["", None, "wizard", "root", "  "])
def test_unknown_roles_fall_back_to_viewer(role):
    """Fail closed on writes without locking anyone out: a deployment carrying a
    custom string in users.role must not lose access entirely. auth.py already
    defaults a missing claim to 'viewer'."""
    assert permissions_for(role) == permissions_for("viewer")


def test_role_matching_is_case_and_space_insensitive():
    assert permissions_for("  Admin ") == permissions_for("admin")
