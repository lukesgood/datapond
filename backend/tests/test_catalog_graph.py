"""Join relationships mined from what people actually ran.

docs/ONTOLOGY_FEASIBILITY_REPORT.md found LLM relation extraction to be the weakest
layer across every domain tested. Query history sidesteps that entirely: a join that
appears in query_history is not an inferred relationship, it is a recorded one.
"""
from app.api.catalog_graph import build_graph, extract_joins


def _pairs(sql):
    return {(j["left_table"], j["right_table"], j["left_column"], j["right_column"])
            for j in extract_joins(sql)}


def test_explicit_join_with_aliases():
    """Edges are undirected, so the pair is stored in a canonical (sorted) order —
    otherwise `a JOIN b` and `b JOIN a` would count as two relationships."""
    assert _pairs(
        "SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id"
    ) == {("sales.customers", "sales.orders", "id", "cust_id")}


def test_join_without_aliases():
    assert _pairs(
        "SELECT * FROM sales.orders JOIN sales.customers "
        "ON sales.orders.cust_id = sales.customers.id"
    ) == {("sales.customers", "sales.orders", "id", "cust_id")}


def test_chained_joins_produce_one_edge_each():
    out = _pairs(
        "SELECT * FROM a.t1 x JOIN b.t2 y ON x.k = y.k JOIN c.t3 z ON y.j = z.j"
    )
    assert ("a.t1", "b.t2", "k", "k") in out
    assert ("b.t2", "c.t3", "j", "j") in out
    assert len(out) == 2


def test_implicit_join_in_the_where_clause():
    assert _pairs(
        "SELECT * FROM sales.orders o, sales.customers c WHERE o.cust_id = c.id"
    ) == {("sales.customers", "sales.orders", "id", "cust_id")}


def test_self_join_is_not_a_relationship():
    assert _pairs("SELECT * FROM t.a x JOIN t.a y ON x.parent = y.id") == set()


def test_query_with_no_join():
    assert extract_joins("SELECT * FROM sales.orders WHERE amt > 10") == []


def test_unparseable_sql_yields_nothing():
    assert extract_joins("SELECT FROM WHERE (((") == []


def test_edges_are_direction_independent():
    """a JOIN b and b JOIN a are the same relationship."""
    one = extract_joins("SELECT * FROM s.a x JOIN s.b y ON x.k = y.k")[0]
    two = extract_joins("SELECT * FROM s.b y JOIN s.a x ON y.k = x.k")[0]
    assert one["key"] == two["key"]


# ── aggregation into a graph ──────────────────────────────────────────────────

HISTORY = [
    "SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id",
    "SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id",
    "SELECT * FROM sales.orders o JOIN ref.regions r ON o.region = r.code",
    "SELECT * FROM sales.customers",
    "not sql at all",
]


def test_graph_counts_how_often_each_join_was_used():
    g = build_graph(HISTORY)
    edge = next(e for e in g["edges"]
                if {e["source"], e["target"]} == {"sales.orders", "sales.customers"})
    assert edge["count"] == 2
    assert edge["joins"] == [{"left_column": "id", "right_column": "cust_id", "count": 2}]


def test_graph_nodes_include_tables_seen_without_a_join():
    g = build_graph(HISTORY)
    assert "sales.customers" in {n["id"] for n in g["nodes"]}
    assert "ref.regions" in {n["id"] for n in g["nodes"]}


def test_graph_node_carries_how_often_the_table_was_queried():
    g = build_graph(HISTORY)
    orders = next(n for n in g["nodes"] if n["id"] == "sales.orders")
    assert orders["query_count"] == 3


def test_graph_of_an_empty_history():
    g = build_graph([])
    assert g == {"nodes": [], "edges": []}


def test_graph_ignores_statements_it_cannot_parse():
    g = build_graph(["not sql at all", "@@@"])
    assert g["nodes"] == [] and g["edges"] == []


# ── endpoint ──────────────────────────────────────────────────────────────────

def test_relationships_endpoint_builds_the_graph_from_successful_history(monkeypatch):
    """History is the source; a failed query proves nothing about a relationship."""
    import asyncio
    import app.api.queries as q

    captured = {}

    class _Q:
        def __init__(self, rows): self._rows = rows
        def filter(self, *a, **k): captured.setdefault("filters", 0); captured["filters"] += 1; return self
        def order_by(self, *a, **k): return self
        def limit(self, n): captured["limit"] = n; return self
        def all(self): return self._rows

    class _DB:
        def query(self, *cols):
            return _Q([
                ("SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id",),
                ("SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id",),
            ])

    res = asyncio.run(q.catalog_relationships(days=30, db=_DB(),
                                              user={"id": "00000000-0000-0000-0000-0000000000aa"}))

    assert captured["filters"] >= 2, "must filter by time window and by success"
    edge = res["edges"][0]
    assert {edge["source"], edge["target"]} == {"sales.orders", "sales.customers"}
    assert edge["count"] == 2
    assert res["source"] == "query_history"
