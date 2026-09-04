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
    """Only mask on the column — patching `_mask_policy_by_id` alone left
    `_masks_for_column` hitting the real loader, which threw and landed in the
    except branch; the assertion passed for the wrong reason (the failure path's
    identity item, not the normal "stops being masked" path). Patching both here
    exercises the path this test is named for."""
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-1", "table": "crm.customers",
                                     "table_key": "crm.customers",
                                     "schema_table": "crm.customers",
                                     "column": "email", "rule": "partial",
                                     "roles": ["analyst"]})
    monkeypatch.setattr(mod, "_masks_for_column", lambda table_key, column: [])
    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-1"}, {"id": "u1"}))
    assert "email" in repr(out)
    effects = " ".join(i["effect"] for i in out["items"])
    assert "stops being masked" in effects


# ── fix round 1 — findings 1, 2, 3, 4 ───────────────────────────────────────────

def test_a_same_named_table_in_another_catalog_is_not_counted_as_coverage(monkeypatch):
    """crm.customers can exist in two catalogs. A policy protecting the other one
    must not be reported as still covering the one actually being deleted from."""
    from app.chat.analysis import governance as mod
    from app.rls.engine import RlsPolicy
    import app.rls.loader as rls_loader_mod

    aws = RlsPolicy(id="rls-aws", catalog="aws", schema="crm", table="customers",
                    filter_expression="region = 'x'", role_map={"analyst": False})
    gcp = RlsPolicy(id="rls-gcp", catalog="gcp", schema="crm", table="customers",
                    filter_expression="region = 'y'", role_map={"viewer": False})

    async def _fake_load_policies():
        return [aws, gcp]

    async def _fake_load_policy_by_id(policy_id):
        return {"rls-aws": aws, "rls-gcp": gcp}.get(policy_id)

    monkeypatch.setattr(rls_loader_mod, "load_policies", _fake_load_policies)
    monkeypatch.setattr(rls_loader_mod, "load_policy_by_id", _fake_load_policy_by_id)
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-aws"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "rls-gcp" not in effects, "a different catalog's policy is not coverage"
    assert "unfiltered" in effects or "no row filtering" in effects


def test_a_policy_differing_only_in_case_is_still_treated_as_coverage(monkeypatch):
    """The engine lower-cases identifiers before matching a policy (app/rls/engine.py
    _qualify/_policy_key) — a stored Crm.Customers must still count as covering
    crm.customers, or deleting one of them would be reported as leaving the table
    completely unfiltered when the engine still filters it."""
    from app.chat.analysis import governance as mod
    from app.rls.engine import RlsPolicy
    import app.rls.loader as rls_loader_mod

    p1 = RlsPolicy(id="rls-1", catalog="iceberg", schema="Crm", table="Customers",
                   filter_expression="region = 'x'", role_map={"analyst": False})
    p2 = RlsPolicy(id="rls-2", catalog="ICEBERG", schema="crm", table="customers",
                   filter_expression="region = 'y'", role_map={"viewer": False})

    async def _fake_load_policies():
        return [p1, p2]

    async def _fake_load_policy_by_id(policy_id):
        return {"rls-1": p1, "rls-2": p2}.get(policy_id)

    monkeypatch.setattr(rls_loader_mod, "load_policies", _fake_load_policies)
    monkeypatch.setattr(rls_loader_mod, "load_policy_by_id", _fake_load_policy_by_id)
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-1"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "rls-2" in effects, "a case-only difference is the same table"
    assert "unfiltered" not in effects


def test_a_table_absent_from_the_pii_scan_is_not_reported_as_clean(monkeypatch):
    """`_scan_pii_tables` only appends a table when it has at least one PII hit — a
    clean table and a table that was never looked at (truncated, or unreadable) are
    both simply absent from the result. Absent must not become "no PII found"."""
    from app.chat.analysis import governance as mod
    import app.api.governance as governance_api

    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-1", "table": "iceberg.crm.customers",
                                     "table_key": "iceberg.crm.customers",
                                     "schema_table": "crm.customers",
                                     "column": "email", "rule": "full",
                                     "roles": ["analyst"]})
    monkeypatch.setattr(mod, "_masks_for_column", lambda table_key, column: [])

    class _Entry:
        table = "crm.some_other_table"
        pii_columns = []

    monkeypatch.setattr(governance_api, "_scan_pii_tables", lambda: [_Entry()])

    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-1"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "no PII was found" not in effects
    assert "found no PII in this column" not in effects
    assert out["not_checked"], "an unscanned table must say so, not read as clean"


