"""Reads over Transforms. The only add-on with an assistant action — design §4."""
from typing import Callable, Dict

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r


class PipelineRuns(_Strict):
    pipeline: str
    limit: int = Field(default=10, ge=1, le=50)


async def recent_runs(params: dict, user: dict) -> dict:
    from app.api.pipelines import get_pipeline_runs
    return {"runs": await get_pipeline_runs(
        pipeline_name=params["pipeline"], limit=params["limit"])}


ACTIONS = (
    Action("pipelines.recent_runs", "Recent pipeline runs",
           "Execution history for one transform pipeline: when it ran and how it ended.",
           ("*",), "pipeline:write", ActionKind.READ, PipelineRuns,
           capability="pipelines"),
)

EXECUTORS: Dict[str, Callable] = {"pipelines.recent_runs": recent_runs}
RESOLVERS: Dict[str, Callable] = {
    "pipelines.recent_runs": _r("app.api.pipelines", "get_pipeline_runs"),
}
PREVIEWERS: Dict[str, Callable] = {}
