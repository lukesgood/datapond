"""What feeds a knowledge collection, and what a source feeds.

The product already computes this dependency and acts on it: when a connector sync
finishes, _invalidate_sink_collections marks any collection whose refresh_source
names that table stale, and the scheduler re-embeds it. The edge exists, it fires in
production, and it appeared nowhere in the UI — so "this table changed, which
collections are now wrong?" had no answer for the person who had to know.

Pure shaping, so the graph is testable without three tables.
"""
import pytest

from app.api.ai_vectors import build_lineage


def conn(id, name, type="postgresql"):
    return {"id": id, "name": name, "connector_type": type}


def job(connection_id, source_table, target_table, status="success"):
    return {"connection_id": connection_id, "source_table": source_table,
            "target_table": target_table, "last_run_status": status}


def coll(name, schema=None, table=None, enabled=True):
    src = {"type": "iceberg", "schema": schema, "table": table} if schema else None
    return {"name": name, "refresh_source": src, "refresh_enabled": enabled}


def _edge(out, a, b):
    return any(e["source"] == a and e["target"] == b for e in out["edges"])


def test_a_connector_reaches_the_collection_it_ultimately_feeds():
    out = build_lineage([conn("c1", "crm")],
                        [job("c1", "public.orders", "datapond.sales.orders")],
                        [coll("orders-kb", "sales", "orders")])
    assert _edge(out, "connector:crm", "table:sales.orders")
    assert _edge(out, "table:sales.orders", "collection:orders-kb")


def test_a_collection_with_no_scheduled_source_stands_alone():
    """Ingested once by hand. It has no upstream and nothing upstream can make it
    stale — which is exactly what someone auditing freshness needs to see."""
    out = build_lineage([], [], [coll("handbook")])
    assert any(n["id"] == "collection:handbook" for n in out["nodes"])
    assert out["edges"] == []


def test_a_table_feeding_two_collections_shows_both():
    out = build_lineage([conn("c1", "crm")],
                        [job("c1", "public.orders", "datapond.sales.orders")],
                        [coll("a", "sales", "orders"), coll("b", "sales", "orders")])
    assert _edge(out, "table:sales.orders", "collection:a")
    assert _edge(out, "table:sales.orders", "collection:b")


def test_a_table_nothing_consumes_is_not_drawn():
    """A connector syncing tables no collection uses would otherwise bury the part of
    the graph that matters under the part that does not."""
    out = build_lineage([conn("c1", "crm")],
                        [job("c1", "public.other", "datapond.sales.other")],
                        [coll("handbook")])
    assert not any(n["id"] == "table:sales.other" for n in out["nodes"])


def test_the_namespace_comes_from_the_target_not_a_default():
    """A sync can write into a namespace other than `default`; assuming otherwise
    silently breaks the match, which is how a stale collection looks fresh."""
    out = build_lineage([conn("c1", "crm")],
                        [job("c1", "public.orders", "datapond.archive.orders")],
                        [coll("kb", "archive", "orders")])
    assert _edge(out, "table:archive.orders", "collection:kb")


def test_a_paused_schedule_is_marked_rather_than_hidden():
    """The edge is real — the table still feeds it — but nothing will act on a
    change. Hiding it would claim the collection has no upstream at all."""
    out = build_lineage([conn("c1", "crm")],
                        [job("c1", "public.orders", "datapond.sales.orders")],
                        [coll("kb", "sales", "orders", enabled=False)])
    edge = next(e for e in out["edges"] if e["target"] == "collection:kb")
    assert edge["active"] is False


def test_a_failing_sync_is_carried_onto_the_node():
    out = build_lineage([conn("c1", "crm")],
                        [job("c1", "public.orders", "datapond.sales.orders", status="failed")],
                        [coll("kb", "sales", "orders")])
    node = next(n for n in out["nodes"] if n["id"] == "connector:crm")
    assert node["status"] == "failed"


def test_nothing_configured_is_an_empty_graph_not_an_error():
    assert build_lineage([], [], []) == {"nodes": [], "edges": []}
