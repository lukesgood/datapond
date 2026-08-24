"""Plan review runs on real Athena output, not invented strings.

The fixtures in tests/fixtures/ are verbatim captures from the live cluster for:

    SELECT c.tier, count(*) n, sum(o.amt) total
    FROM planlab.orders o JOIN planlab.customers c ON o.cust_id = c.cust_id
    WHERE o.region = 'us' GROUP BY c.tier ORDER BY total DESC

The first thing a reviewer needs is not a performance grade — it is which tables the
query actually touches. A generated query can be perfectly valid and still read the
wrong table: asked for a table that does not exist, the model silently substituted a
real one and EXPLAIN (TYPE VALIDATE) passed it (observed live 2026-08-24).
"""
from pathlib import Path

import pytest

from app.api.plan_review import parse_distributed_plan, parse_io_plan, review

FIXTURES = Path(__file__).parent / "fixtures"
IO_PLAN = (FIXTURES / "athena_io_plan.json").read_text()
DIST_PLAN = (FIXTURES / "athena_distributed_plan.txt").read_text()


# ── what does this query actually read ────────────────────────────────────────

def test_io_plan_lists_every_table_the_query_reads():
    out = parse_io_plan(IO_PLAN)
    assert {(t["schema"], t["table"]) for t in out["tables"]} == {
        ("planlab", "orders"), ("planlab", "customers")
    }


def test_io_plan_reports_which_predicates_reached_the_table():
    out = parse_io_plan(IO_PLAN)
    orders = next(t for t in out["tables"] if t["table"] == "orders")
    customers = next(t for t in out["tables"] if t["table"] == "customers")
    assert [f["column"] for f in orders["filters"]] == ["region"]
    assert "us" in orders["filters"][0]["summary"]
    assert customers["filters"] == [], "no predicate was pushed to customers"


def test_io_plan_reports_that_row_estimates_are_unavailable():
    """Iceberg tables here carry no statistics, so Trino's cost model emits NaN.
    Saying so is the honest output; a fabricated number would not be."""
    assert parse_io_plan(IO_PLAN)["estimates_available"] is False


def test_io_plan_survives_an_empty_or_broken_payload():
    assert parse_io_plan("")["tables"] == []
    assert parse_io_plan("not json at all")["tables"] == []


# ── structural signals from the distributed plan ──────────────────────────────

def test_distributed_plan_extracts_the_join_and_its_distribution():
    out = parse_distributed_plan(DIST_PLAN)
    assert len(out["joins"]) == 1
    j = out["joins"][0]
    assert j["type"] == "InnerJoin"
    assert j["distribution"] == "REPLICATED"
    assert "cust_id" in j["criteria"]


def test_distributed_plan_extracts_scans_with_pushed_filters():
    out = parse_distributed_plan(DIST_PLAN)
    scans = {s["table"]: s for s in out["scans"]}
    assert "planlab.orders" in scans
    assert scans["planlab.orders"]["filter"] is not None
    assert "region" in scans["planlab.orders"]["filter"]


def test_distributed_plan_notices_dynamic_filtering():
    assert parse_distributed_plan(DIST_PLAN)["dynamic_filters"] is True


def test_distributed_plan_counts_fragments():
    assert parse_distributed_plan(DIST_PLAN)["fragments"] >= 3


def test_distributed_plan_survives_empty_input():
    out = parse_distributed_plan("")
    assert out["joins"] == [] and out["scans"] == [] and out["fragments"] == 0


# ── the combined review ───────────────────────────────────────────────────────

def test_review_leads_with_the_accessed_tables():
    out = review(IO_PLAN, DIST_PLAN)
    assert [f"{t['schema']}.{t['table']}" for t in out["accessed"]] == [
        "planlab.orders", "planlab.customers"
    ]


def test_review_flags_a_scan_with_no_predicate():
    out = review(IO_PLAN, DIST_PLAN)
    codes = {f["code"] for f in out["findings"]}
    assert "unfiltered_scan" in codes, "customers is read with no filter at all"
    finding = next(f for f in out["findings"] if f["code"] == "unfiltered_scan")
    assert "customers" in finding["message"]


def test_review_reports_missing_statistics_rather_than_guessing():
    codes = {f["code"] for f in review(IO_PLAN, DIST_PLAN)["findings"]}
    assert "no_statistics" in codes


def test_review_flags_a_cross_join_as_critical():
    dist = DIST_PLAN.replace("InnerJoin[criteria", "CrossJoin[criteria")
    out = review(IO_PLAN, dist)
    crit = [f for f in out["findings"] if f["severity"] == "critical"]
    assert any(f["code"] == "cross_join" for f in crit)


def test_review_flags_a_sort_with_no_limit():
    codes = {f["code"] for f in review(IO_PLAN, DIST_PLAN)["findings"]}
    assert "sort_without_limit" in codes


def test_review_is_usable_when_only_the_io_plan_is_available():
    """TYPE DISTRIBUTED is a second engine round-trip; the table list must not
    depend on it."""
    out = review(IO_PLAN, None)
    assert len(out["accessed"]) == 2
    assert isinstance(out["findings"], list)
