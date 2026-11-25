"""Data Map step 2: search by column name and by business word (app/catalog_search.py)."""
from app import catalog_search as cs

INDEX = {
    ("iceberg", "default", "customers"): [
        {"name": "id", "type": "bigint"}, {"name": "email", "type": "varchar"},
        {"name": "full_name", "type": "varchar"}, {"name": "tier", "type": "varchar"}],
    ("iceberg", "default", "orders"): [
        {"name": "id", "type": "bigint"}, {"name": "customer_id", "type": "bigint"},
        {"name": "status", "type": "varchar"}],
    ("iceberg", "default", "support_tickets"): [
        {"name": "id", "type": "bigint"}, {"name": "customer_id", "type": "bigint"}],
    ("src_sample_finance_db", "public", "invoices"): [
        {"name": "id", "type": "integer"}, {"name": "customer_email", "type": "varchar"}],
}
CONCEPTS = [
    {"name": "고객", "pii": True, "terms": ["customer", "회원", "구매자"], "description": "산다",
     "parent": None},
    {"name": "VIP 고객", "pii": False, "terms": ["vip"], "parent": "고객"},
    {"name": "주문", "pii": False, "terms": ["order"]},
]
BINDINGS = [
    {"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "customers",
     "column": "id", "role": "key"},
    {"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "orders",
     "column": "customer_id", "role": "key"},
    {"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "customers",
     "column": "email", "role": "attribute"},
    {"concept": "VIP 고객", "catalog": "iceberg", "namespace": "default", "table": "customers",
     "column": "tier", "role": "filter", "filter_sql": "tier = 'VIP'"},
    {"concept": "고객", "catalog": "hidden_cat", "namespace": "x", "table": "people",
     "column": "id", "role": "key"},
]
METRICS = [{"name": "customer_count", "label": "고객 수", "synonyms": ["회원 수"],
            "base_table": "iceberg.default.customers"},
           {"name": "secret_revenue", "label": "고객 매출", "synonyms": [],
            "base_table": "hidden_cat.x.sales"}]


def allowed(cat):
    return cat != "hidden_cat"


def run(q):
    return cs.search(q, INDEX, CONCEPTS, BINDINGS, METRICS, allowed)


def test_tokens():
    assert cs.tokens("  고객 이메일 ") == ["고객", "이메일"]
    assert cs.tokens("a customer") == ["customer"]          # one Latin letter dropped
    assert cs.tokens("키") == ["키"]                         # one Hangul syllable kept
    assert cs.tokens("") == []


def test_business_word_finds_columns_through_bindings():
    r = run("고객")
    cols = {(c["table"], c["column"]): c["why"] for c in r["columns"]}
    # No column or table is named 고객; the concept's bindings find them.
    assert cols[("customers", "id")] == "concept 고객"
    assert cols[("orders", "customer_id")] == "concept 고객"
    assert cols[("customers", "email")] == "concept 고객"
    names = [c["name"] for c in r["concepts"]]
    assert names == ["VIP 고객", "고객"]
    c = next(c for c in r["concepts"] if c["name"] == "고객")
    assert c["keys"] == ["default.customers.id", "default.orders.customer_id"]
    assert c["attributes"] == ["default.customers.email"]
    assert [s["filter_sql"] for s in r["segments"]] == ["tier = 'VIP'"]
    top = next(t for t in r["tables"] if t["table"] == "customers")
    assert "segment VIP 고객" in top["why"]
    assert [m["name"] for m in r["metrics"]] == ["customer_count"]


def test_hidden_catalog_never_appears():
    r = run("고객")
    flat = repr(r)
    assert "hidden_cat" not in flat and "secret_revenue" not in flat


def test_alias_matches_like_the_name():
    assert {c["column"] for c in run("구매자")["columns"]} >= {"id", "customer_id", "email"}


