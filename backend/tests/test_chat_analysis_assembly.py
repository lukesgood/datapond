"""The registry is assembled from domain modules, and stays whole while it moves.

The move is mechanical, so the test that matters is the one asserting nothing was
dropped on the way: the same ids, each with an executor, each executor with a resolver.
"""
from app.chat import analysis
from app.chat.actions import REGISTRY


def test_every_action_comes_from_a_domain_module():
    assert {a.id for a in analysis.ACTIONS} == set(REGISTRY)


def test_every_action_has_an_executor():
    missing = sorted(set(REGISTRY) - set(analysis.EXECUTORS))
    assert not missing, f"actions with no executor: {missing}"


def test_every_executor_has_a_resolver():
    """RESOLVERS is what test_chat_executor_wiring proves against the real modules —
    an executor with no resolver is one nothing checks the target function of."""
    missing = sorted(set(analysis.EXECUTORS) - set(analysis.RESOLVERS))
    assert not missing, f"executors with no resolver: {missing}"


def test_no_module_declares_an_id_another_module_also_declares():
    ids = [a.id for a in analysis.ACTIONS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate action ids across modules: {dupes}"


def test_every_params_model_forbids_fields_the_model_invented():
    """extra="forbid" everywhere. A field the model made up is a sign it misunderstood,
    and accepting it silently hides that."""
    loose = sorted(a.id for a in analysis.ACTIONS
                   if a.params.model_config.get("extra") != "forbid")
    assert not loose, f"params models accepting extra fields: {loose}"


def test_every_id_is_domain_dot_verb():
    bad = sorted(a.id for a in analysis.ACTIONS
                 if a.id.count(".") != 1 or a.id != a.id.lower())
    assert not bad, f"ids that are not lowercase domain.verb: {bad}"


def test_the_twelve_that_existed_before_are_all_still_here():
    """Named literally. A move that silently drops one would otherwise pass every
    other test in this file."""
    assert {
        "catalog.describe_table", "catalog.find_tables", "catalog.explain_relationships",
        "query.generate_sql", "query.explain_plan", "query.run",
        "dashboard.save",
        "knowledge.search", "knowledge.answer_with_citations",
        "knowledge.create_collection",
        "governance.explain_policy", "spend.summarize",
    } <= set(REGISTRY)
