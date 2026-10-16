import asyncio
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.ai_sql as m
from app import catalog_access, tool_call_log
from app import catalog_registry as reg
from app.api import auth
from app.catalog_registry import CatalogEntry
from app.semantic.context import metric_lines, suggest

M = [{"name": "revenue", "label": "매출", "synonyms": ["매출액", "sales"], "version": 3,
      "measure": "SUM(amount)", "filters": "status = 'paid'", "base_table": "iceberg.sales.orders",
      "time_column": "ordered_at", "dimensions": ["channel", "region"]},
     {"name": "orders", "label": "주문 수", "synonyms": [], "version": 1,
      "measure": "COUNT(*)", "filters": None, "base_table": "iceberg.sales.orders",
      "time_column": "ordered_at", "dimensions": ["channel"]}]


def test_block_lists_definitions_and_the_rule():
    block, ids = metric_lines(M, "지난달 매출")
    assert "Approved metric definitions" in block
    assert "revenue (매출; 매출액, sales): SUM(amount) FROM iceberg.sales.orders WHERE status = 'paid'" in block
    assert "use its expression and filters exactly" in block
    assert ids == ["revenue@v3", "orders@v1"]


def test_question_matches_go_first_and_the_cap_holds():
    many = [dict(M[1], name=f"m{i:02d}", label=f"지표{i}", version=1) for i in range(30)]
    _, ids = metric_lines(many + [M[0]], "매출 알려줘", limit=20)
    assert ids[0] == "revenue@v3" and len(ids) == 20


def test_no_metrics_no_block():
    assert metric_lines([], "x") == ("", [])


def test_suggestion_is_a_verbatim_label_or_synonym_match():
    assert suggest(M, "지난달 매출액 지역별") == {"name": "revenue", "dimensions": ["channel", "region"],
                                               "period_required": True}
    assert suggest(M, "고객 이탈률") is None


def test_longest_match_wins():
    # "주문 수" must not lose to a shorter accidental match
    assert suggest(M, "채널별 주문 수")["name"] == "orders"


def test_build_messages_includes_the_block():
    from app.api.ai_sql import _build_messages
    system, _ = _build_messages("TABLES", "q", None, metrics_block="Approved metric definitions:\n- x")
    assert "Approved metric definitions" in system
    system2, _ = _build_messages("TABLES", "q", None)
    assert "Approved metric definitions" not in system2


def test_response_has_the_new_fields():
    from app.api.ai_sql import AskResponse
    r = AskResponse(sql="", explanation="", has_ai=False)
    assert r.metrics_provided == [] and r.suggested_metric is None


ENG = {"id": "11111111-1111-1111-1111-111111111111", "username": "eng", "role": "ai_engineer"}


def test_prompt_carries_the_block_and_the_response_reports_it(monkeypatch):
    from app.semantic import context as mc
    reg.set_entries([CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg",
                                  is_default=True)])
    catalog_access.set_grants({})
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    prompts = []

    async def _record(**kw):
        return None
    monkeypatch.setattr(tool_call_log, "record", _record)
    monkeypatch.setattr(m, "_cfg", lambda: {"litellm_url": "http://litellm:4000",
                                            "litellm_model": "default", "master_key": ""})
    monkeypatch.setattr(m, "_get_schema_context",
                        lambda: "Available tables (catalog: iceberg):\n  iceberg.sales.orders: amount (double)")
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")
    monkeypatch.setattr(m, "validate_sql", lambda sql: (True, None))

    def _llm(system, messages):
        prompts.append(system)
        return '{"sql": "SELECT SUM(amount) FROM iceberg.sales.orders", "explanation": "x"}'
    monkeypatch.setattr(m, "_call_litellm", _llm)

    async def fake_for_caller(user, catalog=None):
        return M
    monkeypatch.setattr(mc, "for_caller", fake_for_caller)
    try:
        res = asyncio.run(m.generate_sql(m.AskRequest(question="지난달 매출"), user=ENG))
    finally:
        reg.reset()
    assert "revenue (매출; 매출액, sales)" in prompts[0]
    assert res.metrics_provided == ["revenue@v3", "orders@v1"]
    assert res.suggested_metric["name"] == "revenue"


