"""
Unit tests for the RLS enforcement engine (backend Layer 1).

These run WITHOUT a cluster — they exercise policy resolution, attribute binding,
column masking, default_deny, admin bypass, exemptions, and sqlglot rewriting
purely on SQL strings. See docs/RLS_DESIGN.md.
"""
import os
import pytest

from app.rls.engine import (
    UserContext, RlsPolicy, MaskPolicy, RlsDenied,
    enforce, bind_attributes, applicable_policies, combined_filter,
    mask_expression, sql_literal,
)


# ── fixtures ────────────────────────────────────────────────────────────────

def analyst(region="us-east", roles=("business_analyst",)):
    return UserContext(
        user_id="u1", username="alice", roles=list(roles),
        attributes={"region": region, "department": "sales"},
    )


def orders_region_policy(roles=None):
    return RlsPolicy(
        id="p-orders-region",
        catalog="iceberg", schema="sales", table="orders",
        filter_expression="region = current_user_attribute('region')",
        priority=0, enabled=True,
        role_map=roles if roles is not None else {"business_analyst": False},
    )


# ── attribute binding ───────────────────────────────────────────────────────

def test_sql_literal_escapes_quotes():
    assert sql_literal("o'brien") == "'o''brien'"
    assert sql_literal(None) == "NULL"
    assert sql_literal(42) == "42"
    assert sql_literal(True) == "TRUE"


def test_bind_attributes_substitutes_known_key():
    out = bind_attributes("region = current_user_attribute('region')", {"region": "eu-west"})
    assert out == "region = 'eu-west'"


def test_bind_attributes_unknown_key_fails_closed_to_null():
    out = bind_attributes("region = current_user_attribute('nope')", {"region": "x"})
    assert out == "region = NULL"


def test_bind_attributes_blocks_injection_via_value():
    # a malicious attribute value must be escaped, not interpolated as SQL
    out = bind_attributes("region = current_user_attribute('region')", {"region": "x' OR '1'='1"})
    assert out == "region = 'x'' OR ''1''=''1'"


# ── policy resolution ───────────────────────────────────────────────────────

def test_applicable_policy_matches_user_role():
    pols = applicable_policies([orders_region_policy()], analyst())
    assert [p.id for p in pols] == ["p-orders-region"]


def test_exempt_role_frees_user():
    pol = orders_region_policy(roles={"business_analyst": True})  # exempt
    assert applicable_policies([pol], analyst()) == []


def test_policy_not_targeting_user_role_is_skipped():
    pol = orders_region_policy(roles={"data_engineer": False})
    assert applicable_policies([pol], analyst()) == []


def test_combined_filter_and_joins_multiple():
    p1 = orders_region_policy()
    p2 = RlsPolicy(id="p2", catalog="iceberg", schema="sales", table="orders",
                   filter_expression="active = true", priority=1,
                   role_map={"business_analyst": False})
    f = combined_filter(applicable_policies([p1, p2], analyst()), analyst())
    assert f == "(region = 'us-east') AND (active = true)"


# ── end-to-end rewrite ──────────────────────────────────────────────────────

def test_enforce_wraps_table_with_filter():
    res = enforce("SELECT id, region FROM iceberg.sales.orders",
                  analyst(), [orders_region_policy()])
    assert "p-orders-region" in res.applied_policy_ids
    low = res.sql.lower()
    assert "where (region = 'us-east')" in low
    assert "iceberg.sales.orders" in low
    # the original projection is preserved outside the subquery
    assert res.sql.strip().lower().startswith("select id, region from (")


def test_enforce_dialect_param_exists():
    import inspect
    assert "dialect" in inspect.signature(enforce).parameters


def test_enforce_athena_dialect_wraps_table():
    # Athena (Presto-derived) dialect must round-trip the same rewrite without error.
    res = enforce("SELECT id, region FROM iceberg.sales.orders",
                  analyst(), [orders_region_policy()], dialect="athena")
    assert "p-orders-region" in res.applied_policy_ids
    assert "region = 'us-east'" in res.sql.lower()
    assert "iceberg.sales.orders" in res.sql.lower()


def test_enforce_unqualified_table_uses_defaults():
    # default catalog=iceberg schema=default; register a policy on that key
    pol = RlsPolicy(id="pd", catalog="iceberg", schema="default", table="t",
                    filter_expression="dept = current_user_attribute('department')",
                    role_map={"business_analyst": False})
    res = enforce("SELECT * FROM t", analyst(), [pol])
    assert "dept = 'sales'" in res.sql.lower()


