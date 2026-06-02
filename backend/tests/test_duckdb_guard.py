"""
Unit tests for the DuckDB / direct-S3 read guard (RLS Layer 3). No cluster needed.
See docs/RLS_DESIGN.md §6.
"""
from app.rls.engine import RlsPolicy
from app.rls.duckdb_guard import (
    sensitive_tables, check_direct_read, seaweedfs_deny_prefixes, default_warehouse_prefix,
)


def _orders():
    return RlsPolicy(id="p1", catalog="iceberg", schema="sales", table="orders",
                     filter_expression="region = 'us-east'",
                     role_map={"business_analyst": False})


def test_sensitive_tables_lists_policy_tables():
    assert sensitive_tables([_orders()]) == ["iceberg.sales.orders"]


def test_disabled_policy_not_sensitive():
    p = _orders(); p.enabled = False
    assert sensitive_tables([p]) == []


def test_check_blocks_sensitive_table():
    r = check_direct_read("SELECT * FROM iceberg.sales.orders", [_orders()])
    assert r["blocked"] is True
    assert r["table"] == "iceberg.sales.orders"


def test_check_allows_non_policy_table():
    # public.events has no policy -> explorable via DuckDB
    r = check_direct_read("SELECT * FROM iceberg.public.events", [_orders()])
    assert r["blocked"] is False


def test_check_blocks_when_sensitive_joined_with_public():
    r = check_direct_read(
        "SELECT * FROM iceberg.public.events e JOIN iceberg.sales.orders o ON e.id = o.id",
        [_orders()])
    assert r["blocked"] is True
    assert r["table"] == "iceberg.sales.orders"


def test_deny_prefixes_uses_location_map_when_present():
    px = seaweedfs_deny_prefixes(
        ["iceberg.sales.orders"],
        location_map={"iceberg.sales.orders": "s3://warehouse/sales/orders-abc"},
    )
    assert px == ["warehouse/sales/orders-abc"]


def test_deny_prefixes_falls_back_to_convention():
    assert seaweedfs_deny_prefixes(["iceberg.sales.orders"]) == ["iceberg/sales/orders"]
    assert default_warehouse_prefix("iceberg.sales.orders") == "iceberg/sales/orders"
