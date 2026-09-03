"""Dashboard actions: save a statement and its chart as a dashboard.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
from typing import Callable, Dict

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class DashboardSave(_Strict):
    name: str
    sql: str
    chart_type: str = "table"


async def preview_dashboard_save(params: dict, user: dict) -> dict:
    return {"name": params["name"], "chart_type": params.get("chart_type", "table"),
            "sql": params["sql"]}


def build_dashboard_create(params: dict):
    """The schema is `query_text` and a ChartConfig object, not `query` and a string."""
    from app.schemas.dashboard import ChartConfig, DashboardCreate
    return DashboardCreate(
        name=params["name"],
        query_text=params["sql"],
        chart_config=ChartConfig(chartType=params.get("chart_type") or "table"),
    )


async def save_dashboard(params: dict, user: dict) -> dict:
    from app.api.dashboards import create_dashboard
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        created = await create_dashboard(build_dashboard_create(params), db=db, user=user)
    finally:
        db.close()
    return {"id": str(getattr(created, "id", "")), "name": params["name"]}


ACTIONS = (
    Action("dashboard.save", "Save dashboard",
           "Save a statement and its chart as a dashboard.",
           ("/query",), "dashboard:write", ActionKind.CREATE, DashboardSave,
           capability="dashboards"),
)

EXECUTORS: Dict[str, Callable] = {
    "dashboard.save": save_dashboard,
}

RESOLVERS: Dict[str, Callable] = {
    "dashboard.save": _r("app.api.dashboards", "create_dashboard"),
}

PREVIEWERS: Dict[str, Callable] = {
    "dashboard.save": preview_dashboard_save,
}