def test_a_second_mask_still_covering_the_column_is_said_so(monkeypatch):
    """Deleting one of two masks on the same column is not the same decision as
    deleting the only one — the RLS twin of test_another_policy_still_covering."""
    from app.chat.analysis import governance as mod

    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-1", "table": "iceberg.crm.customers",
                                     "table_key": "iceberg.crm.customers",
                                     "schema_table": "crm.customers",
                                     "column": "email", "rule": "full",
                                     "roles": ["analyst"]})
    monkeypatch.setattr(
        mod, "_masks_for_column",
        lambda table_key, column: [{"id": "m-1", "roles": ["analyst"]},
                                   {"id": "m-2", "roles": ["viewer"]}])

    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-1"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "m-2" in effects
    assert "stops being masked" not in effects, \
        "another policy still covers this column — it does not stop being masked"


def test_a_failing_rls_coverage_check_still_shows_the_first_reads_facts(monkeypatch):
    """The policy identity (table, roles) was read successfully before the coverage
    check ran — a failure in the second read must not discard it."""
    from app.chat.analysis import governance as mod

    monkeypatch.setattr(mod, "_policy_by_id",
                        lambda pid: {"id": "rls-7", "table": "iceberg.crm.customers",
                                     "table_key": "iceberg.crm.customers",
                                     "roles": ["analyst"]})

    def _boom(table_key):
        raise RuntimeError("coverage check unavailable")

    monkeypatch.setattr(mod, "_policies_for_table", _boom)
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-7"}, {"id": "u1"}))
    assert out["items"], "the successful first read must still be shown"
    assert "crm.customers" in repr(out) and "analyst" in repr(out)
    assert out["not_checked"], "the coverage check that failed must still be flagged"


def test_a_failing_mask_coverage_check_still_shows_the_first_reads_facts(monkeypatch):
    from app.chat.analysis import governance as mod

    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-1", "table": "iceberg.crm.customers",
                                     "table_key": "iceberg.crm.customers",
                                     "schema_table": "crm.customers",
                                     "column": "email", "rule": "full",
                                     "roles": ["analyst"]})

    def _boom(table_key, column):
        raise RuntimeError("mask store unavailable")

    monkeypatch.setattr(mod, "_masks_for_column", _boom)
    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-1"}, {"id": "u1"}))
    assert out["items"], "the successful first read must still be shown"
    assert "email" in repr(out) and "analyst" in repr(out)
    assert out["not_checked"], "the coverage check that failed must still be flagged"


# ── Critical 4 — a disabled policy must still be found, not read as absent ──────

def test_policy_lookup_uses_the_by_id_loader_not_the_enabled_only_one(monkeypatch):
    """`load_policies()` filters to `enabled = true` (its own docstring). The delete
    route (`DELETE /governance/rls/policies/{id}`) has no such filter — it deletes a
    disabled policy exactly as readily as an enabled one. `_policy_by_id` must read
    through `load_policy_by_id`, the loader that has no enabled condition either, or
    a disabled policy about to be destroyed is misreported as not existing."""
    from app.chat.analysis import governance as mod
    from app.rls.engine import RlsPolicy
    import app.rls.loader as rls_loader_mod

    disabled = RlsPolicy(id="rls-9", catalog="iceberg", schema="crm", table="customers",
                         filter_expression="region = 'x'", enabled=False,
                         role_map={"analyst": False})

    async def _load_policies_enabled_only():
        return []  # what the real loader would return: disabled rows excluded

    async def _load_policy_by_id(policy_id):
        return disabled if policy_id == "rls-9" else None

    monkeypatch.setattr(rls_loader_mod, "load_policies", _load_policies_enabled_only)
    monkeypatch.setattr(rls_loader_mod, "load_policy_by_id", _load_policy_by_id)

    policy = _run(mod._policy_by_id("rls-9"))
    assert policy is not None, (
        "a disabled policy must still be found — the loader that only returns "
        "enabled rows must not be the one this lookup goes through")
    assert policy["enabled"] is False

    preview = _run(mod.preview_delete_rls_policy({"policy_id": "rls-9"}, {"id": "u1"}))
    assert "no such policy" not in preview["summary"]
    assert "disabled" in preview["summary"]

    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-9"}, {"id": "u1"}))
    assert out["items"], "a disabled policy is still a real dependents computation"
    assert not any("no such" in (nc or "").lower() for nc in out["not_checked"])


