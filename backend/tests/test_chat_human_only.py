"""The assistant panel is a human surface.

A service account holding `ai:generate` could drive /api/chat and then approve its own
proposal — it is the owner of that invocation, so the ownership check passes. That is
exactly what design §5.4 forbids: the assistant approving its own action, with the
confirmation gate reduced to a formality.

There is also nothing to gain. An agent already calls the typed endpoints directly;
routing it through a model to pick an action adds nondeterminism and a second round of
token spend, and leaves the audit trail unable to say who approved.

Blocked in two independent places: the routes, because that is where the answer should
be quick, and the gate, because that is where the guarantee has to hold even if a
future endpoint forgets the dependency.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api.auth import require_human

SERVICE = {"id": "svc-1", "username": "svc-bot", "role": "ai_engineer",
           "auth_method": "service", "api_key_id": "k1",
           "permissions": ["ai:generate", "query:run", "catalog:read"]}
PERSON = {"id": "u-1", "username": "ada", "role": "ai_engineer"}


def _run(c):
    return asyncio.run(c)


# ── the route gate ────────────────────────────────────────────────────────────

def test_a_person_passes():
    assert _run(require_human(user=PERSON))["id"] == "u-1"


def test_a_person_with_a_stated_auth_method_still_passes():
    assert _run(require_human(user={**PERSON, "auth_method": "local"}))["id"] == "u-1"
    assert _run(require_human(user={**PERSON, "auth_method": "oidc"}))["id"] == "u-1"


def test_a_service_account_is_refused():
    with pytest.raises(HTTPException) as ei:
        _run(require_human(user=SERVICE))
    assert ei.value.status_code == 403


def test_the_refusal_says_what_to_use_instead():
    """A 403 that does not say where to go sends someone to read source."""
    with pytest.raises(HTTPException) as ei:
        _run(require_human(user=SERVICE))
    assert "API" in ei.value.detail


# ── the gate guarantee ────────────────────────────────────────────────────────

class _Store:
    def __init__(self, row):
        self.rows = {row["id"]: row}
        self.audit = []

    async def create(self, **f):
        return {"id": "x", **f}

    async def get(self, invocation_id):
        return self.rows.get(invocation_id)

    async def update(self, invocation_id, **f):
        self.rows[invocation_id].update(f)
        return self.rows[invocation_id]

    async def record_audit(self, event, user_id, user_email, details):
        self.audit.append(event)


def _proposed(owner):
    return {"id": "inv-1", "action_id": "query.run", "params": {"sql": "SELECT 1"},
            "status": "proposed", "user_id": owner["id"], "page": "/query"}


def test_a_service_account_cannot_approve_even_its_own_proposal():
    from app.chat.gate import ActionRefused, approve
    store = _Store(_proposed(SERVICE))
    executed = []
    with pytest.raises(ActionRefused):
        _run(approve("inv-1", user=SERVICE, store=store,
                     executor=lambda p, u: executed.append(p)))
    assert executed == [], "the whole point: no human, no execution"


def test_the_refusal_to_self_approve_is_audited():
    from app.chat.gate import ActionRefused, approve
    store = _Store(_proposed(SERVICE))
    with pytest.raises(ActionRefused):
        _run(approve("inv-1", user=SERVICE, store=store, executor=lambda p, u: {}))
    assert "chat_action_refused" in store.audit


def test_a_person_approving_their_own_proposal_still_works():
    from app.chat.gate import approve
    store = _Store(_proposed(PERSON))
    ran = []
    result = _run(approve("inv-1", user=PERSON, store=store,
                          executor=lambda p, u: ran.append(p) or {"rows": 1}))
    assert result["status"] == "executed"
    assert ran == [{"sql": "SELECT 1"}]
