"""Pointing agents at approved metrics. Measured 2026-10-16 on live: with a SQL tool
available an agent never called metric_list (0/20); with MCP only it found metrics
after four other tools, and gave up on 4/20 without looking. These hints sit on the
tools agents do call."""
import asyncio
from datetime import date

import pytest

from app.chat.analysis import catalog as cat
from app.chat.analysis import query as qmod
from app.mcp import protocol
from app.semantic.compile import compile_metric
from app.semantic.context import suggest
from app.semantic.model import MetricInputError, MetricVersion

M = [{"name": "order_count", "label": "주문 수", "synonyms": [], "version": 1,
      "dimensions": ["channel"], "time_column": "ordered_at"},
     {"name": "customer_count", "label": "고객 수", "synonyms": [], "version": 1,
      "dimensions": ["country"], "time_column": None}]


def test_suggestion_says_whether_a_period_is_required():
    assert suggest(M, "6월 채널별 주문 수")["period_required"] is True
    assert suggest(M, "국가별 고객 수")["period_required"] is False


def test_generate_sql_over_mcp_points_at_the_suggested_metric(monkeypatch):
    from app.api import ai_sql
    from app.api.ai_sql import AskResponse

    async def fake(req, user=None):
        return AskResponse(sql="SELECT 1", explanation="", has_ai=True,
                           metrics_provided=["order_count@v1"],
                           suggested_metric={"name": "order_count", "dimensions": ["channel"],
                                             "period_required": True})
    monkeypatch.setattr(ai_sql, "generate_sql", fake)
    out = asyncio.run(qmod.generate_sql({"question": "6월 채널별 주문 수"}, {"id": "u"}))
    assert out["suggested_metric"]["name"] == "order_count"
    assert "metric_query" in out["next"] and '"metric": "order_count"' in out["next"]
    assert "period" in out["next"]


def test_generate_sql_without_a_suggestion_still_mentions_metrics_when_some_were_given(monkeypatch):
    from app.api import ai_sql
    from app.api.ai_sql import AskResponse

    async def fake(req, user=None):
        return AskResponse(sql="SELECT 1", explanation="", has_ai=True,
                           metrics_provided=["order_count@v1"], suggested_metric=None)
    monkeypatch.setattr(ai_sql, "generate_sql", fake)
    out = asyncio.run(qmod.generate_sql({"question": "x"}, {"id": "u"}))
    assert "suggested_metric" not in out and "metric_list" in out["next"]


def test_generate_sql_with_no_metrics_adds_nothing(monkeypatch):
    from app.api import ai_sql
    from app.api.ai_sql import AskResponse

    async def fake(req, user=None):
        return AskResponse(sql="SELECT 1", explanation="", has_ai=True)
    monkeypatch.setattr(ai_sql, "generate_sql", fake)
    out = asyncio.run(qmod.generate_sql({"question": "x"}, {"id": "u"}))
    assert "next" not in out and "suggested_metric" not in out


def test_describe_table_lists_metrics_defined_on_it(monkeypatch):
    class Reader:
        def get_columns(self, ns, t):
            return [{"name": "id", "type": "bigint"}]

    class Entry:
        name, engine_catalog, is_default = "AwsDataCatalog", "AwsDataCatalog", True

    class Access:
        def resolve(self, c):
            return Entry()

    async def access(user):
        return Access()

    async def metrics_on(user, entry, ns, table):
        return [{"name": "order_count", "label": "주문 수"}]
    monkeypatch.setattr(cat, "_access", access)
    monkeypatch.setattr(cat, "get_catalog_reader", lambda name: Reader())
    monkeypatch.setattr(cat, "_metrics_on", metrics_on)
    out = asyncio.run(cat.describe_table({"namespace": "default", "table": "orders"}, {"id": "u"}))
    assert out["metrics"] == [{"name": "order_count", "label": "주문 수"}]
    assert "metric_query" in out["metrics_note"]


def test_metrics_on_matches_the_qualified_table_and_never_raises(monkeypatch):
    from app.semantic import context

    async def for_caller(user, catalog=None):
        return [{"name": "order_count", "label": "주문 수",
                 "base_table": "AwsDataCatalog.default.orders"},
                {"name": "x", "label": "X", "base_table": "AwsDataCatalog.default.items"}]
    monkeypatch.setattr(context, "for_caller", for_caller)
    monkeypatch.setattr(cat, "_metrics_enabled", lambda: True)

    class Entry:
        name, engine_catalog = "AwsDataCatalog", "AwsDataCatalog"
    got = asyncio.run(cat._metrics_on({"id": "u"}, Entry(), "default", "orders"))
    assert got == [{"name": "order_count", "label": "주문 수"}]

    async def boom(user, catalog=None):
        raise RuntimeError("no semantic tables")
    monkeypatch.setattr(context, "for_caller", boom)
    assert asyncio.run(cat._metrics_on({"id": "u"}, Entry(), "default", "orders")) == []
    monkeypatch.setattr(context, "for_caller", for_caller)
    monkeypatch.setattr(cat, "_metrics_enabled", lambda: False)
    assert asyncio.run(cat._metrics_on({"id": "u"}, Entry(), "default", "orders")) == []


def test_initialize_carries_instructions_that_name_the_metric_tools():
    r = protocol.initialize_result("datapond", "1")
    assert "metric_list" in r["instructions"] and "metric_query" in r["instructions"]


def test_missing_period_error_gives_a_usable_example():
    v = MetricVersion(metric="m", version=1, catalog="c", base_table="s.t", measure="COUNT(*)",
                      time_column="d", grains=("month",))
    with pytest.raises(MetricInputError) as e:
        compile_metric(v, engine_catalog="C", dialect="athena", today=date(2026, 10, 16))
    assert "2026-01-01..2026-10-16" in str(e.value) and "last_month" in str(e.value)
