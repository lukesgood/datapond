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

    monkeypatch.setattr(q, "_catalog_schema_for_graph", lambda: {})
    res = asyncio.run(q.catalog_relationships(days=30, db=_DB(),
                                              user={"id": "00000000-0000-0000-0000-0000000000aa"}))

    assert captured["filters"] >= 2, "must filter by time window and by success"
    edge = res["edges"][0]
    assert {edge["source"], edge["target"]} == {"sales.orders", "sales.customers"}
    assert edge["count"] == 2
    assert res["source"] == "query_history+catalog"


# ── candidate relationships from catalog metadata ─────────────────────────────
# History alone leaves a new catalog blank: the person who needs the diagram has no
# query history, and the person with history already knows the joins. Candidates
# fill day zero — clearly marked as guesses, never mixed with observed evidence.

from app.api.catalog_graph import candidate_joins  # noqa: E402

SCHEMA = {
    "sales.orders":    [{"name": "id", "type": "int"}, {"name": "cust_id", "type": "int"},
                        {"name": "status", "type": "varchar"}, {"name": "amt", "type": "double"}],
    "sales.customers": [{"name": "id", "type": "int"}, {"name": "cust_id", "type": "int"},
                        {"name": "status", "type": "varchar"}, {"name": "name", "type": "varchar"}],
    "ref.regions":     [{"name": "code", "type": "varchar"}, {"name": "name", "type": "varchar"}],
}


def _cand(schema):
    return {(c["source"], c["target"], c["joins"][0]["left_column"], c["joins"][0]["right_column"])
            for c in candidate_joins(schema)}


def test_matching_key_column_on_both_tables_is_a_candidate():
    assert ("sales.customers", "sales.orders", "cust_id", "cust_id") in _cand(SCHEMA)


def test_foreign_key_naming_matches_the_other_tables_primary_key():
    """orders.cust_id -> customers.id, the most common FK convention."""
    got = _cand({"sales.orders":    [{"name": "cust_id", "type": "int"}],
                 "sales.customers": [{"name": "id", "type": "int"}]})
    assert ("sales.customers", "sales.orders", "id", "cust_id") in got


def test_bare_id_columns_are_not_a_relationship():
    """Every table has `id`; matching them all would connect the whole catalog."""
    got = _cand(SCHEMA)
    assert not any(lc == "id" and rc == "id" for _s, _t, lc, rc in got)


def test_generic_columns_are_ignored():
    got = _cand(SCHEMA)
    assert not any(lc in ("status", "name") for _s, _t, lc, _rc in got)


def test_type_mismatch_is_not_a_candidate():
    got = _cand({"a.t1": [{"name": "cust_id", "type": "int"}],
                 "a.t2": [{"name": "cust_id", "type": "varchar"}]})
    assert got == set()


def test_a_table_is_not_a_candidate_against_itself():
    got = candidate_joins({"a.t1": [{"name": "cust_id", "type": "int"}]})
    assert got == []


def test_candidates_are_marked_as_candidates():
    for c in candidate_joins(SCHEMA):
        assert c["evidence"] == "candidate"
        assert c["count"] == 0
        assert c["reason"]


# ── merging the two layers ────────────────────────────────────────────────────

def test_observed_edges_are_marked_observed():
    g = build_graph(["SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id"])
    assert g["edges"][0]["evidence"] == "observed"


def test_a_candidate_is_dropped_when_the_pair_was_actually_observed():
    """Once people have run the join, the guess adds nothing but noise."""
    g = build_graph(
        ["SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id"],
        schema=SCHEMA,
    )
    pairs = [(e["source"], e["target"]) for e in g["edges"]]
    assert pairs.count(("sales.customers", "sales.orders")) == 1
    edge = next(e for e in g["edges"] if {e["source"], e["target"]}
                == {"sales.orders", "sales.customers"})
    assert edge["evidence"] == "observed"


