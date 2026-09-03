"""What the assistant says it can do has to match what the registry lets it do."""
from app.api.chat_routes import _system_prompt


def test_the_prompt_still_refuses_writes_it_cannot_do():
    """The registry has no action that changes settings, runs a sync or deletes
    anything. If that ever stops being true, this sentence has to change with it —
    and the second assertion below is what forces the pairing."""
    prompt = _system_prompt("/knowledge", {})
    assert "cannot delete" in prompt
    assert "change settings" in prompt


def test_the_registry_agrees_with_that_claim():
    from app.chat.actions import REGISTRY
    for action in REGISTRY.values():
        assert action.permission not in ("settings:write", "user:manage"), action.id
        assert "delete" not in action.id, action.id
        assert action.id != "connectors.sync", action.id


def test_the_prompt_mentions_the_reach_it_now_has():
    prompt = _system_prompt("/knowledge", {})
    for word in ("sources", "services", "storage", "collections"):
        assert word in prompt.lower(), f"prompt no longer mentions {word}"
