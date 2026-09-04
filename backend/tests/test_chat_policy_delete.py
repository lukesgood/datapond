"""Deleting a policy, and saying what stops being protected.

"Are you sure?" is not a confirmation. The card has to say which table loses
filtering and who can see rows afterwards that they cannot see now.
"""
import asyncio

import pytest

from app.chat.actions import REGISTRY, ActionKind


def _run(c):
    return asyncio.run(c)


@pytest.mark.parametrize("action_id",
                         ["governance.delete_rls_policy", "governance.delete_masking_policy"])
def test_deleting_is_destructive_and_names_its_target_field(action_id):
    action = REGISTRY[action_id]
    assert action.kind is ActionKind.DESTRUCTIVE
    assert action.target_field == "policy_id"


def test_the_last_policy_on_a_table_reports_that_the_table_becomes_unfiltered(monkeypatch):
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_policies_for_table",
                        lambda table: [{"id": "rls-7", "roles": ["analyst"]}])
    monkeypatch.setattr(mod, "_policy_by_id",
                        lambda pid: {"id": "rls-7", "table": "crm.customers",
                                     "roles": ["analyst"]})
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "crm.customers" in repr(out)
    assert "no row filtering" in effects or "unfiltered" in effects


def test_another_policy_still_covering_the_table_is_said_so(monkeypatch):
    """Deleting one of two is a different decision from deleting the only one."""
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_policies_for_table",
                        lambda table: [{"id": "rls-7", "roles": ["analyst"]},
                                       {"id": "rls-8", "roles": ["viewer"]}])
    monkeypatch.setattr(mod, "_policy_by_id",
                        lambda pid: {"id": "rls-7", "table": "crm.customers",
                                     "roles": ["analyst"]})
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    assert "rls-8" in repr(out)


def test_a_policy_store_that_cannot_be_read_is_not_checked_not_empty(monkeypatch):
    """An empty items list reads as 'nothing depends on this'."""
    from app.chat.analysis import governance as mod

    def _boom(_):
        raise RuntimeError("policy store unavailable")

    monkeypatch.setattr(mod, "_policy_by_id", _boom)
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    assert out["items"] == []
    assert out["not_checked"], "an uncomputed blast radius must say so"


def test_masking_delete_names_the_columns_that_stop_being_masked(monkeypatch):
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-1", "table": "crm.customers",
                                     "column": "email", "rule": "partial"})
    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-1"}, {"id": "u1"}))
    assert "email" in repr(out)
