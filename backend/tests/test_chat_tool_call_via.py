"""The chat gate's executor call runs under via('chat') so any tool_call_log row a
chat-triggered executor writes is attributable to chat rather than the generic 'api'
default. See app/tool_call_log.py for via()/current_via()."""
import asyncio

from app import tool_call_log
from app.chat import gate


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_execute_runs_the_action_under_via_chat(monkeypatch):
    seen = {}

    async def _exec(params, user):
        seen["via"] = tool_call_log.current_via()
        return {"ok": True}

    class _Action:
        id = "knowledge.search"
        label = "Knowledge search"

    class _Store:
        async def update(self, *a, **kw):
            return {"status": "executed"}

    async def _audit(*a, **kw):
        return None

    monkeypatch.setattr(gate, "_audit", _audit)

    invocation = {"id": "inv-1", "params": {}}
    user = {"id": "u", "username": "u", "role": "ai_engineer"}
    _run(gate._execute(invocation, _Action(), user, _Store(), _exec))
    assert seen["via"] == "chat"


def test_execute_leaves_via_at_default_outside_chat():
    # Sanity check on the default from app/tool_call_log.py, so the assertion above
    # is meaningful: absent an active via() context, current_via() is 'api'.
    assert tool_call_log.current_via() == "api"
