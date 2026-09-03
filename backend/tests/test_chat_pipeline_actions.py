"""Recent runs of one transform pipeline."""
import asyncio

from app.chat.analysis import pipelines as mod


def _run(c):
    return asyncio.run(c)


def test_recent_runs_passes_name_and_limit(monkeypatch):
    seen = {}

    async def _fake(pipeline_name, limit=10):
        seen.update(pipeline_name=pipeline_name, limit=limit)
        return {"runs": []}

    monkeypatch.setattr("app.api.pipelines.get_pipeline_runs", _fake)
    _run(mod.recent_runs({"pipeline": "daily_rollup", "limit": 5}, {"id": "u1"}))
    assert seen == {"pipeline_name": "daily_rollup", "limit": 5}


def test_it_is_a_read_gated_on_the_pipelines_capability():
    action = mod.ACTIONS[0]
    assert action.id == "pipelines.recent_runs"
    assert action.kind.value == "read"
    assert action.capability == "pipelines"
    assert action.permission == "pipeline:write"


def test_only_transforms_among_the_add_ons_has_an_action():
    """Streaming, Notebooks and Experiments deliberately have none — design §4."""
    from app.chat.actions import REGISTRY
    gated = {a.capability for a in REGISTRY.values() if a.capability}
    assert "streaming" not in gated
    assert "notebooks" not in gated
    assert "experiments" not in gated