def test_audit_row_cites_provided_definitions_with_the_context_prefix(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(req, user):
        return m.AskResponse(sql="SELECT 1", explanation="", has_ai=True, provider="litellm",
                             metrics_provided=["revenue@v3"])
    monkeypatch.setattr(m, "_generate_sql_impl", _impl)
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    async def _override():
        return ENG
    app.dependency_overrides[auth.require_user] = _override
    assert TestClient(app).post("/api/ai/sql", json={"question": "매출"}).status_code == 200
    assert calls[0]["citation_sources"] == ["context:metric:revenue@v3"]


def _route_env(monkeypatch, *, litellm_url="http://litellm:4000"):
    """Common stubs for driving generate_sql end to end; returns the recorded audit rows."""
    reg.set_entries([CatalogEntry(name="iceberg", kind="polaris", engine_catalog="iceberg",
                                  is_default=True)])
    catalog_access.set_grants({})
    monkeypatch.setenv("QUERY_ENGINE", "trino")
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)
    monkeypatch.setattr(m, "_cfg", lambda: {"litellm_url": litellm_url,
                                            "litellm_model": "default", "master_key": ""})
    monkeypatch.setattr(m, "_get_schema_context",
                        lambda: "Available tables (catalog: iceberg):\n  iceberg.sales.orders: amount (double)")
    monkeypatch.setattr(m, "egress_policy", lambda: "allow-external")
    monkeypatch.setattr(m, "validate_sql", lambda sql: (True, None))
    monkeypatch.setattr(m, "_call_litellm", lambda system, messages:
                        '{"sql": "SELECT SUM(amount) FROM iceberg.sales.orders", "explanation": "x"}')
    return calls


def test_no_ai_path_provides_nothing_but_may_suggest(monkeypatch):
    from app.semantic import context as mc
    calls = _route_env(monkeypatch, litellm_url="")

    async def fake_for_caller(user, catalog=None):
        return M
    monkeypatch.setattr(mc, "for_caller", fake_for_caller)
    try:
        res = asyncio.run(m.generate_sql(m.AskRequest(question="지난달 매출"), user=ENG))
    finally:
        reg.reset()
    assert res.has_ai is False
    assert res.metrics_provided == []
    assert res.suggested_metric["name"] == "revenue"
    assert not calls[0].get("citation_sources")


def _failing_context_is_non_blocking(monkeypatch, fake):
    from app.semantic import context as mc
    _route_env(monkeypatch)
    monkeypatch.setattr(mc, "for_caller", fake)
    try:
        return asyncio.run(m.generate_sql(m.AskRequest(question="지난달 매출"), user=ENG))
    finally:
        reg.reset()


def test_context_failure_does_not_block_the_route(monkeypatch):
    async def boom(user, catalog=None):
        raise RuntimeError("semantic tables missing")
    res = _failing_context_is_non_blocking(monkeypatch, boom)
    assert res.sql.startswith("SELECT SUM(amount)")
    assert res.metrics_provided == [] and res.suggested_metric is None


def test_hung_context_times_out_and_degrades(monkeypatch):
    monkeypatch.setattr(m, "_METRIC_CONTEXT_TIMEOUT_S", 0.05)

    async def hang(user, catalog=None):
        await asyncio.sleep(5)
        return M
    res = _failing_context_is_non_blocking(monkeypatch, hang)
    assert res.sql.startswith("SELECT SUM(amount)")
    assert res.metrics_provided == [] and res.suggested_metric is None


# ── for_caller ────────────────────────────────────────────────────────────────

class _Dim:
    def __init__(self, name):
        self.name = name


class _Ver:
    def __init__(self, version):
        self.version, self.measure, self.filters = version, "SUM(amount)", None
        self.catalog, self.base_table, self.time_column = "glue", "sales.orders", "ordered_at"
        self.dimensions = [_Dim("channel")]


class _Entry:
    engine_catalog = "AwsDataCatalog"


class _Access:
    def allows(self, name):
        return True

    def resolve(self, name=None):
        assert name == "glue"
        return _Entry()


def _fake_semantic(monkeypatch, visible, metrics, versions):
    from app.semantic import service, store

    async def list_visible(user, catalog=None):
        return visible

    async def pool():
        return "POOL"

    async def list_metrics(p):
        return metrics

    async def get_version(p, metric_id, name, version):
        return versions.get(name)

    async def for_caller(user):
        return _Access()
    monkeypatch.setattr(catalog_access, "for_caller", for_caller)
    monkeypatch.setattr(service, "list_visible", list_visible)
    monkeypatch.setattr(service, "_pool", pool)
    monkeypatch.setattr(store, "list_metrics", list_metrics)
    monkeypatch.setattr(store, "get_version", get_version)


