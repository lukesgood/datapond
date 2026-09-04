"""Creating a row filter or a column mask, behind the ordinary approval card.

A policy that is too tight is an inconvenience someone reports. A policy that is
too loose is a leak nobody reports, so the preview has to say who it will apply to
before anyone approves it.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind


def _run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("action_id",
                         ["governance.create_rls_policy", "governance.create_masking_policy"])
def test_creating_is_a_mutate(action_id):
    action = REGISTRY[action_id]
    assert action.kind is ActionKind.MUTATE
    assert action.permission == "governance:write"
    assert action.target_field is None


def test_the_preview_says_which_table_and_which_roles(monkeypatch):
    from app.chat.analysis import governance as mod
    card = _run(mod.preview_create_rls_policy(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"},
        {"id": "u1"}))
    rendered = repr(card)
    assert "crm.customers" in rendered and "analyst" in rendered


def test_the_masking_preview_says_which_table_column_and_rule():
    from app.chat.analysis import governance as mod
    card = _run(mod.preview_create_masking_policy(
        {"table": "crm.customers", "column": "email", "masking_type": "partial_email",
         "roles": ["analyst"]},
        {"id": "u1"}))
    rendered = repr(card)
    assert "crm.customers" in rendered and "email" in rendered
    assert "analyst" in rendered and "partial_email" in rendered


def test_an_empty_roles_list_previews_as_matching_nobody():
    """`applicable_policies` (app/rls/engine.py) only applies a policy to roles
    present in its role_map — an empty roles list is stored but matches nobody, the
    opposite of "applies to everyone". The preview must say so plainly."""
    from app.chat.analysis import governance as mod
    card = _run(mod.preview_create_rls_policy(
        {"table": "crm.customers", "roles": [], "expression": "region = 'EU'"},
        {"id": "u1"}))
    assert "not apply to anyone" in card["summary"]


def test_the_executor_passes_the_caller(monkeypatch):
    from app.chat.analysis import governance as mod
    seen = {}

    async def _fake(body, user=None):
        seen["user"] = user
        return {"id": "rls-1"}

    monkeypatch.setattr("app.api.governance.create_rls_policy", _fake)
    user = {"id": "u1"}
    _run(mod.create_rls_policy_action(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"},
        user))
    assert seen["user"] is user


def test_the_masking_executor_passes_the_caller_and_builds_the_real_model(monkeypatch):
    from app.api.governance import MaskPolicyIn
    from app.chat.analysis import governance as mod
    seen = {}

    async def _fake(body, user=None):
        seen["user"] = user
        seen["body"] = body
        return {"id": "mask-1"}

    monkeypatch.setattr("app.api.governance.create_mask_policy", _fake)
    user = {"id": "u1"}
    _run(mod.create_masking_policy_action(
        {"table": "crm.customers", "column": "email", "masking_type": "partial_email",
         "roles": ["analyst"]},
        user))
    assert seen["user"] is user
    assert isinstance(seen["body"], MaskPolicyIn)
    assert seen["body"].column_name == "email"
    assert seen["body"].masking_type == "partial_email"
    assert seen["body"].schema_name == "crm" and seen["body"].table_name == "customers"


def test_build_rls_policy_in_splits_schema_and_table():
    from app.api.governance import RlsPolicyIn
    from app.chat.analysis.governance import build_rls_policy_in
    body = build_rls_policy_in(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"})
    assert isinstance(body, RlsPolicyIn)
    assert body.catalog_name == "iceberg"
    assert body.schema_name == "crm" and body.table_name == "customers"
    assert body.role_names == ["analyst"]
    assert body.filter_expression == "region = 'EU'"


def test_two_part_table_resolves_the_deployment_catalog_not_a_hardcoded_default(monkeypatch):
    """On the AWS Single-Node Reference, Helm sets RLS_DEFAULT_CATALOG=AwsDataCatalog
    (helm/datapond/templates/backend-deployment.yaml). `app.rls.engine._default_catalog()`
    is what the RLS engine itself resolves a policy's catalog against — if a chat-created
    policy for a two-part table name were stored under a hardcoded "iceberg" instead, the
    engine's own lookup for AwsDataCatalog would never find it: a policy that looks right
    on the approval card and protects nothing at runtime."""
    monkeypatch.setenv("RLS_DEFAULT_CATALOG", "AwsDataCatalog")
    from app.api.governance import MaskPolicyIn, RlsPolicyIn
    from app.chat.analysis.governance import (build_mask_policy_in,
                                               build_rls_policy_in,
                                               preview_create_masking_policy,
                                               preview_create_rls_policy)

    rls_body = build_rls_policy_in(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"})
    assert isinstance(rls_body, RlsPolicyIn)
    assert rls_body.catalog_name == "AwsDataCatalog"

    mask_body = build_mask_policy_in(
        {"table": "crm.customers", "column": "email", "roles": ["analyst"]})
    assert isinstance(mask_body, MaskPolicyIn)
    assert mask_body.catalog_name == "AwsDataCatalog"

    # The approval card has to show the catalog the policy is actually stored
    # against, not the placeholder — otherwise the person approving cannot tell a
    # working policy from a silently-inert one.
    rls_card = _run(preview_create_rls_policy(
        {"table": "crm.customers", "roles": ["analyst"], "expression": "region = 'EU'"},
        {"id": "u1"}))
    assert rls_card["catalog_name"] == "AwsDataCatalog"

    mask_card = _run(preview_create_masking_policy(
        {"table": "crm.customers", "column": "email", "roles": ["analyst"]}, {"id": "u1"}))
    assert mask_card["catalog_name"] == "AwsDataCatalog"


def test_three_part_table_is_still_taken_as_given(monkeypatch):
    """The explicit-catalog case the review already approved must not regress."""
    monkeypatch.setenv("RLS_DEFAULT_CATALOG", "AwsDataCatalog")
    from app.chat.analysis.governance import _split_table
    assert _split_table("otherlog.crm.customers") == ("otherlog", "crm", "customers")


def test_one_or_four_parts_still_raise():
    from app.chat.analysis.governance import _split_table
    with pytest.raises(ValueError):
        _split_table("customers")
    with pytest.raises(ValueError):
        _split_table("a.b.c.d")
