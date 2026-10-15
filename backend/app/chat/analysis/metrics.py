"""Metric actions: governed metric definitions, queried deterministically.

`metric.query` is READ, unlike `query.run` (CREATE, approval card). query.run runs a
statement nobody approved against a table the model chose; a metric runs an
admin-approved expression over an admin-approved table, its period is mandatory and
capped (max_period_days), and the per-key rate limit applies. Residual risk — an
unpartitioned table scanned in full within the period — is shown to the admin who
approves the definition. See the semantic-layer spec §3.
"""
from typing import Any, Callable, Dict, List, Optional

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class _LazyService:
    """`app.semantic.service` resolved on first use. Importing it at module load closes a
    cycle: service -> tool_call_log -> app.chat.actions (REGISTRY) -> this module."""

    def __getattr__(self, name: str):
        import importlib
        return getattr(importlib.import_module("app.semantic.service"), name)


service = _LazyService()


class MetricList(_Strict):
    catalog: Optional[str] = Field(
        default=None, description="Only metrics over this data catalog. Omit for all you may use.")


class MetricName(_Strict):
    metric: str = Field(description="The metric's name, as metric_list returns it (e.g. revenue).")


class MetricQuery(_Strict):
    metric: str = Field(description="The metric's name, as metric_list returns it (e.g. revenue).")
    by: List[str] = Field(
        default_factory=list,
        description="Dimension names to group by, from metric_describe. Not column names.")
    period: Optional[str] = Field(
        default=None,
        description="Required when the metric has a time column. One of this_month, last_month, "
                    "this_quarter, last_quarter, this_year, last_year, last_n_days:N, or "
                    "YYYY-MM-DD..YYYY-MM-DD (inclusive).")
    grain: Optional[str] = Field(
        default=None, description="Group by time: one of the metric's grains (day, week, month, "
                                  "quarter, year).")
    where: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description='Filters as [{"dimension": "...", "op": "=|!=|in|>|<|between", "value": ...}]. '
                    "in takes a list; between takes [low, high].")


async def list_metrics(params: dict, user: dict) -> dict:
    return {"metrics": await service.list_visible(user, params.get("catalog"))}


async def describe_metric(params: dict, user: dict) -> dict:
    return await service.describe_visible(user, params["metric"])


async def query_metric(params: dict, user: dict) -> dict:
    return await service.run_metric_query(
        user, metric=params["metric"], by=params.get("by") or [],
        period=params.get("period"), grain=params.get("grain"),
        where=params.get("where") or [])


ACTIONS = (
    Action("metric.list", "List metrics",
           "Approved business metrics you may query, with their names and synonyms. Use before "
           "writing SQL for a KPI: a metric gives a cited, reproducible number.",
           ("*",), "catalog:read", ActionKind.READ, MetricList, capability="query"),
    Action("metric.describe", "Describe metric",
           "One metric's definition: expression, filters, dimensions, grains, period cap, "
           "version and approver.",
           ("*",), "catalog:read", ActionKind.READ, MetricName, capability="query"),
    Action("metric.query", "Query metric",
           "Compute an approved metric by dimensions over a period. Deterministic SQL from the "
           "approved definition; the result carries a citation (metric, version, approver, SQL).",
           ("*",), "query:run", ActionKind.READ, MetricQuery, capability="query"),
)

EXECUTORS: Dict[str, Callable] = {
    "metric.list": list_metrics,
    "metric.describe": describe_metric,
    "metric.query": query_metric,
}

RESOLVERS: Dict[str, Callable] = {
    "metric.list": _r("app.semantic.service", "list_visible"),
    "metric.describe": _r("app.semantic.service", "describe_visible"),
    "metric.query": _r("app.semantic.service", "run_metric_query"),
}

PREVIEWERS: Dict[str, Callable] = {}
