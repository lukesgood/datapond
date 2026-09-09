"""The authorization decision the assistant panel and the MCP server share.

Both surfaces must answer 'may this caller run this action' identically — that is the
whole reason the decision was extracted from the gate. The parity test below is what
keeps them from drifting: it asserts `authorize` agrees with `actions_for`, which is
the filter the tool list is built from, for every action against several permission
sets. A tool a caller can see but not call, or the reverse, fails here.
"""
import pytest

from app.chat import authz
from app.chat.actions import REGISTRY, actions_for


ALL_PERMISSIONS = sorted({a.permission for a in REGISTRY.values()})
ALL_CAPABILITIES = {a.capability: True for a in REGISTRY.values() if a.capability}


@pytest.fixture
def caps_on(monkeypatch):
    """capability_on reads the environment; actions_for takes a map. Pin both to the
    same answer so the parity test measures the permission rule, not the environment."""
    monkeypatch.setattr(authz, "capability_on", lambda key: ALL_CAPABILITIES.get(key) is True)
    return ALL_CAPABILITIES


@pytest.mark.parametrize("permissions", [
    set(),
    {"knowledge:read"},
    {"knowledge:read", "ai:generate"},
    set(ALL_PERMISSIONS),
])
def test_authorize_agrees_with_actions_for(permissions, caps_on):
    allowed = {a.id for a in actions_for(permissions, "*", caps_on)}
    user = {"permissions": sorted(permissions)}
    for action in REGISTRY.values():
        try:
            authz.authorize(action, user)
            permitted = True
        except (authz.NotPermitted, authz.CapabilityOff):
            permitted = False
        assert permitted is (action.id in allowed), action.id


def test_capability_off_is_refused_even_with_the_permission(monkeypatch):
    monkeypatch.setattr(authz, "capability_on", lambda key: False)
    gated = next(a for a in REGISTRY.values() if a.capability)
    with pytest.raises(authz.CapabilityOff) as exc:
        authz.authorize(gated, {"permissions": [gated.permission]})
    assert exc.value.required == gated.capability


def test_held_permissions_prefers_the_key_over_the_role():
    """A service-account key carries its own narrowed set; a person is judged by role."""
    assert authz.held_permissions({"permissions": ["knowledge:read"], "role": "admin"}) \
        == {"knowledge:read"}
    assert "knowledge:read" in authz.held_permissions({"role": "admin"})


def test_an_empty_scope_list_is_not_the_same_as_no_scopes():
    """`permissions: []` is a key that was granted nothing — not a fall-back to role."""
    assert authz.held_permissions({"permissions": [], "role": "admin"}) == set()
