import pytest
from pydantic import ValidationError

from app.chat.actions import ActionKind
from app.chat.analysis import ACTIONS, EXECUTORS
from app.mcp import tools

BY_ID = {a.id: a for a in ACTIONS}


def test_three_read_actions_with_their_permissions():
    assert BY_ID["metric.list"].permission == "catalog:read"
    assert BY_ID["metric.describe"].permission == "catalog:read"
    assert BY_ID["metric.query"].permission == "query:run"
    for i in ("metric.list", "metric.describe", "metric.query"):
        assert BY_ID[i].kind is ActionKind.READ and BY_ID[i].capability == "query"
        assert i in EXECUTORS


def test_mcp_now_exposes_29_read_tools():
    assert sum(1 for a in ACTIONS if a.kind is ActionKind.READ) == 29
    names = {tools.mcp_name(a.id) for a in ACTIONS}
    assert {"metric_list", "metric_describe", "metric_query"} <= names


def test_query_params_reject_unknown_fields():
    with pytest.raises(ValidationError):
        BY_ID["metric.query"].params.model_validate({"metric": "revenue", "sql": "DROP"})


def test_query_executor_passes_everything_through(monkeypatch):
    import asyncio
    from app.chat.analysis import metrics
    seen = {}

    async def fake(user, **kw):
        seen.update(kw)
        return {"ok": True}
    monkeypatch.setattr(metrics.service, "run_metric_query", fake)
    asyncio.run(metrics.query_metric({"metric": "revenue", "by": ["channel"],
                                      "period": "last_month", "grain": None, "where": None},
                                     {"id": "u"}))
    assert seen == {"metric": "revenue", "by": ["channel"], "period": "last_month",
                    "grain": None, "where": []}
