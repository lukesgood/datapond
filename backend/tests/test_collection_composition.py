"""What a collection is actually made of.

The card said "3 sources" and nothing could say which three. `ai_chunks.source` and
`source_group` have carried it since ingest, and no endpoint returned it — so the one
question someone asks about a collection they did not build ("where did this come
from?") had no answer anywhere in the product.

The shaping is pure and tested here; the query and its ACL are exercised against the
live database.
"""
import pytest

from app.api.ai_vectors import shape_composition


def _row(source, chunks, last=None, group=None):
    return {"source": source, "chunks": chunks, "last_ingested": last, "source_group": group}


def test_each_source_is_reported_with_its_share():
    out = shape_composition([_row("policy.pdf", 30), _row("faq.md", 10)], refresh_source=None)
    by = {s["source"]: s for s in out["sources"]}
    assert by["policy.pdf"]["chunks"] == 30
    assert out["total_chunks"] == 40


def test_the_largest_source_is_listed_first():
    out = shape_composition([_row("small", 1), _row("big", 99)], refresh_source=None)
    assert [s["source"] for s in out["sources"]] == ["big", "small"]


def test_a_source_with_no_name_is_still_counted():
    """Text pasted into the box has no filename. Dropping it would make the parts
    disagree with the total, and the total is the number people trust."""
    out = shape_composition([_row(None, 5)], refresh_source=None)
    assert out["sources"][0]["source"] == "(pasted text)"
    assert out["total_chunks"] == 5


def test_the_scheduled_source_is_marked():
    """A scheduled source is replaced wholesale on every refresh; the others were
    ingested once and stay until someone removes them. Telling them apart is the
    difference between 'this is stale' and 'this is finished'."""
    out = shape_composition(
        [_row("iceberg://sales.orders", 40, group="iceberg:sales.orders.body"),
         _row("handbook.pdf", 5)],
        refresh_source={"type": "iceberg", "schema": "sales", "table": "orders",
                        "text_column": "body"})
    by = {s["source"]: s for s in out["sources"]}
    assert by["iceberg://sales.orders"]["scheduled"] is True
    assert by["handbook.pdf"]["scheduled"] is False


def test_a_schedule_with_no_matching_chunks_is_reported(): 
    """A schedule pointing at a table that has never produced a chunk looks like a
    working pipeline from the Schedule tab. It is not."""
    out = shape_composition([_row("handbook.pdf", 5)],
                            refresh_source={"type": "iceberg", "schema": "s",
                                            "table": "t", "text_column": "c"})
    assert out["scheduled_source_has_no_chunks"] is True


def test_no_schedule_means_no_such_warning():
    out = shape_composition([_row("handbook.pdf", 5)], refresh_source=None)
    assert out["scheduled_source_has_no_chunks"] is False


def test_an_empty_collection_is_not_an_error():
    out = shape_composition([], refresh_source=None)
    assert out == {"sources": [], "total_chunks": 0, "scheduled_source_has_no_chunks": False}


def test_an_s3_schedule_matches_its_own_group_shape():
    out = shape_composition([_row("s3://bucket/docs/a.txt", 3, group="s3:bucket/docs")],
                            refresh_source={"type": "s3", "bucket": "bucket", "prefix": "docs"})
    assert out["sources"][0]["scheduled"] is True