def _row(name):
    return {"id": f"id-{name}", "name": name, "label": name.upper(), "synonyms": None,
            "current_version": 2}


def test_for_caller_excludes_invisible_and_skips_missing_versions(monkeypatch):
    from app.semantic import context as mc
    _fake_semantic(monkeypatch,
                   visible=[{"name": "revenue"}, {"name": "ghost"}],
                   metrics=[_row("revenue"), _row("secret"), _row("ghost")],
                   versions={"revenue": _Ver(2), "secret": _Ver(2)})   # ghost: no version
    out = asyncio.run(mc.for_caller(ENG, None))
    assert [x["name"] for x in out] == ["revenue"]
    assert out[0]["version"] == 2 and out[0]["synonyms"] == [] and out[0]["dimensions"] == ["channel"]


def test_for_caller_names_the_base_table_fully_qualified(monkeypatch):
    """The prompt's rules require catalog.schema.table; the stored two-part name gets the
    engine catalog of the metric's registry catalog, as this caller resolves it."""
    from app.semantic import context as mc
    _fake_semantic(monkeypatch, visible=[{"name": "revenue"}], metrics=[_row("revenue")],
                   versions={"revenue": _Ver(2)})
    (m,) = asyncio.run(mc.for_caller(ENG, None))
    assert m["base_table"] == "AwsDataCatalog.sales.orders"
    assert "FROM AwsDataCatalog.sales.orders" in metric_lines([m], "x")[0]


def test_for_caller_short_circuits_when_nothing_is_visible(monkeypatch):
    from app.semantic import context as mc, service

    async def no_pool():
        raise AssertionError("pool must not be touched")
    _fake_semantic(monkeypatch, visible=[], metrics=[_row("revenue")], versions={})
    monkeypatch.setattr(service, "_pool", no_pool)
    assert asyncio.run(mc.for_caller(ENG, None)) == []



# Labels from the 2026-10-15 live after-measurement; the questions are its Q1, Q2, Q9-Q11, Q19.
LIVE = [{"name": n, "label": lab, "synonyms": syn, "version": 1, "dimensions": []} for n, lab, syn in [
    ("order_count_en", "order count", []),
    ("order_count", "주문 수", ["주문 건수"]),
    ("revenue", "매출", ["매출액", "총 매출액"]),
    ("customer_count", "고객 수", []),
    ("stock_qty", "재고 수량", ["재고 수량 합계"]),
    ("invoice_amount", "청구서 금액", ["청구서 금액 합계"]),
    ("invoice_count", "청구서 건수", []),
    ("on_hand_qty", "총 재고 수량(on_hand)", ["창고별 재고"]),
]]


@pytest.mark.parametrize("question,name", [
    ("2026년 7월 주문은 총 몇 건인가요?", "order_count"),
    ("2026년 7월 취소된 주문을 제외한 총 매출액은 얼마인가요?", "revenue"),
    ("활성 상품 기준으로 카테고리별 재고 수량 합계를 알려주세요.", "stock_qty"),
    ("2026년 7월에 발행된 청구서의 금액 합계는 얼마인가요?", "invoice_amount"),
    ("창고 코드별 총 재고 수량(on_hand)을 알려주세요.", "on_hand_qty"),
    ("How many 주문 last month?", "order_count"),
    ("국가별 고객 수를 알려주세요.", "customer_count"),
    ("고객수는?", "customer_count"),
])
def test_words_match_across_particles_and_spacing(question, name):
    assert suggest(LIVE, question)["name"] == name


def test_a_tie_between_two_metrics_suggests_neither():
    assert suggest(LIVE, "청구서 상태별 건수와 금액 합계를 보여주세요.") is None


@pytest.mark.parametrize("question", [
    "고객 이탈률",
    "상품 재고",               # "수량" missing: every word of a term must appear
    "몇 건인가요?",            # a count cue alone names no metric
    "주문 금액 평균",          # "주문" alone does not make "주문 수"
    "주문 수량 합계",          # "수" inside "수량" is not a count
    "주문 취소율을 알 수 있나요?",   # "할 수 있다" is not a count
    "고객 이탈률을 볼 수 있을까요?",
    "고객 점수는?",
    "order rate per country",
])
def test_partial_or_cue_only_questions_suggest_nothing(question):
    assert suggest(LIVE, question) is None
