"""The action registry rendered as MCP tools.

Two properties matter more than the rendering: the name map cannot collide (a new
action must not silently shadow an existing tool), and nothing but a READ action can
reach the list.
"""
from app.chat.actions import REGISTRY, ActionKind
from app.mcp import tools


ALL_CAPS = {a.capability: True for a in REGISTRY.values() if a.capability}
ALL_PERMS = sorted({a.permission for a in REGISTRY.values()})


def test_names_are_the_ids_with_dots_replaced():
    assert tools.mcp_name("knowledge.search") == "knowledge_search"


def test_the_name_map_is_collision_free_and_round_trips():
    seen = {}
    for action in REGISTRY.values():
        name = tools.mcp_name(action.id)
        assert name not in seen, f"{action.id} and {seen.get(name)} both map to {name}"
        seen[name] = action.id
        assert tools.action_id_for(name) == action.id


def test_every_name_is_what_a_client_will_accept():
    """Common clients and gateways validate against ^[a-zA-Z0-9_-]{1,64}$ and reject a
    dotted name at invocation time rather than at registration."""
    import re
    for action in REGISTRY.values():
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tools.mcp_name(action.id)), action.id


def test_an_unknown_name_resolves_to_nothing():
    assert tools.action_id_for("no_such_tool") is None


def test_only_read_actions_are_exposed():
    exposed = tools.exposed_actions(ALL_PERMS, ALL_CAPS)
    assert exposed, "expected some tools"
    assert all(a.kind is ActionKind.READ for a in exposed)
    expected = {a.id for a in REGISTRY.values() if a.kind is ActionKind.READ}
    assert {a.id for a in exposed} == expected


def test_a_narrow_key_sees_a_short_list():
    narrow = {a.id for a in tools.exposed_actions(["knowledge:read"], ALL_CAPS)}
    assert "knowledge.search" in narrow
    assert "spend.summarize" not in narrow
    assert narrow < {a.id for a in tools.exposed_actions(ALL_PERMS, ALL_CAPS)}


def test_a_capability_that_is_off_hides_its_tools_from_everyone():
    assert not [a for a in tools.exposed_actions(ALL_PERMS, {}) if a.capability]


def test_descriptors_carry_name_description_and_schema():
    d = {t["name"]: t for t in tools.descriptors(ALL_PERMS, ALL_CAPS)}
    search = d["knowledge_search"]
    assert search["description"]
    schema = search["inputSchema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "title" not in schema
    assert set(schema["properties"]) == {"collection", "query"}


def test_an_action_with_no_parameters_still_gets_an_object_schema():
    d = {t["name"]: t for t in tools.descriptors(ALL_PERMS, ALL_CAPS)}
    schema = d["storage_overview"]["inputSchema"]
    assert schema["type"] == "object" and schema["properties"] == {}
    assert schema["required"] == []
