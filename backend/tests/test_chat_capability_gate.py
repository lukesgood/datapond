"""The third gate: an action for a component this deployment does not run.

Permission answers "may this person", capability answers "does this deployment have
it". Before this, `actions_for` asked only the first, so a Portable Core install with
no query engine still offered the model catalog.describe_table — which it proposed,
and which then failed at the route. The model cannot explain that, and the user reads
it as the assistant being broken.
"""
import pytest

from app.chat.actions import (REGISTRY, Action, ActionKind, actions_for,
                              tool_definitions)
from app.chat import gate
from app.chat.gate import ActionRefused


ALL = {a.permission for a in REGISTRY.values()}


def test_an_action_whose_capability_is_off_is_not_offered():
    off = {"catalog": False, "query": False}
    ids = {a.id for a in actions_for(ALL, "*", off)}
    assert "catalog.describe_table" not in ids
    assert "query.run" not in ids
    # Core actions carry no capability and are unaffected.
    assert "knowledge.search" in ids


def test_an_action_whose_capability_is_on_is_offered():
    ids = {a.id for a in actions_for(ALL, "*", {"catalog": True, "query": True})}
    assert "catalog.describe_table" in ids
    assert "query.run" in ids


def test_no_capability_map_drops_every_capability_bound_action():
    """Fail-closed. A caller that could not determine capabilities loses the gated
    actions rather than gaining them."""
    ids = {a.id for a in actions_for(ALL, "*", None)}
    assert not [i for i in ids if REGISTRY[i].capability]
    assert "knowledge.search" in ids


@pytest.mark.parametrize("value", [False, None, "true", 1, {}])
def test_only_an_exact_true_counts(value):
    ids = {a.id for a in actions_for(ALL, "*", {"catalog": value})}
    assert "catalog.describe_table" not in ids


def test_tool_definitions_hides_them_from_the_model():
    names = {t["name"] for t in tool_definitions(ALL, "*", {"catalog": False})}
    assert "catalog.describe_table" not in names


@pytest.mark.asyncio
async def test_execution_refuses_a_forged_id_for_a_disabled_capability(monkeypatch):
    """The second gate. Not seeing an action is UX; being refused is the control."""
    monkeypatch.setattr(gate, "capability_on", lambda key: False)

    class _Store:
        async def record_audit(self, *a, **k):
            return None

    user = {"id": "u1", "permissions": sorted(ALL)}
    with pytest.raises(ActionRefused):
        await gate._authorize(REGISTRY["catalog.describe_table"], user, "*",
                              _Store(), stage="propose")


def test_every_capability_named_in_the_registry_exists():
    """A capability name that does not exist fails closed, which means a typo hides an
    action forever and nothing ever says so. This is the only thing that would."""
    from app.capabilities import compute_capabilities
    known = set(compute_capabilities({}))
    unknown = sorted({a.capability for a in REGISTRY.values()
                      if a.capability and a.capability not in known})
    assert not unknown, f"capabilities not in compute_capabilities(): {unknown}"


def test_every_permission_named_in_the_registry_exists():
    from app.permissions import ALL_PERMISSIONS
    unknown = sorted({a.permission for a in REGISTRY.values()
                      if a.permission not in ALL_PERMISSIONS})
    assert not unknown, f"permissions not in ALL_PERMISSIONS: {unknown}"