def test_default_deny_blocks_table_without_policy(monkeypatch):
    # default_deny is now opt-in via RLS_DEFAULT_DENY; with it ON, a table with no
    # policy is blocked (the original strict behavior).
    monkeypatch.setenv("RLS_DEFAULT_DENY", "true")
    with pytest.raises(RlsDenied) as e:
        enforce("SELECT * FROM iceberg.sales.secret", analyst(), [])
    assert "default_deny" in str(e.value)
    assert e.value.table == "iceberg.sales.secret"


def test_no_policy_passes_through_when_default_deny_off(monkeypatch):
    # RLS_DEFAULT_DENY off (the default): a policy-empty query is returned UNTOUCHED,
    # so flipping RLS_ENABLED on a policy-empty database is a true no-op. The engine
    # must not even round-trip the SQL through sqlglot in this case.
    monkeypatch.delenv("RLS_DEFAULT_DENY", raising=False)
    sql = "SELECT * FROM iceberg.sales.secret WHERE ts > date '2026-01-01'"
    res = enforce(sql, analyst(), [])
    assert res.sql == sql  # byte-for-byte, no sqlglot re-serialization
    assert res.applied_policy_ids == []


def test_no_policy_passes_through_even_if_unparseable_when_default_deny_off(monkeypatch):
    # The no-op short-circuit runs BEFORE the parser, so a policy-empty database can
    # never 403 a live query on a sqlglot dialect gap.
    monkeypatch.delenv("RLS_DEFAULT_DENY", raising=False)
    weird = "SELECT some_athena_only_construct FROM t /*+ HINT */"
    res = enforce(weird, analyst(), [])
    assert res.sql == weird


def test_unparseable_sql_fails_closed():
    # With a policy present the parser runs, and unparseable SQL still fails closed.
    with pytest.raises(RlsDenied):
        enforce("SELECT FROM WHERE )(", analyst(), [orders_region_policy()])


def test_admin_denied_by_default(monkeypatch):
    # admin (no bypass) + default_deny ON + no policy -> still blocked.
    monkeypatch.delenv("RLS_ADMIN_BYPASS", raising=False)
    monkeypatch.setenv("RLS_DEFAULT_DENY", "true")
    admin = UserContext(user_id="a", username="root", roles=["admin"], attributes={})
    with pytest.raises(RlsDenied):
        enforce("SELECT * FROM iceberg.x.y", admin, [])


def test_admin_bypass_when_enabled(monkeypatch):
    monkeypatch.setenv("RLS_ADMIN_BYPASS", "true")
    admin = UserContext(user_id="a", username="root", roles=["admin"], attributes={})
    res = enforce("SELECT * FROM iceberg.x.y", admin, [])
    assert res.sql == "SELECT * FROM iceberg.x.y"


def test_sensitive_block_denies_policy_table():
    with pytest.raises(RlsDenied) as e:
        enforce("SELECT * FROM iceberg.sales.orders", analyst(),
                [orders_region_policy()], sensitive_block=True)
    assert "direct read" in str(e.value)


# ── column masking ──────────────────────────────────────────────────────────

def test_mask_expression_variants():
    m = MaskPolicy(id="m", catalog="c", schema="s", table="t", column="email",
                   masking_type="partial_email")
    assert "regexp_replace" in mask_expression("email", m)
    assert mask_expression("x", MaskPolicy("m", "c", "s", "t", "x", "null")) == "NULL"
    assert "sha256" in mask_expression("x", MaskPolicy("m", "c", "s", "t", "x", "hash"))


def test_enforce_applies_mask_in_projection():
    mask = MaskPolicy(id="m-email", catalog="iceberg", schema="sales", table="orders",
                      column="email", masking_type="partial_email",
                      role_map={"business_analyst": False})
    res = enforce("SELECT email FROM iceberg.sales.orders",
                  analyst(), [orders_region_policy()], [mask])
    assert "m-email" in res.applied_mask_ids
    low = res.sql.lower()
    assert "except" in low and "regexp_replace" in low


def test_enforce_mask_survives_athena_dialect():
    # The SELECT * EXCEPT (col), <mask> AS col rewrite must round-trip on athena too.
    mask = MaskPolicy(id="m-email", catalog="iceberg", schema="sales", table="orders",
                      column="email", masking_type="partial_email",
                      role_map={"business_analyst": False})
    res = enforce("SELECT email FROM iceberg.sales.orders",
                  analyst(), [orders_region_policy()], [mask], dialect="athena")
    assert "m-email" in res.applied_mask_ids
    low = res.sql.lower()
    assert "except" in low and "regexp_replace" in low
