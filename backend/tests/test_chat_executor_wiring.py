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
        "knowledge.diagnose_collection": {"collection": "c"},
        "knowledge.set_refresh_schedule": {"collection": "c", "interval_minutes": 60,
                                            "schedule": None},
        "knowledge.add_member": {"collection": "c", "email": "a@b.c", "role": "reader"},
        "knowledge.remove_member": {"collection": "c", "email": "a@b.c"},
        "governance.explain_policy": {"table": None},
        "governance.policy_coverage": {},
        "governance.summary_stats": {},
        "governance.pii_summary": {},
        "audit.activity_summary": {"days": 7},
        "spend.summarize": {"days": 30},
        "spend.diagnose_change": {"days": 7},
        "connectors.list_sources": {},
        "connectors.sync_history": {"connection_id": "c1", "limit": 5},
        "connectors.quality_checks": {"connection_id": "c1", "limit": 5},
        "connectors.diagnose_sync": {"connection_id": "c1"},
        "connectors.set_schedule": {"connection_id": "c1", "cron": "0 2 * * *"},
        "connectors.set_sync_mode": {"connection_id": "c1", "sync_mode": "incremental",
                                      "table_name": None},
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


# ── every parameter an executor leaves unbound must have a plain default ──────
#
# `platform.recent_events` called `list_system_events(severity=..., hours=...,
# limit=...)` and left `kind`/`source` unbound. Their real defaults are
# `Query(None)` objects, not `None` — a fastapi.params.Query instance is truthy, so
# both got bound as query arguments and the call failed on every real invocation.
# `test_every_executor_resolves_its_target_function` above only proves the resolved
# target is *callable*; it never inspects what the target's own parameters default
# to, so it could not have caught this.
#
# This does not statically read what each executor's call site actually passes —
# that would need parsing the executor's source. Instead it is a fixture, hand-built
# by reading every executor in app/chat/analysis/*.py: for each action with a
# resolver, the set of parameter names that executor's call binds explicitly (by
# keyword, or positionally — a positional argument's name still comes from
# `inspect.signature`). Anything on the resolved target NOT in this set is a
# parameter the executor is relying on the function's own default for, and that
# default must not be a `fastapi.params.Depends` or `fastapi.params.Query`
# sentinel — those are only meaningful when FastAPI itself resolves them from a
# request, and calling the function directly (as every executor does, per the
# global "executors call service functions directly" rule) leaves them as the raw
# sentinel object instead.
#
# What this catches: exactly the Critical-2 shape — an executor omitting a
# parameter whose real default is a Depends/Query sentinel, for every action listed
# below. What it does NOT catch: a fixture entry that is wrong (this test is only
# as honest as the hand-maintained set below — a stale entry after a genuine
# executor-side change fails silently), a resolver that does not point at the
# function the executor actually calls (RESOLVERS carries one function per action;
# some executors call more than one), or any hazard in a parameter the executor
# *does* pass, or in a value the executor passes to a bound parameter (e.g. passing
# a Depends object through by accident). Nor does it catch a default that is some
# other kind of unsafe sentinel outside these two FastAPI classes.
_EXPLICITLY_BOUND_PARAMS = {
    "catalog.describe_table": set(),          # get_catalog_reader() — no params
    "catalog.find_tables": set(),              # get_catalog_reader() — no params
    "catalog.explain_relationships": {"statements", "schema"},   # dialect omitted, plain default
    "query.generate_sql": {"req", "user"},
    "query.explain_plan": {"io_text", "dist_text"},
    "query.run": {"request", "db", "user"},
    "dashboard.save": {"dashboard", "db", "user"},
    "knowledge.search": {"req", "user"},
    "knowledge.answer_with_citations": {"req", "user"},
    "knowledge.create_collection": {"body", "user"},
    "knowledge.list_collections": {"user", "q", "limit"},        # offset omitted, plain default
    "knowledge.collection_composition": {"name", "user"},
    "knowledge.diagnose_collection": {"c", "name", "user"},      # write/destroy omitted, plain default
    "knowledge.set_refresh_schedule": {"name", "body", "user"},
    "knowledge.add_member": {"name", "body", "user"},
    "knowledge.remove_member": {"name", "username", "user"},
    "governance.explain_policy": set(),        # load_policies() — no params
    "governance.policy_coverage": {"user"},
    "governance.summary_stats": set(),         # _scan_pii_tables() — no params
    "governance.pii_summary": set(),           # _scan_pii_tables() — no params
    "audit.activity_summary": set(),           # _get_pool() — no params
    "spend.summarize": set(),                  # spend_summary() — no params
    "spend.diagnose_change": {"start_date", "end_date"},
    "connectors.list_sources": {"user"},
    "connectors.sync_history": {"connection_id", "limit", "user"},
    "connectors.quality_checks": {"connection_id", "limit", "user"},
    "connectors.diagnose_sync": {"connection_id", "limit", "user"},
    "connectors.set_schedule": {"connection_id", "request", "user"},
    "connectors.set_sync_mode": {"connection_id", "body", "user"},
    "platform.service_health": {"service"},
    "platform.service_metrics": {"service"},
    "platform.recent_events": {"severity", "kind", "source", "hours", "limit"},
    "storage.overview": set(),                 # get_storage_overview() — no params
    "pipelines.recent_runs": {"pipeline_name", "limit"},
}


def test_the_bound_params_fixture_covers_every_resolvable_action():
    """If an action gains a resolver, this file's fixture must be updated too — that
    is the point, same as test_the_sample_parameters_cover_every_action above."""
    resolvable = {a for a in REGISTRY if executors.RESOLVERS.get(a) is not None}
    assert resolvable == set(_EXPLICITLY_BOUND_PARAMS), (
        resolvable.symmetric_difference(_EXPLICITLY_BOUND_PARAMS))


@pytest.mark.parametrize("action_id", sorted(_EXPLICITLY_BOUND_PARAMS))
def test_unbound_params_have_plain_defaults_not_fastapi_sentinels(action_id):
    """Every parameter the executor does NOT bind must default to something other
    than a `Depends(...)`/`Query(...)` sentinel — see the module comment above."""
    import fastapi.params

    resolver = executors.RESOLVERS[action_id]
    target = resolver()
    bound = _EXPLICITLY_BOUND_PARAMS[action_id]
    sig = inspect.signature(target)
    for name, param in sig.parameters.items():
        if name in bound or param.default is inspect.Parameter.empty:
            continue
        assert not isinstance(param.default, (fastapi.params.Depends, fastapi.params.Query)), (
            f"{action_id}: {target.__module__}.{target.__qualname__}'s {name!r} "
            f"defaults to {param.default!r}, which the executor leaves unbound — "
            f"calling it directly (not through FastAPI) will pass that sentinel "
            f"through as the argument value.")
