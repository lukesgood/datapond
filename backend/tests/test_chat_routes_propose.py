"""`/chat/actions/propose` — the panel's "run the thing I just chose" route — must
never be able to raise a destructive card. It exists for parameters the MODEL
produced (see its docstring in app/api/chat_routes.py): a person picking one from a
list does not mean the person named the target in their own words, so this route
passes no `turns` into `gate.propose`. Without `turns`, `named_by_user` can never
find evidence and any destructive action reached this way is refused before an
invocation even exists.

That is deliberate today and untested, so a later change that threads history
through (to make some other feature work) could silently remove the protection.
This pins it.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import chat_routes

USER = {"id": "u1", "permissions": ["governance:write"]}


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


def test_a_destructive_action_proposed_through_the_panel_route_is_always_refused():
    request = chat_routes.ProposeRequest(
        action_id="governance.delete_rls_policy",
        params={"policy_id": "rls-1"}, page="*")

    with pytest.raises(HTTPException) as exc:
        _run(chat_routes.propose_action(request, user=USER, _human=USER))

    assert exc.value.status_code == 403
    assert "not mentioned" in exc.value.detail