def test_mask_lookup_uses_the_by_id_loader_not_the_enabled_only_one(monkeypatch):
    """The masking twin of the RLS test above."""
    from app.chat.analysis import governance as mod
    from app.rls.engine import MaskPolicy
    import app.rls.loader as rls_loader_mod

    disabled = MaskPolicy(id="m-9", catalog="iceberg", schema="crm", table="customers",
                          column="email", masking_type="full", enabled=False,
                          role_map={"analyst": False})

    async def _load_masks_enabled_only():
        return []

    async def _load_mask_by_id(policy_id):
        return disabled if policy_id == "m-9" else None

    monkeypatch.setattr(rls_loader_mod, "load_masks", _load_masks_enabled_only)
    monkeypatch.setattr(rls_loader_mod, "load_mask_by_id", _load_mask_by_id)

    policy = _run(mod._mask_policy_by_id("m-9"))
    assert policy is not None
    assert policy["enabled"] is False

    preview = _run(mod.preview_delete_masking_policy({"policy_id": "m-9"}, {"id": "u1"}))
    assert "no such policy" not in preview["summary"]
    assert "disabled" in preview["summary"]


# ── Important — a disabled policy's card must not claim protection is lost ──────
# A disabled policy is not filtering (or masking) anything before the delete either
# — the table/column is already unprotected by it. These pin the sentence itself,
# not just that some branch ran, so the next wrong wording would fail them too.

def test_a_disabled_rls_policys_card_does_not_claim_protection_is_lost(monkeypatch):
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_policies_for_table", lambda table: [])
    monkeypatch.setattr(mod, "_policy_by_id",
                        lambda pid: {"id": "rls-9", "table": "crm.customers",
                                     "table_key": "iceberg.crm.customers",
                                     "roles": ["analyst"], "enabled": False})
    out = _run(mod.dependents_delete_rls_policy({"policy_id": "rls-9"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "already unfiltered" in effects
    assert "cannot be re-enabled or restored" in effects
    for forbidden in ("loses its only row filter", "will see every row",
                       "becomes unfiltered"):
        assert forbidden not in effects, f"a disabled policy's card must not say {forbidden!r}"


def test_a_disabled_masking_policys_card_does_not_claim_protection_is_lost(monkeypatch):
    from app.chat.analysis import governance as mod
    monkeypatch.setattr(mod, "_masks_for_column", lambda table_key, column: [])
    monkeypatch.setattr(mod, "_mask_policy_by_id",
                        lambda pid: {"id": "m-9", "table": "crm.customers",
                                     "table_key": "iceberg.crm.customers",
                                     "schema_table": "crm.customers", "column": "email",
                                     "rule": "full", "roles": ["analyst"],
                                     "enabled": False})
    out = _run(mod.dependents_delete_masking_policy({"policy_id": "m-9"}, {"id": "u1"}))
    effects = " ".join(i["effect"] for i in out["items"])
    assert "already unmasked" in effects
    assert "cannot be re-enabled or restored" in effects
    for forbidden in ("stops being masked", "will see the real values"):
        assert forbidden not in effects, f"a disabled policy's card must not say {forbidden!r}"


# ── Important 6 — a policy id has to be reachable from inside the panel ─────────

def test_explain_policy_includes_the_id_a_delete_would_target(monkeypatch):
    """`delete_rls_policy` / `delete_masking_policy` target_field="policy_id", a
    UUID — and before this fix no read action ever showed one, so `named_by_user`
    could never have evidence for a policy id: the person would have had to leave
    the panel (the Governance page's own UI) to find it first. Once
    `explain_policy` includes `id`, reading a policy and then asking to delete it by
    that id works without leaving the conversation."""
    from app.chat.analysis import governance as mod
    from app.rls.engine import RlsPolicy, MaskPolicy
    import app.rls.loader as rls_loader_mod

    async def _fake_load_policies():
        return [RlsPolicy(id="rls-42", catalog="iceberg", schema="crm", table="customers",
                          filter_expression="region = 'EU'", role_map={"analyst": False})]

    async def _fake_load_masks():
        return [MaskPolicy(id="m-42", catalog="iceberg", schema="crm", table="customers",
                           column="email", masking_type="full", role_map={"analyst": False})]

    monkeypatch.setattr(rls_loader_mod, "load_policies", _fake_load_policies)
    monkeypatch.setattr(rls_loader_mod, "load_masks", _fake_load_masks)

    out = _run(mod.explain_policy({"table": None}, {"id": "u1"}))
    assert out["row_filters"][0]["id"] == "rls-42"
    assert out["column_masks"][0]["id"] == "m-42"
