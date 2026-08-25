"""Which tables RLS would let through.

RLS_DEFAULT_DENY is off by default, so enabling RLS on a database with no policies
changes nothing and blocks nothing. That is a defensible default — turning it on
strictly would refuse every query — but it makes the dangerous state and the safe
state look identical from the outside. An operator turns RLS on, sees no breakage,
and believes the data is governed.

This is the missing readout: which tables carry a policy, which do not, and what
default_deny would do to each. Pure — takes a table list and a policy list, touches
nothing.
"""
from app.rls.coverage import coverage


class P:
    """Minimal stand-in for RlsPolicy; coverage only reads the identity fields."""
    def __init__(self, catalog, schema, table):
        self.catalog, self.schema, self.table = catalog, schema, table


def test_a_table_with_a_policy_is_covered():
    out = coverage([("iceberg", "sales", "orders")], [P("iceberg", "sales", "orders")], [])
    assert out["covered"] == ["iceberg.sales.orders"]
    assert out["uncovered"] == []


def test_a_table_without_a_policy_is_reported():
    out = coverage([("iceberg", "sales", "orders")], [], [])
    assert out["uncovered"] == ["iceberg.sales.orders"]
    assert out["covered"] == []


def test_a_column_mask_alone_counts_as_coverage():
    """A table with only a masking policy is governed — the rows all come back, but
    the sensitive columns do not. Calling that uncovered would send an operator
    looking for a problem that is already solved."""
    out = coverage([("iceberg", "sales", "orders")], [], [P("iceberg", "sales", "orders")])
    assert out["covered"] == ["iceberg.sales.orders"]


def test_matching_ignores_case():
    """The engine lower-cases identifiers before matching, so a policy written on
    Orders must not read as a policy on nothing."""
    out = coverage([("Iceberg", "Sales", "Orders")], [P("iceberg", "sales", "orders")], [])
    assert out["uncovered"] == []


def test_a_policy_for_a_table_that_does_not_exist_is_reported_separately():
    """A policy on a dropped or renamed table protects nothing while still appearing
    in the policy list — the exact shape of a control everyone believes is on."""
    out = coverage([("iceberg", "sales", "orders")], [P("iceberg", "sales", "gone")], [])
    assert out["orphaned_policies"] == ["iceberg.sales.gone"]


def test_the_summary_counts_match_the_lists():
    tables = [("c", "s", f"t{i}") for i in range(5)]
    out = coverage(tables, [P("c", "s", "t0"), P("c", "s", "t1")], [])
    assert out["total"] == 5
    assert out["covered_count"] == 2
    assert out["uncovered_count"] == 3


def test_what_default_deny_would_block_is_stated_outright():
    """The number an operator actually needs before flipping the switch."""
    out = coverage([("c", "s", "a"), ("c", "s", "b")], [P("c", "s", "a")], [])
    assert out["would_block_under_default_deny"] == ["c.s.b"]


def test_an_empty_catalog_is_not_an_error():
    out = coverage([], [], [])
    assert out["total"] == 0 and out["uncovered"] == []


def test_the_lists_are_sorted_so_the_output_is_stable():
    tables = [("c", "s", "z"), ("c", "s", "a"), ("c", "s", "m")]
    assert coverage(tables, [], [])["uncovered"] == ["c.s.a", "c.s.m", "c.s.z"]


# ── the warning ───────────────────────────────────────────────────────────────
#
# An endpoint nobody calls is not visibility. The state worth saying out loud is
# "RLS is on, and it is letting N tables through" — which reads as protection to
# everyone who turned it on.

from app.rls.coverage import startup_warning


def test_nothing_is_said_when_rls_is_off():
    assert startup_warning(rls_enabled=False, default_deny=False, uncovered=9) is None


def test_nothing_is_said_when_strict_mode_is_on():
    """default_deny closes the gap; there is nothing to warn about."""
    assert startup_warning(rls_enabled=True, default_deny=True, uncovered=9) is None


def test_nothing_is_said_when_every_table_has_a_policy():
    assert startup_warning(rls_enabled=True, default_deny=False, uncovered=0) is None


def test_the_warning_names_the_number_of_unprotected_tables():
    msg = startup_warning(rls_enabled=True, default_deny=False, uncovered=9)
    assert msg and "9" in msg


def test_the_warning_names_the_setting_that_changes_it():
    msg = startup_warning(rls_enabled=True, default_deny=False, uncovered=1)
    assert "RLS_DEFAULT_DENY" in msg
