"""What the metric service needs from the governed execution path."""
import asyncio

from app.api import queries


def test_metric_is_an_allowed_origin():
    assert "metric" in queries._ALLOWED_ORIGINS

    class R:
        origin = "metric"
    assert queries._safe_origin(R()) == "metric"


def test_rls_holder_collects_applied_ids():
    with queries.rls_applied_ids() as ids:
        queries._note_rls(["p1"], ["m1"])
        assert ids == ["p1", "m1"]
    queries._note_rls(["p2"], [])          # outside the block: nowhere to write, no error


def _relationship_filters(monkeypatch, **kwargs):
    filters = []

    class _Q:
        def filter(self, expr):
            filters.append(str(expr.compile(compile_kwargs={"literal_binds": True})))
            return self
        def order_by(self, *a, **k): return self
        def limit(self, n): return self
        def all(self): return []

    class _DB:
        def query(self, *cols): return _Q()

    monkeypatch.setattr(queries, "_catalog_schema_for_graph", lambda: {})
    asyncio.run(queries.catalog_relationships(
        days=30, db=_DB(), user={"id": "00000000-0000-0000-0000-0000000000aa"}, **kwargs))
    return filters


def test_relationships_exclude_metric_statements(monkeypatch):
    for kwargs in ({}, {"include_ai": True}):
        filters = _relationship_filters(monkeypatch, **kwargs)
        assert any("origin != 'metric'" in f for f in filters), kwargs
