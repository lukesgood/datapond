"""The second line: the person types the name of the thing they are changing.

The first line is Task 3 — the model cannot raise a dialog for an unnamed target.
This one is against the person clicking through a dialog they did raise.
"""
import asyncio

import pytest

from app.chat import actions, gate
from app.chat.actions import Action, ActionKind, _Strict
from app.chat.gate import ActionRefused


def _run(c):
    return asyncio.run(c)


class _Target(_Strict):
    name: str


DROP = Action("test.drop_thing", "Drop thing", "Drops a thing.", ("*",),
              "governance:write", ActionKind.DESTRUCTIVE, _Target,
              target_field="name")

INVOCATION = {
    "id": "inv-1", "action_id": DROP.id, "user_id": "u1", "status": "proposed",
    "params": {"name": "crm.customers"},
    "preview": {"target": "crm.customers", "named_by_user": {"turn_index": 0}},
}


class _Store:
    """Carries only the methods `approve()` actually calls: `claim_for_approval`,
    `get`, `update`, and `record_audit` — there is no `set_status`."""

    def __init__(self):
        self.audits = []
        self.status = "proposed"

    async def record_audit(self, event, user_id, user_email, details):
        self.audits.append((event, details))

    async def get(self, invocation_id):
        return {**INVOCATION, "status": self.status}

    async def claim_for_approval(self, invocation_id, approved_by):
        if self.status != "proposed":
            return None
        self.status = "approved"
        return {**INVOCATION, "status": self.status}

    async def update(self, invocation_id, **fields):
        if "status" in fields:
            self.status = fields["status"]
        return {**INVOCATION, "status": self.status, **fields}


USER = {"id": "u1", "permissions": ["governance:write"]}


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    monkeypatch.setitem(actions.REGISTRY, DROP.id, DROP)
    monkeypatch.setattr(gate, "capability_on", lambda key: True)


def test_the_exact_name_executes():
    store, ran = _Store(), []
    _run(gate.approve("inv-1", user=USER, store=store,
                      executor=lambda p, u: ran.append(p) or {"ok": True},
                      typed_target="crm.customers"))
    assert ran == [{"name": "crm.customers"}]


def test_a_different_name_does_not_execute():
    store, ran = _Store(), []
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store,
                          executor=lambda p, u: ran.append(p),
                          typed_target="crm.orders"))
    assert ran == []


def test_no_typed_name_at_all_does_not_execute():
    """Omitting the field is not the same as matching it."""
    store, ran = _Store(), []
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store,
                          executor=lambda p, u: ran.append(p)))
    assert ran == []


def test_case_and_surrounding_quotes_are_forgiven():
    """The point is intent, not transcription. Copying the name out of the card and
    picking up a backtick must not be a failure."""
    store, ran = _Store(), []
    _run(gate.approve("inv-1", user=USER, store=store,
                      executor=lambda p, u: ran.append(p) or {"ok": True},
                      typed_target=' "CRM.Customers" '))
    assert ran


def test_the_mismatch_is_audited():
    store = _Store()
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store, typed_target="wrong"))
    assert any(d.get("reason") == "typed_target_mismatch"
               for e, d in store.audits if e == "chat_action_refused")


def test_a_mistyped_name_can_be_retried():
    """A refusal on a bad guess must not consume the invocation: the person gets
    another try, and typing it right the second time still executes."""
    store, ran = _Store(), []
    with pytest.raises(ActionRefused):
        _run(gate.approve("inv-1", user=USER, store=store,
                          executor=lambda p, u: ran.append(p),
                          typed_target="wrong"))
    assert store.status == "proposed"
    _run(gate.approve("inv-1", user=USER, store=store,
                      executor=lambda p, u: ran.append(p) or {"ok": True},
                      typed_target="crm.customers"))
    assert ran == [{"name": "crm.customers"}]
