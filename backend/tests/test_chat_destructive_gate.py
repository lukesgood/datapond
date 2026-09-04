"""The gate a destructive action passes through, tested without one existing.

A destructive proposal is refused before a card is ever rendered when the user did
not name the target. That is the order that matters: the model must not be able to
put a confirmation dialog in front of someone for a target they never mentioned,
because a dialog is an invitation to click.
"""
import asyncio

import pytest

from app.chat import gate
from app.chat import actions as chat_actions
from app.chat.actions import Action, ActionKind, _Strict
from app.chat.gate import ActionRefused


def _run(c):
    return asyncio.run(c)


class _Target(_Strict):
    name: str


DROP = Action("test.drop_thing", "Drop thing", "Drops a thing.", ("*",),
              "governance:write", ActionKind.DESTRUCTIVE, _Target,
              target_field="name")


class _Store:
    def __init__(self):
        self.audits = []
        self.created = None

    async def record_audit(self, event, user_id, user_email, details):
        self.audits.append((event, details))

    async def create(self, **fields):
        self.created = fields
        return {"id": "inv-1", **fields}


USER = {"id": "u1", "permissions": ["governance:write"]}


def _propose(store, turns, **kw):
    return _run(gate.propose(
        DROP.id, {"name": "crm.customers"}, user=USER, page="*", store=store,
        turns=turns, **kw))


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    # gate.py does not import REGISTRY itself — resolve() reads it from the actions
    # module's own namespace, so that is the correct patch target.
    monkeypatch.setitem(chat_actions.REGISTRY, DROP.id, DROP)
    monkeypatch.setattr(gate, "capability_on", lambda key: True)


def test_a_target_the_user_named_reaches_the_card():
    store = _Store()
    inv = _propose(store, [{"role": "user", "content": "drop crm.customers"}])
    assert inv["status"] == "proposed"
    assert inv["preview"]["target"] == "crm.customers"
    assert inv["preview"]["named_by_user"]["turn_index"] == 0


def test_a_target_only_the_assistant_named_is_refused_before_any_card():
    store = _Store()
    with pytest.raises(ActionRefused):
        _propose(store, [
            {"role": "user", "content": "clean up anything unused"},
            {"role": "assistant", "content": "crm.customers looks unused"},
        ])
    assert store.created is None, "no invocation may be recorded for a refused proposal"


def test_the_refusal_is_audited_with_its_reason():
    store = _Store()
    with pytest.raises(ActionRefused):
        _propose(store, [{"role": "user", "content": "tidy up"}])
    events = [d for e, d in store.audits if e == "chat_action_refused"]
    assert events and events[-1]["reason"] == "target_not_named"


def test_no_turns_at_all_refuses_rather_than_waves_through():
    """Fail closed: a caller that sent no history has proved nothing."""
    store = _Store()
    with pytest.raises(ActionRefused):
        _propose(store, [])


def test_dependents_are_computed_server_side_and_stored():
    store = _Store()

    def _deps(params, user):
        from app.chat.dependents import Dependents
        return Dependents(params["name"]).item("table", params["name"], "unfiltered").done()

    inv = _propose(store, [{"role": "user", "content": "drop crm.customers"}],
                   dependents=_deps)
    assert inv["preview"]["dependents"]["items"][0]["name"] == "crm.customers"


def test_a_destructive_action_never_executes_at_propose_time():
    """READ executes immediately; everything else waits. A destructive one waits
    hardest."""
    store = _Store()
    ran = []
    inv = _propose(store, [{"role": "user", "content": "drop crm.customers"}],
                   executor=lambda p, u: ran.append(p))
    assert ran == []
    assert inv["status"] == "proposed"