def test_candidates_appear_when_there_is_no_history_at_all():
    g = build_graph([], schema=SCHEMA)
    assert g["edges"], "a fresh catalog must still show something"
    assert all(e["evidence"] == "candidate" for e in g["edges"])
    assert {n["id"] for n in g["nodes"]} >= {"sales.orders", "sales.customers"}


# ── origin: keep the assistant out of its own evidence ────────────────────────
# Ask AI generates a join -> the user runs it -> it lands in query_history -> it
# becomes an "observed relationship". A guess laundered into evidence. The origin
# column breaks that loop.

def test_relationships_endpoint_excludes_ai_generated_history_by_default(monkeypatch):
    import asyncio
    import app.api.queries as q

    filters = []

    class _Q:
        def filter(self, expr):
            filters.append(str(expr))
            return self
        def order_by(self, *a, **k): return self
        def limit(self, n): return self
        def all(self): return []

    class _DB:
        def query(self, *cols): return _Q()

    monkeypatch.setattr(q, "_catalog_schema_for_graph", lambda: {})
    asyncio.run(q.catalog_relationships(days=30, db=_DB(),
                                        user={"id": "00000000-0000-0000-0000-0000000000aa"}))
    assert any("origin" in f for f in filters), "ai_sql history must be filtered out"


def test_relationships_endpoint_can_include_ai_history_on_request(monkeypatch):
    import asyncio
    import app.api.queries as q

    filters = []

    class _Q:
        def filter(self, expr):
            filters.append(str(expr))
            return self
        def order_by(self, *a, **k): return self
        def limit(self, n): return self
        def all(self): return []

    class _DB:
        def query(self, *cols): return _Q()

    monkeypatch.setattr(q, "_catalog_schema_for_graph", lambda: {})
    res = asyncio.run(q.catalog_relationships(days=30, include_ai=True, db=_DB(),
                                              user={"id": "00000000-0000-0000-0000-0000000000aa"}))
    assert not any("origin" in f for f in filters)
    assert res["includes_ai_generated"] is True


# ── detail for a selected node or edge ────────────────────────────────────────
# The diagram is only worth clicking if selecting something tells you more than the
# picture already did.

def test_nodes_carry_their_columns_when_the_schema_is_known():
    g = build_graph([], schema=SCHEMA)
    orders = next(n for n in g["nodes"] if n["id"] == "sales.orders")
    assert {c["name"] for c in orders["columns"]} == {"id", "cust_id", "status", "amt"}


def test_nodes_without_schema_information_carry_no_columns():
    g = build_graph(["SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id"])
    assert all(n["columns"] == [] for n in g["nodes"])


def test_edges_offer_a_join_statement_to_start_from():
    """Reconstructed from the parsed keys, never echoed from history: a stored
    statement can carry literals in its WHERE clause that the reader should not see."""
    g = build_graph(["SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id"])
    sql = g["edges"][0]["join_sql"]
    assert sql.startswith("SELECT")
    assert "sales.customers" in sql and "sales.orders" in sql
    assert "JOIN" in sql and "ON" in sql
    assert "LIMIT" in sql


def test_the_join_statement_never_repeats_a_stored_predicate():
    g = build_graph([
        "SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id "
        "WHERE c.ssn = '123-45-6789'"
    ])
    assert "123-45-6789" not in g["edges"][0]["join_sql"]
    assert "ssn" not in g["edges"][0]["join_sql"]


def test_an_edge_lists_every_key_pair_that_was_used():
    g = build_graph([
        "SELECT * FROM sales.orders o JOIN sales.customers c ON o.cust_id = c.id",
        "SELECT * FROM sales.orders o JOIN sales.customers c ON o.alt_id = c.id",
    ])
    edge = g["edges"][0]
    assert {(j["left_column"], j["right_column"]) for j in edge["joins"]} == {
        ("id", "cust_id"), ("id", "alt_id")
    }