def test_column_name_search_across_catalogs():
    r = run("email")
    got = {(c["catalog"], c["table"], c["column"]) for c in r["columns"]}
    assert ("iceberg", "customers", "email") in got
    assert ("src_sample_finance_db", "invoices", "customer_email") in got
    # A name hit sorts before a concept hit of the same column set.
    assert all(c["why"] == "name" for c in r["columns"])


def test_tables_ranked_by_words_then_columns():
    r = run("customer")
    tables = [t["table"] for t in r["tables"]]
    # customers: table name + concept 고객 (alias customer) + columns; first.
    assert tables[0] == "customers"
    top = r["tables"][0]
    assert "name" in top["why"] and "concept 고객" in top["why"]
    assert "metric customer_count" in top["why"]


def test_two_words_rank_a_table_holding_both_higher():
    r = run("고객 status")
    assert r["tables"][0]["table"] == "orders"          # 고객 (customer_id) + status


def test_no_words_no_results():
    r = run("   ")
    assert r["tables"] == [] and r["columns"] == [] and r["concepts"] == []


def test_column_index_caches_and_survives_a_down_catalog():
    cs.reset_cache()
    calls = []
    clock = [0.0]

    def read(cat):
        calls.append(cat)
        if cat == "src_down":
            raise RuntimeError("down")
        return {(cat, "s", "t"): [{"name": "c", "type": "int"}]}

    idx = cs.column_index(["iceberg", "src_down"], read=read, now=lambda: clock[0])
    assert list(idx) == [("iceberg", "s", "t")]
    cs.column_index(["iceberg"], read=read, now=lambda: clock[0])
    assert calls == ["iceberg", "src_down"]                # cached
    clock[0] = cs.INDEX_TTL_S + 1
    cs.column_index(["iceberg"], read=read, now=lambda: clock[0])
    assert calls[-1] == "iceberg"                          # expired → re-read
    cs.reset_cache()


def test_find_tables_adds_column_and_concept_matches(monkeypatch):
    """MCP catalog.find_tables: name matches stay in `tables`; column and concept hits
    come back in `matches` with why, with the concepts the words name."""
    import asyncio
    from app import catalog_search
    from app.chat.analysis import catalog as cat_actions

    index = {("iceberg", "default", "customers"): [{"name": "id", "type": "bigint"}, {"name": "email", "type": "varchar"}],
             ("iceberg", "default", "orders"): [{"name": "id", "type": "bigint"}, {"name": "customer_id", "type": "bigint"}]}
    concepts = [{"name": "고객", "pii": True, "terms": ["customer"]}]
    bindings = [{"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "customers", "column": "id", "role": "key"},
                {"concept": "고객", "catalog": "iceberg", "namespace": "default", "table": "orders", "column": "customer_id", "role": "key"}]

    async def search_for(q, user, engine_catalogs=None):
        assert engine_catalogs == ["iceberg"]
        return catalog_search.search(q, index, concepts, bindings)

    class Entry:
        name = engine_catalog = "iceberg"
        is_default = True

    class Access:
        def entries(self):
            return [Entry()]

    class Reader:
        def list_namespaces(self):
            return ["default"]

        def list_tables(self, ns):
            return ["customers", "orders"]

    async def access(user):
        return Access()

    monkeypatch.setattr(catalog_search, "search_for", search_for)
    monkeypatch.setattr(cat_actions, "_access", access)
    monkeypatch.setattr(cat_actions, "get_catalog_reader", lambda name: Reader())
    out = asyncio.run(cat_actions.find_tables({"query": "고객 email"}, {"role": "admin"}))
    assert out["tables"] == []                                    # no table is named 고객 or email
    found = {m["table"]: m["why"] for m in out["matches"]}
    assert "concept 고객" in found["default.customers"] and "concept 고객" in found["default.orders"]
    assert out["concepts"][0]["name"] == "고객"
    assert "default.orders.customer_id" in out["concepts"][0]["keys"]
