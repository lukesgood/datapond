"""The action registry bounds what an assistant can ever propose.

The model does not compose requests. It picks an id from this registry and supplies
parameters that are validated before anything else happens. Everything here is
testable without a model, which is the point: the gate is the part that must be right.
"""
import pytest

from app.chat.actions import (
    ActionKind,
    InvalidParams,
    UnknownAction,
    actions_for,
    resolve,
    tool_definitions,
    validate_params,
)


# ── resolution ────────────────────────────────────────────────────────────────

def test_a_known_action_resolves():
    action = resolve("catalog.describe_table")
    assert action.id == "catalog.describe_table"
    assert action.kind is ActionKind.READ


@pytest.mark.parametrize("bogus", [
    "catalog.drop_everything",
    "",
    None,
    "../../etc/passwd",
    "catalog.describe_table; DROP TABLE users",
])
def test_a_fabricated_action_id_is_refused(bogus):
    with pytest.raises(UnknownAction):
        resolve(bogus)


def test_every_registered_action_declares_a_real_permission():
    from app.permissions import ALL_PERMISSIONS
    for action in actions_for(ALL_PERMISSIONS, page="*"):
        assert action.permission in ALL_PERMISSIONS, action.id


def test_every_destructive_action_declares_the_target_field_the_gate_needs():
    """v1 excluded deletion because the destructive gate did not exist yet — it does
    now (app/chat/gate.py), and app/chat/analysis/governance.py registers the first
    two destructive actions. The gate reads `target_field` off the Action to find
    what the user must have named and must type back to confirm; a destructive
    action with none would silently skip that check rather than fail loudly, so this
    is the one property that must hold for every one of them, present and future."""
    from app.permissions import ALL_PERMISSIONS
    for action in actions_for(ALL_PERMISSIONS, page="*"):
        if action.kind is ActionKind.DESTRUCTIVE:
            assert action.target_field, action.id


# ── parameter validation ──────────────────────────────────────────────────────

def test_valid_parameters_pass_and_come_back_normalised():
    action = resolve("catalog.describe_table")
    assert validate_params(action, {"namespace": "sales", "table": "orders"}) == {
        "namespace": "sales", "table": "orders"}


def test_missing_required_parameters_are_refused():
    action = resolve("catalog.describe_table")
    with pytest.raises(InvalidParams) as ei:
        validate_params(action, {"namespace": "sales"})
    assert "table" in str(ei.value)
    with pytest.raises(InvalidParams) as ei:
        validate_params(action, {"table": "orders"})
    assert "namespace" in str(ei.value)


def test_unexpected_parameters_are_refused_rather_than_ignored():
    """Silently dropping a field the model invented hides that it misunderstood."""
    action = resolve("catalog.describe_table")
    with pytest.raises(InvalidParams):
        validate_params(action, {"namespace": "sales", "table": "orders", "force": True})


def test_wrong_types_are_refused():
    action = resolve("catalog.describe_table")
    with pytest.raises(InvalidParams):
        validate_params(action, {"namespace": ["sales"], "table": "orders"})


def test_non_object_parameters_are_refused():
    action = resolve("catalog.describe_table")
    for junk in ("a string", 42, None, ["a", "list"]):
        with pytest.raises(InvalidParams):
            validate_params(action, junk)


# ── the first gate: a model never learns about actions the caller cannot use ──

CAPS = {"catalog": True, "query": True, "dashboards": True}


def test_actions_are_filtered_by_permission():
    ids = {a.id for a in actions_for({"catalog:read"}, page="*", capabilities=CAPS)}
    assert "catalog.describe_table" in ids
    assert "knowledge.create_collection" not in ids
    assert "dashboard.save" not in ids


def test_a_permissionless_caller_gets_nothing():
    assert actions_for(set(), page="*") == []


def test_actions_are_filtered_by_page():
    from app.permissions import ALL_PERMISSIONS
    on_query = {a.id for a in actions_for(ALL_PERMISSIONS, page="/query", capabilities=CAPS)}
    assert "query.run" in on_query
    assert "governance.explain_policy" not in on_query


def test_global_actions_appear_on_every_page():
    from app.permissions import ALL_PERMISSIONS
    for page in ("/query", "/knowledge", "/governance"):
        assert "catalog.find_tables" in {a.id for a in actions_for(ALL_PERMISSIONS, page, CAPS)}


def test_the_wildcard_page_lists_everything_permitted():
    from app.permissions import ALL_PERMISSIONS
    everything = {a.id for a in actions_for(ALL_PERMISSIONS, page="*", capabilities=CAPS)}
    assert {"query.run", "governance.explain_policy", "knowledge.search"} <= everything


# ── what the model is handed ──────────────────────────────────────────────────

def test_tool_definitions_describe_only_permitted_actions():
    tools = tool_definitions({"catalog:read"}, page="*", capabilities=CAPS)
    names = {t["name"] for t in tools}
    assert names and names <= {"catalog.describe_table", "catalog.find_tables",
                               "catalog.explain_relationships"}


def test_a_tool_definition_carries_a_usable_schema():
    tool = next(t for t in tool_definitions({"catalog:read"}, page="*", capabilities=CAPS)
                if t["name"] == "catalog.describe_table")
    schema = tool["input_schema"]
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"namespace", "table"}
    assert schema.get("additionalProperties") is False


def test_tool_definitions_never_leak_server_internals():
    """The model gets a name, a description, and a schema — not callables or routes."""
    from app.permissions import ALL_PERMISSIONS
    for tool in tool_definitions(ALL_PERMISSIONS, page="*"):
        assert set(tool) == {"name", "description", "input_schema"}


def test_running_a_query_requires_approval():
    """A product decision, pinned so it cannot be reverted by a one-word edit.

    Analytics runs a query on one click, and this adds a step. Kept because the two
    are not the same act: there the person wrote the statement, here they did not.
    Athena bills by bytes scanned, and this product's own plan review exists because a
    generated query can read the wrong table — asked for a table that did not exist,
    the model substituted a real one and validation passed.
    """
    action = resolve("query.run")
    assert action.kind is not ActionKind.READ, (
        "query.run must not execute without approval")
    assert action.kind is ActionKind.CREATE


def test_generating_sql_does_not_require_approval():
    """The counterpart: writing a statement changes nothing and costs no scan."""
    assert resolve("query.generate_sql").kind is ActionKind.READ
    assert resolve("query.explain_plan").kind is ActionKind.READ
