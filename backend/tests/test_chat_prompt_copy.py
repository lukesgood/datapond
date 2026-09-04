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


def test_the_prompt_names_what_it_can_now_change():
    """Task 11: the assistant can change configuration now — schedules, membership,
    connector settings, policies, model configuration, roles. Say so."""
    prompt = _system_prompt("/knowledge", {}).lower()
    for phrase in ("schedule", "collection member", "sync mode", "row-filter",
                   "masking", "model", "role"):
        assert phrase in prompt, f"prompt no longer mentions {phrase}"


def test_the_approval_only_actions_the_prompt_promises_are_not_destructive():
    """The prompt says a refresh schedule, collection membership, a connector
    schedule, a sync mode change, and creating a row-filter or masking policy need
    only the person's approval — not a typed target. Paired against the registry:
    each of these stays MUTATE. If one of them were ever promoted to DESTRUCTIVE, the
    prompt would be understating what the gate actually demands, which is the same
    drift this file exists to catch."""
    from app.chat.actions import REGISTRY, ActionKind
    approval_only_ids = ("knowledge.set_refresh_schedule", "knowledge.add_member",
                        "knowledge.remove_member", "connectors.set_schedule",
                        "connectors.set_sync_mode", "governance.create_rls_policy",
                        "governance.create_masking_policy")
    for action_id in approval_only_ids:
        action = REGISTRY[action_id]  # KeyError, not .get() — a removed action must fail loudly
        assert action.kind is ActionKind.MUTATE, action.id


def test_the_prompt_names_the_create_actions_too():
    """Fix round 1, finding 1: governance.create_rls_policy and
    governance.create_masking_policy are registered MUTATE actions, but an earlier
    pass of this copy named the corresponding deletes and never said the assistant
    can create a policy in the first place. A person who does not know the assistant
    can create a policy will not ask it to — resolving the copy against only the
    DESTRUCTIVE actions let the creates fall out of view, which is exactly the
    failure this file exists to catch."""
    prompt = _system_prompt("/knowledge", {}).lower()
    assert "create a row-filter or column-masking policy" in prompt


def test_the_typed_target_actions_the_prompt_promises_are_exactly_the_destructive_ones():
    """'the last four asking them to type the target's name' — deleting a row-filter
    policy, deleting a masking policy, changing model configuration, granting a role.
    Checked both ways: nothing DESTRUCTIVE is missing from the prompt's promise, and
    nothing the prompt promises is missing from what is actually DESTRUCTIVE."""
    from app.chat.actions import REGISTRY, ActionKind
    destructive_ids = {a.id for a in REGISTRY.values() if a.kind is ActionKind.DESTRUCTIVE}
    assert destructive_ids == {
        "governance.delete_rls_policy", "governance.delete_masking_policy",
        "settings.set_model_config", "users.grant_role",
    }


def test_every_refusal_the_prompt_makes_is_guarded_unconditionally():
    """Fix round 1, finding 2. The prompt makes four flat refusals: it never writes a
    credential, never deletes an account, never runs a sync, never deletes a
    collection or a dashboard.

    The `"delete" in action.id` branch in test_the_registry_agrees_with_that_claim
    only forces DESTRUCTIVE + target_field — it does not forbid the action from
    existing. A future `users.delete_user`, correctly marked DESTRUCTIVE with a
    target_field, would pass every assertion in this file while making the "cannot
    delete an account" claim false, and a green suite would read as coverage it does
    not provide. Each refusal here is guarded unconditionally instead: by an exact id
    (sync, where the registry already has a concrete name to check), or by permission
    shape (account/collection/dashboard deletion, where 'delete' appearing under a
    permission that should never carry it is the thing to catch, not any one guessed
    id), or by a set-emptiness check that holds regardless of which actions exist at
    all (credentials)."""
    from app.chat.actions import REGISTRY
    from app.chat.analysis.settings import ALLOWED_KEYS
    from app.api.system_settings import SENSITIVE_KEYS

    # Credentials: true independent of the registry's contents — settings.py could
    # gain ten new actions built on ALLOWED_KEYS and this would still hold, because
    # it is a fact about what ALLOWED_KEYS *is*, not about which action reads it.
    assert not (ALLOWED_KEYS & set(SENSITIVE_KEYS))

    for action in REGISTRY.values():
        # Sync: the registry already has one concrete name a sync action would use.
        assert action.id != "connectors.sync", action.id
        # Account deletion: user:manage is the permission that reaches accounts and
        # roles at all; nothing under it may be delete-shaped, not just the one id
        # this repo happens to have avoided so far.
        if action.permission == "user:manage":
            assert "delete" not in action.id, action.id
        # Collection deletion: same shape, under the permission that reaches
        # collections.
        if action.permission == "knowledge:write":
            assert "delete" not in action.id, action.id
        # Dashboard deletion: same shape, under the permission that reaches
        # dashboards.
        if action.permission == "dashboard:write":
            assert "delete" not in action.id, action.id


def test_the_prompt_does_not_promise_disabling_a_refresh_schedule():
    """schedule_ingest (app/api/ai_vectors.py) always sets refresh_enabled = true —
    there is no off-path, so the assistant must not claim it can stop a schedule, only
    set or change it. RefreshScheduleParams backs the same claim: nothing in its shape
    could mean 'off'."""
    from app.chat.analysis.knowledge import RefreshScheduleParams
    assert "enabled" not in RefreshScheduleParams.model_fields

    prompt = _system_prompt("/knowledge", {}).lower()
    assert "never turn its schedule off" in prompt
    assert "turn a schedule off" not in prompt
    assert "turn schedules on" not in prompt
    assert "on or off" not in prompt
