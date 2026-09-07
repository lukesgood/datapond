"""What the user hears when the turn budget runs out mid-chain.

Found on live, not in review: asked which of seven collections were stale, the
assistant chained list + three diagnoses, streamed "I'll continue checking the
remaining collections:" — and stopped. The budget (`_TURN_STEPS`) expired on a
read, the loop broke, and the preamble the model wrote *before choosing its last
tool* was returned as the turn's answer. Four reads ran; none were summarised.

The fix: when the loop ends while the model was still reading, ask the model once
more with no tools on offer. It cannot chain further — there is nothing to call —
so the boundary should_continue enforces is intact; the turn just ends on an
answer instead of a promise. A parked write keeps its card, and a turn the model
ended itself in prose gains no extra call.
"""
import asyncio

import app.api.chat_routes as chat_routes
from app.api.chat_routes import ChatRequest, chat

USER = {"id": "u-1", "username": "admin", "role": "admin", "auth_method": "password"}

READ_CALL = {"name": "knowledge.list_collections", "input": {}}


class FakeModel:
    """Scripted (prose, tool_call) pairs; records whether each call offered tools."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    async def __call__(self, system, messages, tools):
        self.calls.append({"with_tools": bool(tools), "messages": list(messages)})
        if not self.scripted:
            raise AssertionError("model called more times than the script allows")
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _wire(monkeypatch, model, *, invocation_status="executed"):
    async def fake_propose(action_id, params, **kwargs):
        return {"id": "inv-1", "status": invocation_status,
                "result": {"collections": ["a", "b"]}, "preview": None}

    async def fake_pool():
        return None

    async def fake_conv(pool, user_id, page, conversation_id):
        return "conv-1"

    monkeypatch.setattr(chat_routes, "_ask_model", model)
    monkeypatch.setattr(chat_routes, "propose", fake_propose)
    monkeypatch.setattr(chat_routes, "_get_pool", fake_pool)
    monkeypatch.setattr(chat_routes, "ensure_conversation", fake_conv)
    monkeypatch.setattr(chat_routes, "PostgresInvocationStore", lambda pool: object())
    monkeypatch.setattr(chat_routes, "tool_definitions", lambda *a, **k: [
        {"name": "knowledge.list_collections", "description": "d", "input_schema": {}}])
    monkeypatch.setattr(chat_routes, "_TURN_STEPS", 4)


def test_budget_exhausted_on_reads_ends_with_an_answer_not_a_promise(monkeypatch):
    model = FakeModel(
        [("I'll continue checking the remaining collections:", READ_CALL)] * 4
        + [("Three are stale; two collections remain unchecked.", None)])
    _wire(monkeypatch, model)

    resp = asyncio.run(chat(ChatRequest(message="which collections are stale?"), USER, USER))

    assert resp["reply"] == "Three are stale; two collections remain unchecked."
    assert len(resp["steps"]) == 4
    # The closing call is the one place the model speaks with nothing to call.
    assert len(model.calls) == 5
    assert model.calls[-1]["with_tools"] is False


def test_the_closing_call_carries_the_last_result_and_says_the_turn_is_over(monkeypatch):
    """The final read's result never entered `messages` — the loop broke before the
    append. Without it, the closing answer summarises everything except the last
    thing that ran."""
    model = FakeModel([("checking:", READ_CALL)] * 4 + [("done.", None)])
    _wire(monkeypatch, model)

    asyncio.run(chat(ChatRequest(message="q"), USER, USER))

    closing = model.calls[-1]["messages"]
    assert "Result of knowledge.list_collections" in closing[-1]["content"]
    assert "last tool call" in closing[-1]["content"]


def test_a_turn_the_model_ends_itself_gains_no_extra_call(monkeypatch):
    model = FakeModel([("There are seven collections.", None)])
    _wire(monkeypatch, model)

    resp = asyncio.run(chat(ChatRequest(message="how many collections?"), USER, USER))

    assert resp["reply"] == "There are seven collections."
    assert len(model.calls) == 1


def test_a_parked_write_keeps_its_card_and_gains_no_extra_call(monkeypatch):
    """The loop already stops correctly for a write — a person decides next. The
    closing call must not fire there: the model would speak past its own card."""
    model = FakeModel([("Here is what I propose:",
                        {"name": "knowledge.set_refresh_schedule",
                         "input": {"collection": "c"}})])
    _wire(monkeypatch, model, invocation_status="proposed")

    resp = asyncio.run(chat(ChatRequest(message="refresh c hourly"), USER, USER))

    assert resp["reply"] == "Here is what I propose:"
    assert resp["action"]["needs_approval"] is True
    assert len(model.calls) == 1


def test_a_failed_closing_call_degrades_to_the_preamble_rather_than_crashing(monkeypatch):
    model = FakeModel([("I'll keep checking:", READ_CALL)] * 4
                      + [RuntimeError("gateway down")])
    _wire(monkeypatch, model)

    resp = asyncio.run(chat(ChatRequest(message="q"), USER, USER))

    assert resp["reply"] == "I'll keep checking:"
    assert len(resp["steps"]) == 4


def test_a_read_that_failed_still_gets_a_closing_answer(monkeypatch):
    """A failed read stops the loop at step one (see turn.py). The user should hear
    what was attempted and that it failed — not the preamble to the attempt."""
    model = FakeModel([("Let me look that up:", READ_CALL),
                       ("I could not read the collection list.", None)])
    _wire(monkeypatch, model, invocation_status="failed")

    resp = asyncio.run(chat(ChatRequest(message="q"), USER, USER))

    assert resp["reply"] == "I could not read the collection list."
    assert len(model.calls) == 2
    assert model.calls[-1]["with_tools"] is False
