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


def test_value_check_finds_the_stored_spelling():
    v = {"table": "iceberg.default.customers", "column": "tier", "value": "VIP", "questions": 2}
    sql = fb.value_check_sql(v)
    assert 'FROM "iceberg"."default"."customers"' in sql and "lower('VIP')" in sql
    assert fb.value_check_sql(dict(v, column="tier; DROP")) is None
    assert fb.value_check_sql(dict(v, value="O'Neil")).count("O''Neil") == 1
    got = fb.apply_check(v, [["vip", 3]], masked=False)
    assert (got["exists"], got["rows"], got["actual"], got["actual_rows"]) == (True, 0, "vip", 3)
    exact = fb.apply_check(dict(v, value="vip"), [["vip", 3]], masked=False)
    assert (exact["rows"], "actual" in exact) == (3, False)
    none = fb.apply_check(v, [], masked=False)
    assert (none["exists"], none["rows"]) == (False, 0)
    assert fb.apply_check(v, [["***", 3]], masked=True)["checked"] is False


def test_check_values_goes_through_the_governed_path(monkeypatch):
    from app.semantic import service
    calls = []
    async def execute(sql, user, origin="metric"):
        calls.append((origin, user["id"]))
        return {"rows": [["vip", 3]], "pii_masked": 0}
    monkeypatch.setattr(service, "_execute", execute)
    vals = [{"table": "iceberg.default.customers", "column": "tier", "value": "VIP"},
            {"table": "bad name", "column": "c", "value": "x"}]
    out = asyncio.run(fb.check_values(vals, {"id": "u1"}))
    assert calls == [("internal", "u1")]
    assert out[0]["actual"] == "vip" and out[1]["checked"] is False


def test_dismissed_suggestions_are_left_out():
    tier = lambda v: {"table": "iceberg.default.customers", "column": "tier", "value": v}
    join = "customers.id is 고객 but product_returns.product_id is 상품"
    rows = [_row("VIP 고객 반품", ["고객"], conflicts=[join], lits=[tier("vip")]),
            _row("VIP 고객 반품 수", ["고객"], conflicts=[join], lits=[tier("vip")])]
    before = fb.suggest(rows, CONCEPTS, BINDINGS)
    assert [w["word"] for w in before["words"]] == ["vip", "반품"] and before["joins"] and before["values"]
    key = fb.value_key(before["values"][0])
    assert key == "iceberg.default.customers.tier=vip"
    after = fb.suggest(rows, CONCEPTS, BINDINGS,
                       dismissed=[("word", "vip"), ("join", join), ("value", key)])
    assert [w["word"] for w in after["words"]] == ["반품"]
    assert after["joins"] == [] and after["values"] == []
    # a dismissal is per kind: dismissing the word 'vip' leaves the value 'vip' alone
    assert fb.suggest(rows, CONCEPTS, BINDINGS, dismissed=[("word", "vip")])["values"]


def test_record_soon_does_not_make_the_caller_wait(monkeypatch):
    done = []
    gate = {}

    async def slow_record(*a, **k):
        await gate["release"].wait()
        done.append(a[1])
    monkeypatch.setattr(fb, "record", slow_record)

    async def main():
        gate["release"] = asyncio.Event()
        fb.record_soon({"id": None}, "q1", "SELECT 1", [], [], [])
        assert done == [] and len(fb._PENDING) == 1     # returned before the write
        gate["release"].set()
        await asyncio.gather(*list(fb._PENDING))
        assert done == ["q1"] and not fb._PENDING       # held until done, then released
    asyncio.run(main())
    fb.record_soon({"id": None}, "q2", "SELECT 1", [], [], [])   # no loop: a no-op, no raise


def test_feedback_segments_record_their_own_source():
    from app.api.concepts import BindingBody
    from app.semantic.concepts import SOURCES
    assert "feedback" in SOURCES
    b = BindingBody(concept="VIP 고객", catalog="iceberg", table="default.customers", column="tier",
                    role="filter", filter_sql="tier = 'vip'", source="feedback")
    assert b.source == "feedback"
