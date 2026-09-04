"""What the assistant says it can do has to match what the registry lets it do."""
from app.api.chat_routes import _system_prompt


def test_the_prompt_still_refuses_writes_it_cannot_do():
    """The registry has no action that runs a sync, and no action ever writes or
    reads back a credential. If that ever stops being true, this sentence has to
    change with it — and the second assertion below is what forces the pairing.
    Deletion and settings changes are no longer an outright refusal: destructive
    actions exist now (governance.delete_rls_policy, governance.delete_masking_policy,
    settings.set_model_config), so the prompt says what those actually take — a
    target the person already named, and their typed confirmation — instead of
    claiming they cannot happen at all."""
    prompt = _system_prompt("/knowledge", {})
    assert "typed confirmation" in prompt
    assert "cannot run a sync" in prompt
    assert "never read or write a credential" in prompt


def test_the_registry_agrees_with_that_claim():
    from app.chat.actions import REGISTRY, ActionKind
    for action in REGISTRY.values():
        if action.permission == "user:manage":
            # users.grant_role exists, but only behind the destructive gate — a
            # named target (the person, via target_field) and a typed confirmation.
            # An action that can reshape who can do what must never reach a caller
            # through the weaker, undo-able MUTATE gate.
            assert action.kind is ActionKind.DESTRUCTIVE, action.id
            assert action.target_field, action.id
        assert action.id != "connectors.sync", action.id
        if action.permission == "settings:write":
            # settings.set_model_config exists, but only behind the destructive
            # gate, and only for the non-credential keys — see
            # app/chat/analysis/settings.py's ALLOWED_KEYS.
            assert action.kind is ActionKind.DESTRUCTIVE, action.id
        if "delete" in action.id:
            # Allowed to exist, but only behind the destructive gate — a named
            # target and a typed confirmation — never as an ordinary write. See the
            # prompt copy above, which is what promises this to the model.
            assert action.kind is ActionKind.DESTRUCTIVE, action.id
    # Fix round 1, finding 5: the two assertions on user:manage above are inside an
    # `if` guarded on an action that carries "user:manage" existing at all — remove
    # that action and both go vacuous. This keeps the invariant from silently
    # stopping meaning anything if users.grant_role is ever removed.
    assert any(a.permission == "user:manage" for a in REGISTRY.values())


def test_the_prompt_mentions_the_reach_it_now_has():
    prompt = _system_prompt("/knowledge", {})
    for word in ("sources", "services", "storage", "collections"):
        assert word in prompt.lower(), f"prompt no longer mentions {word}"
