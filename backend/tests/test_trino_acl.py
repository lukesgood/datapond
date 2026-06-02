"""
Unit tests for the Trino file-based access control generator (RLS Layer 2).
No cluster needed — asserts on the generated rules.json dict. See docs/RLS_DESIGN.md.
"""
from app.rls.engine import UserContext, RlsPolicy, MaskPolicy
from app.rls.trino_acl import generate_rules, rules_summary


def _users():
    return [
        UserContext("u1", "alice", ["business_analyst"], {"region": "us-east"}),
        UserContext("u2", "bob", ["business_analyst"], {"region": "eu-west"}),
        UserContext("u3", "root", ["admin"], {}),
    ]


def _orders_policy():
    return RlsPolicy(
        id="p1", catalog="iceberg", schema="sales", table="orders",
        filter_expression="region = current_user_attribute('region')",
        role_map={"business_analyst": False},
    )


def test_per_user_filter_is_bound_to_literal():
    rules = generate_rules(_users(), [_orders_policy()])
    by_user = {r.get("user"): r for r in rules["tables"] if r.get("filter")}
    assert by_user["^alice$"]["filter"] == "(region = 'us-east')"
    assert by_user["^bob$"]["filter"] == "(region = 'eu-west')"


def test_admin_no_bypass_is_subject_to_targeting_policy():
    # a policy targeting admin too -> admin (no region attr) gets filter bound to NULL
    pol = RlsPolicy(id="pa", catalog="iceberg", schema="sales", table="orders",
                    filter_expression="region = current_user_attribute('region')",
                    role_map={"business_analyst": False, "admin": False})
    rules = generate_rules(_users(), [pol], admin_bypass=False)
    root_rules = [r for r in rules["tables"] if r.get("user") == "^root$"]
    assert root_rules                      # admin is subject to RLS (no blanket allow)
    assert "NULL" in root_rules[0].get("filter", "")  # missing attr -> fails closed


def test_admin_bypass_emits_allow_all():
    rules = generate_rules(_users(), [_orders_policy()], admin_bypass=True)
    top = rules["tables"][0]
    assert "root" in top["user"]
    assert "SELECT" in top["privileges"] and top["catalog"] == ".*"
    # admin should NOT also get a per-table filtered rule
    assert not any(r.get("user") == "^root$" and r.get("filter") for r in rules["tables"])


def test_default_deny_catch_all_present():
    rules = generate_rules(_users(), [_orders_policy()], default_deny=True)
    last = rules["tables"][-1]
    assert last["privileges"] == [] and last["catalog"] == ".*"
    assert rules_summary(rules)["default_deny"] is True


def test_default_deny_can_be_disabled():
    rules = generate_rules(_users(), [_orders_policy()], default_deny=False)
    assert not any(r.get("privileges") == [] and r["catalog"] == ".*" for r in rules["tables"])


def test_column_mask_emitted_per_user():
    mask = MaskPolicy(id="m1", catalog="iceberg", schema="sales", table="orders",
                      column="email", masking_type="partial_email",
                      role_map={"business_analyst": False})
    rules = generate_rules(_users(), [_orders_policy()], [mask])
    alice = [r for r in rules["tables"] if r.get("user") == "^alice$"][0]
    assert alice["columns"][0]["name"] == "email"
    assert "regexp_replace" in alice["columns"][0]["mask"]


def test_exempt_role_gets_no_filter_but_still_allowed():
    pol = RlsPolicy(id="p", catalog="iceberg", schema="sales", table="orders",
                    filter_expression="region = current_user_attribute('region')",
                    role_map={"business_analyst": True})  # exempt
    rules = generate_rules(_users(), [pol], admin_bypass=False)
    alice = [r for r in rules["tables"] if r.get("user") == "^alice$"][0]
    assert "filter" not in alice          # exempt -> no row filter
    assert alice["privileges"] == ["SELECT"]  # but still allowed (whitelisted)


def test_summary_counts():
    mask = MaskPolicy(id="m1", catalog="iceberg", schema="sales", table="orders",
                      column="email", masking_type="hash", role_map={"business_analyst": False})
    s = rules_summary(generate_rules(_users(), [_orders_policy()], [mask]))
    assert s["with_filter"] >= 2 and s["with_masks"] >= 2
