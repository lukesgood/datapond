"""`/chat/actions/propose` — the panel's "run the thing I just chose" route — must
never be able to raise a destructive card. It exists for parameters the MODEL
produced (see its docstring in app/api/chat_routes.py): a person picking one from a
list does not mean the person named the target in their own words, so this route
passes no `turns` into `gate.propose`. Without `turns`, `named_by_user` can never
find evidence and any destructive action reached this way is refused before an
invocation even exists.

That is deliberate today and untested, so a later change that threads history
through (to make some other feature work) could silently remove the protection.
This pins it two ways: the end-to-end refusal, and the actual call made to
`gate.propose` — checking only the former would stay green if a future change
added a `history` field to `ProposeRequest` and wired `turns=request.history`
through, since nothing in this file's own request would populate it either. Capturing
the kwargs pins the mechanism itself, not just today's incidental outcome.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import chat_routes

USER = {"id": "u1", "permissions": ["governance:write"]}

# Captured before any monkeypatch touches `chat_routes.propose` — the real
# `gate.propose`, so the wrapper below can still exercise the actual refusal logic
# while also recording what it was called with.
_REAL_PROPOSE = chat_routes.propose


def _run(c):
    return asyncio.run(c)


class _NoopStore:
    """A store that never touches Postgres — the refusal happens before any
    invocation is created, so nothing here needs to actually work."""

    async def record_audit(self, *a, **kw):
        return None


@pytest.fixture(autouse=True)
def _no_real_infra(monkeypatch):
    async def _fake_get_pool():
        return object()

    async def _fake_ensure_conversation(pool, user_id, page, conversation_id):
        return "conv-1"

    monkeypatch.setattr(chat_routes, "_get_pool", _fake_get_pool)
    monkeypatch.setattr(chat_routes, "ensure_conversation", _fake_ensure_conversation)
    monkeypatch.setattr(chat_routes, "PostgresInvocationStore",
                        lambda pool: _NoopStore())

    captured.clear()

    async def _capturing_propose(*args, **kwargs):
        captured.append(kwargs)
        return await _REAL_PROPOSE(*args, **kwargs)

    monkeypatch.setattr(chat_routes, "propose", _capturing_propose)


captured: list = []


def test_propose_action_passes_no_naming_evidence_so_destructive_actions_stay_refused():
    """This route exists for parameters the MODEL produced and a person merely
    chose to run — a click here is not proof the person named the target in their
    own words, so `propose_action` must never pass `turns` into `gate.propose` at
    all. Checking that the call carries no `turns` kwarg is the assertion that
    actually pins this: `assert not turns` would still pass if a future change
    added a `history` field to `ProposeRequest` and wired `turns=request.history`
    through, because this test's own request sets no history either and an empty
    list is just as falsy as an absent key — the exact loophole this test exists to
    close. Asserting the key itself is absent fails the moment that wiring exists,
    regardless of what any particular request happens to carry.
    """
    request = chat_routes.ProposeRequest(
        action_id="governance.delete_rls_policy",
        params={"policy_id": "rls-1"}, page="*")

    with pytest.raises(HTTPException) as exc:
        _run(chat_routes.propose_action(request, user=USER, _human=USER))

    assert exc.value.status_code == 403
    assert "not mentioned" in exc.value.detail

    assert len(captured) == 1
    assert "turns" not in captured[0], (
        "app.api.chat_routes.propose_action must never pass a `turns` kwarg into "
        "gate.propose at all — not even an empty one — because this route's "
        "parameters can be model-authored even though a person clicked")
