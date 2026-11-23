"""Source keys carried to lake copies (app/source_keys.py) and the statistics profile
(app/table_profile.py)."""
import asyncio
import datetime as dt

import pytest
from fastapi import HTTPException

from app import source_keys as sk
from app import table_profile as tp

ROWS = [  # nspname, relname, attname, ref nsp, ref rel, ref att, contype — as pg_catalog returns
    ("public", "customers", "id", None, None, None, "p"),
    ("public", "orders", "id", None, None, None, "p"),
    ("public", "orders", "customer_id", "public", "customers", "id", "f"),
    ("public", "order_items", "order_id", "public", "orders", "id", "f"),
    ("public", "order_items", "product_id", "public", "products", "id", "f"),
]
CAT = "src_sample_e_commerce_db"


def test_passthrough_escapes_and_refuses_unknown_kinds():
    sql = sk.passthrough(CAT, "postgresql")
    assert sql.startswith(f"SELECT * FROM TABLE({CAT}.system.query(query => '")
    assert "IN (''p'', ''f'')" in sql                      # quotes doubled inside the literal
    assert sk.passthrough(CAT, "mysql") is None
    assert sk.passthrough("bad;name", "postgresql") is None


def test_keys_carry_to_lake_copies_only_when_both_ends_are_synced():
    keys = sk.parse(CAT, ROWS)
    jobs = [{"connection_id": "c1", "source_table": "customers", "target_table": "datapond.default.customers", "target_catalog": None},
            {"connection_id": "c1", "source_table": "public.orders", "target_table": "datapond.default.public.orders", "target_catalog": None},
            {"connection_id": "c1", "source_table": "public.order_items", "target_table": "datapond.default.public.order_items", "target_catalog": None}]
    copies = sk.lake_map(jobs, {"c1": CAT}, lambda name: "iceberg")
    assert copies == {f"{CAT}.public.customers": "iceberg.default.customers",
                      f"{CAT}.public.orders": "iceberg.default.orders",
                      f"{CAT}.public.order_items": "iceberg.default.order_items"}
    lake = sk.carry(keys, copies)
    fks = [(k["table"], k["column"], k["ref_table"]) for k in lake if k["kind"] == "fk"]
    assert fks == [("iceberg.default.orders", "customer_id", "iceberg.default.customers"),
                   ("iceberg.default.order_items", "order_id", "iceberg.default.orders")]  # products not synced
    t = sk.for_table(keys + lake, "iceberg.default.orders")
    assert t["primary"] == ["id"]
    assert t["foreign"] == [{"column": "customer_id", "ref_table": "iceberg.default.customers", "ref_column": "id", "via": "sync"}]
    assert t["referenced_by"] == [{"table": "iceberg.default.order_items", "column": "order_id", "ref_column": "id"}]


def test_fk_edges_merge_into_the_graph():
    edges = sk.fk_edges([
        {"table": "iceberg.default.orders", "column": "customer_id", "kind": "fk",
         "ref_table": "iceberg.default.customers", "ref_column": "id", "via": "sync"},
        {"table": "iceberg.default.shipments", "column": "order_id", "kind": "fk",
         "ref_table": "iceberg.default.orders", "ref_column": "id", "via": "sync"}])
    graph = {"nodes": [{"id": "iceberg.default.orders"}, {"id": "iceberg.default.customers"}],
             "edges": [{"source": "iceberg.default.customers", "target": "iceberg.default.orders",
                        "evidence": "observed", "count": 41, "joins": []},
                       {"source": "iceberg.default.shipments", "target": "iceberg.default.orders",
                        "evidence": "candidate", "count": 0, "joins": []}]}
    out = sk.merge(graph, edges)
    by = {frozenset((e["source"], e["target"])): e for e in out["edges"]}
    observed = by[frozenset(("iceberg.default.customers", "iceberg.default.orders"))]
    assert (observed["evidence"], observed["count"], observed["via"]) == ("fk", 41, "sync")
    assert by[frozenset(("iceberg.default.shipments", "iceberg.default.orders"))]["evidence"] == "fk"
    assert len(out["edges"]) == 2                           # the guess was replaced, not kept
    assert "iceberg.default.shipments" in {n["id"] for n in out["nodes"]}


def test_stats_parse_redact_and_snapshots():
    rows = [["id", None, 1200.0, 0.0, None, "1", "1200"], ["email", 199.0, 1.0, 0.02, None, None, None],
            ["signup_date", None, 656.0, 0.0, None, "2023-01-15", "2026-05-01"], [None, None, None, None, 1200.0, None, None]]
    p = tp.parse_stats(rows)
    assert p["rows"] == 1200 and [c["name"] for c in p["columns"]] == ["id", "email", "signup_date"]
    r = tp.redact(p, {"signup_date"})
    sd = next(c for c in r["columns"] if c["name"] == "signup_date")
    assert (sd["low"], sd["high"], sd["hidden"], sd["distinct"]) == (None, None, True, 656.0)
    snaps = tp.parse_snapshots([(dt.datetime(2026, 11, 20, 3, 18), "append", {"added-records": "10", "total-records": "6000"})])
    assert snaps == [{"at": "2026-11-20T03:18:00", "operation": "append", "added_records": 10, "total_records": 6000}]


@pytest.fixture
def route(monkeypatch):
    from app import catalog_registry as reg
    from app.api import catalog as routes
    from app.catalog_registry import CatalogEntry
    reg.set_entries([CatalogEntry(name="AwsDataCatalog", kind="glue", engine_catalog="iceberg", is_default=True)])
    stats = {"rows": 1200, "snapshots": [], "columns": [
        {"name": "id", "nulls": 0.0, "distinct": 1200.0, "low": "1", "high": "1200"},
        {"name": "signup_date", "nulls": 0.0, "distinct": 656.0, "low": "2023-01-15", "high": "2026-05-01"}]}
    monkeypatch.setattr(tp, "read", lambda *a: dict(stats, columns=[dict(c) for c in stats["columns"]]))
    async def no_pii(*a):
        return set()
    monkeypatch.setattr(tp, "pii_columns", no_pii)
    yield routes, monkeypatch
    reg.reset()


ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}


def test_profile_route_withholds_under_row_policies_and_hides_masked_ranges(route):
    routes, mp = route
    async def gov(user, *a):
        return {"restricted": False, "masked": {"signup_date"}}
    mp.setattr(tp, "governance", gov)
    out = asyncio.run(routes.table_profile("default", "customers", user=ADMIN))
    sd = next(c for c in out["columns"] if c["name"] == "signup_date")
    assert out["rows"] == 1200 and sd["low"] is None and sd["hidden"]

    async def restricted(user, *a):
        return {"restricted": True, "masked": set()}
    mp.setattr(tp, "governance", restricted)
    out = asyncio.run(routes.table_profile("default", "customers", user=ADMIN))
    assert out["restricted"] and out["rows"] is None and out["columns"] == [{"name": "id"}, {"name": "signup_date"}]

    async def refused(user, *a):
        raise PermissionError("default deny")
    mp.setattr(tp, "governance", refused)
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.table_profile("default", "customers", user=ADMIN))
    assert e.value.status_code == 403
