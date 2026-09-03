"""Executors must actually be able to call what they claim to call.

`test_every_registered_action_has_an_executor` only proved a callable existed. Four of
the twelve were wired to functions and request models that do not have the shape they
assumed — a wrong field name, a wrong function name — and each would have failed the
first time a user asked for it, in production, through the assistant.

These tests construct the real request models and resolve the real functions. No
database, no cluster: a field name is wrong or it is not.
"""
import inspect

import pytest

from app.chat import executors
from app.chat.actions import REGISTRY, ActionKind
from app.chat.analysis import dashboards, knowledge


def _params_for(action_id: str) -> dict:
    """A minimal valid parameter set for each action, from its own schema."""
    return {
        "catalog.describe_table": {"namespace": "sales", "table": "orders"},
        "catalog.find_tables": {"query": "orders"},
        "catalog.explain_relationships": {"table": None, "days": 30},
        "query.generate_sql": {"question": "totals by region"},
        "query.explain_plan": {"sql": "SELECT 1"},
        "query.run": {"sql": "SELECT 1"},
        "dashboard.save": {"name": "d", "sql": "SELECT 1", "chart_type": "bar"},
        "knowledge.search": {"query": "q", "collection": "c"},
        "knowledge.answer_with_citations": {"query": "q", "collection": "c"},
        "knowledge.create_collection": {"name": "c", "description": None},
        "knowledge.list_collections": {"q": None, "limit": 25},
        "knowledge.collection_composition": {"collection": "c"},
        "governance.explain_policy": {"table": None},
        "governance.policy_coverage": {},
        "governance.summary_stats": {},
        "spend.summarize": {"days": 30},
        "connectors.list_sources": {},
        "connectors.sync_history": {"connection_id": "c1", "limit": 5},
        "connectors.quality_checks": {"connection_id": "c1", "limit": 5},
        "platform.service_health": {"service": "backend"},
        "platform.service_metrics": {"service": "backend"},
        "platform.recent_events": {"hours": 24, "limit": 50, "severity": None},
        "storage.overview": {},
        "pipelines.recent_runs": {"pipeline": "daily_rollup", "limit": 5},
    }[action_id]


def test_the_sample_parameters_cover_every_action():
    """If an action is added, this file must be updated — that is the point."""
    for action_id, action in REGISTRY.items():
        params = _params_for(action_id)
        action.params.model_validate(params)  # raises if the sample is wrong


# ── the request models each executor builds ───────────────────────────────────

def test_dashboard_save_builds_the_real_request_model():
    from app.schemas.dashboard import ChartConfig, DashboardCreate
    params = _params_for("dashboard.save")
    body = dashboards.build_dashboard_create(params)
    assert isinstance(body, DashboardCreate)
    assert body.query_text == params["sql"], "the field is query_text, not query"
    assert isinstance(body.chart_config, ChartConfig)
    assert body.chart_config.chartType == "bar"


def test_knowledge_search_builds_the_real_request_model():
    from app.api.ai_vectors import SearchRequest
    body = knowledge.build_search_request(_params_for("knowledge.search"))
    assert isinstance(body, SearchRequest)
    assert body.collection == "c" and body.query == "q"


def test_rag_builds_the_real_request_model():
    from app.api.ai_vectors import RagRequest
    body = knowledge.build_rag_request(_params_for("knowledge.answer_with_citations"))
    assert isinstance(body, RagRequest)
    assert body.question == "q", "the field is question, not query"
    assert body.collection == "c"


def test_collection_create_builds_the_real_request_model():
    from app.api.ai_vectors import CollectionCreate
    body = knowledge.build_collection_create(_params_for("knowledge.create_collection"))
    assert isinstance(body, CollectionCreate)
    assert body.name == "c"


# ── the functions each executor resolves ──────────────────────────────────────

@pytest.mark.parametrize("action_id", sorted(REGISTRY))
def test_every_executor_resolves_its_target_function(action_id):
    """Import-time resolution of everything an executor reaches for. A renamed
    function — `rag_answer` for `rag`, `get_spend` for `spend_summary` — fails here
    rather than in front of a user."""
    resolver = executors.RESOLVERS.get(action_id)
    if resolver is None:
        pytest.skip(f"{action_id} calls nothing importable")
    target = resolver()
    assert callable(target), f"{action_id} resolved to something not callable"


def test_a_collection_is_required_where_the_api_requires_one():
    """SearchRequest.collection and RagRequest.collection are not optional, so the
    action schema must not let the model omit them."""
    for action_id in ("knowledge.search", "knowledge.answer_with_citations"):
        fields = REGISTRY[action_id].params.model_fields
        assert fields["collection"].is_required(), action_id


def test_every_non_read_action_still_has_a_previewer():
    missing = [a for a, action in REGISTRY.items()
               if action.kind is not ActionKind.READ and a not in executors.PREVIEWERS]
    assert not missing, missing
