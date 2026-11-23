"""Feedback from /ai/sql use back to the concept store (app/semantic/concept_feedback.py)."""
import asyncio

from app.semantic import concept_feedback as fb

CONCEPTS = [{"name": "고객", "terms": ["customer", "회원"]}, {"name": "플래티넘 고객", "terms": []},
            {"name": "주문", "terms": ["order"]}]
BINDINGS = [{"concept": "플래티넘 고객", "catalog": "iceberg", "namespace": "default", "table": "customers",
             "column": "tier", "role": "filter", "filter_sql": "tier = 'platinum'"}]


def test_words_strip_particles_and_stopwords():
    assert fb.words("VIP 고객의 지난달 주문은 몇 건인가요?") == ["vip", "고객", "주문"]
    assert fb.words("휴면회원별로 알려주세요") == ["휴면회원"]


def test_literals_resolve_aliases_in_and_booleans():
    sql = ("SELECT count(*) FROM iceberg.default.orders o JOIN iceberg.default.customers c "
           "ON c.id = o.customer_id WHERE c.tier = 'Platinum' AND o.status IN ('cancelled', 'returned') "
           "AND c.is_active = true")
    key = lambda x: (x["table"], x["column"], x["value"])
    assert sorted(fb.literals(sql), key=key) == sorted([
        {"table": "iceberg.default.customers", "column": "tier", "value": "Platinum"},
        {"table": "iceberg.default.customers", "column": "is_active", "value": "true"},
        {"table": "iceberg.default.orders", "column": "status", "value": "cancelled"},
        {"table": "iceberg.default.orders", "column": "status", "value": "returned"},
    ], key=key)
    one = fb.literals("SELECT 1 FROM default.orders WHERE status = 'x'", default_catalog="iceberg")
    assert one == [{"table": "iceberg.default.orders", "column": "status", "value": "x"}]
    assert fb.literals("not sql at all ((") == []


def _row(q, concepts=(), conflicts=(), left=(), lits=()):
    return {"question_masked": q, "concepts": list(concepts), "conflicts": list(conflicts),
            "conflicts_left": list(left), "literals": list(lits)}


def test_suggestions_need_two_questions_and_skip_what_is_known():
    tier = lambda v: {"table": "iceberg.default.customers", "column": "tier", "value": v}
    rows = [
        _row("VIP 고객 주문 수", ["고객", "주문"], lits=[tier("vip")]),
        _row("VIP 고객 매출", ["고객"], lits=[tier("vip")]),
        _row("휴면 고객 수", ["고객"], lits=[tier("platinum")]),
        _row("플래티넘 고객 반품", ["플래티넘 고객"], conflicts=["customers.id is 고객 but product_returns.product_id is 상품"],
             lits=[tier("platinum")]),
        _row("플래티넘 고객 반품 수", ["플래티넘 고객"], conflicts=["customers.id is 고객 but product_returns.product_id is 상품"],
             left=["customers.id is 고객 but product_returns.product_id is 상품"]),
    ]
    out = fb.suggest(rows, CONCEPTS, BINDINGS, [{"label": "매출", "synonyms": []}])
    assert [w["word"] for w in out["words"]] == ["vip", "반품"]     # 휴면 once; 고객/매출/플래티넘 known
    assert out["joins"] == [{"join": "customers.id is 고객 but product_returns.product_id is 상품",
                             "seen": 2, "unrepaired": 1, "example": "플래티넘 고객 반품"}]
    # 'platinum' is a segment already; 'vip' twice on a column that has segments
    assert [(v["value"], v["questions"], v["segments_on_column"]) for v in out["values"]] == [("vip", 2, True)]
    assert out["questions"] == 5


def test_hidden_catalog_literals_are_dropped():
    rows = [_row("q", lits=[{"table": "secret.s.t", "column": "c", "value": "v"},
                            {"table": "iceberg.default.t", "column": "c", "value": "v"}])]
    vis = fb.visible_rows(rows, lambda t: not t.startswith("secret."))
    assert [x["table"] for x in vis[0]["literals"]] == ["iceberg.default.t"]


def test_record_is_off_for_evaluations_and_never_raises(monkeypatch):
    monkeypatch.setattr(fb, "ENABLED", False)
    asyncio.run(fb.record({"id": "x"}, "q", "SELECT 1", [], [], []))   # returns without a pool
    monkeypatch.setattr(fb, "ENABLED", True)
    from app.api import connectors
    async def broken():
        raise RuntimeError("no db")
    monkeypatch.setattr(connectors, "get_db_pool", broken)
    asyncio.run(fb.record({"id": "x"}, "q", "SELECT 1", [], [], []))   # logged, not raised


def test_record_keeps_no_personal_values(monkeypatch):
    stored = {}
    class Conn:
        async def execute(self, sql, *args):
            if sql.startswith("INSERT"):
                stored["q"], stored["lits"] = args[1], args[5]
    class Acq:
        async def __aenter__(self): return Conn()
        async def __aexit__(self, *a): return False
    class Pool:
        def acquire(self, timeout=None): return Acq()
    from app.api import connectors
    async def pool():
        return Pool()
    monkeypatch.setattr(connectors, "get_db_pool", pool)
    sql = "SELECT 1 FROM iceberg.default.customers WHERE email = 'kim@example.com' AND tier = 'gold'"
    asyncio.run(fb.record({"id": None}, "kim@example.com 의 등급", sql, [], [], []))
    assert "kim@example.com" not in stored["q"]
    assert '"gold"' in stored["lits"] and "example.com" not in stored["lits"]
