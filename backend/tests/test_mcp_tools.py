"""The action registry rendered as MCP tools.

Two properties matter more than the rendering: the name map cannot collide (a new
action must not silently shadow an existing tool), and nothing but a READ action can
reach the list.
"""
import importlib

import pytest
from pydantic import BaseModel

from app.chat.actions import REGISTRY, Action, ActionKind
from app.chat import actions as chat_actions
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
    """`knowledge.search` needs `ai:generate`, not `knowledge:read` — it embeds the
    query (and reranks), the same spend gate REST's `/ai/search` enforces. A
    `knowledge:read`-only key sees collection metadata, never search itself."""
    narrow = {a.id for a in tools.exposed_actions(["ai:generate"], ALL_CAPS)}
    assert "knowledge.search" in narrow
    assert "spend.summarize" not in narrow
    assert narrow < {a.id for a in tools.exposed_actions(ALL_PERMS, ALL_CAPS)}


def test_knowledge_read_alone_does_not_reach_search():
    """The gap `knowledge.search`'s permission fix closed: a `knowledge:read`-only
    key must not see (and, via server.py's authorize(), must not be able to call)
    a tool that spends a model call."""
    narrow = {a.id for a in tools.exposed_actions(["knowledge:read"], ALL_CAPS)}
    assert "knowledge.search" not in narrow
    assert "knowledge.list_collections" in narrow


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


# ── F1: a write action's name must resolve for the "no, that's a write action"
# refusal message, but never through the lookup a dispatcher reaches for by
# reflex. Derived from the registry so a new write action is covered for free. ──

def test_read_action_id_for_refuses_every_non_read_action():
    non_read = [a for a in REGISTRY.values() if a.kind is not ActionKind.READ]
    assert non_read, "expected at least one non-READ action to guard against"
    for action in non_read:
        assert tools.read_action_id_for(tools.mcp_name(action.id)) is None


def test_read_action_id_for_accepts_every_read_action():
    for action in REGISTRY.values():
        if action.kind is ActionKind.READ:
            assert tools.read_action_id_for(tools.mcp_name(action.id)) == action.id


def test_action_id_for_still_resolves_a_write_action_name():
    """action_id_for stays permissive — it resolves a write action's name too,
    because read_action_id_for is built on it. The server does not use that to
    distinguish its refusals: an unknown tool, an unauthorized tool, and a write
    action all answer identically (server.py's `_unknown()`), deliberately, so a
    call cannot be used to enumerate a deployment's components or a caller's own
    missing scopes."""
    write_action = next(a for a in REGISTRY.values() if a.kind is not ActionKind.READ)
    assert tools.action_id_for(tools.mcp_name(write_action.id)) == write_action.id


# ── F2: `name` comes straight off the wire as JSON; a client may legally send a
# list or dict where a tool name is expected. Match resolve()'s isinstance guard. ──

@pytest.mark.parametrize("bad_name", [["x"], {"name": "x"}, 1, None, 3.5])
def test_action_id_for_rejects_non_str(bad_name):
    assert tools.action_id_for(bad_name) is None


@pytest.mark.parametrize("bad_name", [["x"], {"name": "x"}, 1, None, 3.5])
def test_read_action_id_for_rejects_non_str(bad_name):
    assert tools.read_action_id_for(bad_name) is None


# ── F3: ActionKind is a str Enum, so `==` against the bare string "read" would
# also expose an action whose kind was declared as a plain string by mistake.
# `is` is correct today; this pins it so a future `==` edit fails loudly. ──

class _NoParams(BaseModel):
    model_config = {"extra": "forbid"}


def test_a_bare_string_kind_is_not_exposed_even_though_it_equals_read(monkeypatch):
    template = next(iter(REGISTRY.values()))
    fake = Action(id=template.id, label=template.label, description=template.description,
                  pages=template.pages, permission=template.permission,
                  kind="read", params=_NoParams)
    assert fake.kind == ActionKind.READ  # str Enum: equality holds...
    monkeypatch.setattr(tools, "actions_for", lambda *a, **k: [fake])
    assert tools.exposed_actions(ALL_PERMS, ALL_CAPS) == []  # ...but exposure must not


# ── F4: a colliding pair of ids (dots and underscores trading places) would
# make one MCP name silently shadow the other. Structural, not test-dependent:
# it must fail at import, the way app/chat/analysis/__init__.py's duplicate-id
# guard does. ──

def test_a_colliding_pair_of_mcp_names_fails_at_import_not_only_in_a_test():
    fake1 = Action(id="collide.a_b", label="x", description="x", pages=("*",),
                   permission="x:read", kind=ActionKind.READ, params=_NoParams)
    fake2 = Action(id="collide_a.b", label="y", description="y", pages=("*",),
                   permission="x:read", kind=ActionKind.READ, params=_NoParams)
    assert tools.mcp_name(fake1.id) == tools.mcp_name(fake2.id)

    original = dict(chat_actions.REGISTRY)
    chat_actions.REGISTRY[fake1.id] = fake1
    chat_actions.REGISTRY[fake2.id] = fake2
    try:
        with pytest.raises(RuntimeError):
            importlib.reload(tools)
    finally:
        chat_actions.REGISTRY.clear()
        chat_actions.REGISTRY.update(original)
        importlib.reload(tools)


def test_every_exposed_field_is_described():
    """A client's model sees the JSON Schema and nothing else. A field it has to guess
    at is a field it fills in wrong, so an undescribed parameter is an unshipped tool."""
    missing = []
    for action in tools.exposed_actions(ALL_PERMS, ALL_CAPS):
        for field_name, field in action.params.model_fields.items():
            if not (field.description or "").strip():
                missing.append(f"{action.id}.{field_name}")
    assert not missing, "undescribed parameters: " + ", ".join(sorted(missing))
