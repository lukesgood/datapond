"""What collections exist, and what one of them is made of."""
import asyncio

from app.chat.analysis import knowledge as mod


def _run(c):
    return asyncio.run(c)


def test_list_collections_passes_the_caller_and_bounds_the_page(monkeypatch):
    """Collections are access-filtered by caller. Passing the Depends default instead
    of the user would filter by nothing."""
    seen = {}

    async def _fake(user=None, q=None, limit=None, offset=None):
        seen.update(user=user, q=q, limit=limit)
        return {"collections": []}

    monkeypatch.setattr("app.api.ai_vectors.list_collections", _fake)
    user = {"id": "u1"}
    _run(mod.list_collections_action({"q": "handbook", "limit": 25}, user))
    assert seen == {"user": user, "q": "handbook", "limit": 25}


def test_composition_passes_name_and_user(monkeypatch):
    seen = {}

    async def _fake(name, user=None):
        seen.update(name=name, user=user)
        return {"sources": []}

    monkeypatch.setattr("app.api.ai_vectors.collection_composition", _fake)
    user = {"id": "u1"}
    _run(mod.collection_composition_action({"collection": "handbook"}, user))
    assert seen == {"name": "handbook", "user": user}


def test_both_are_reads_on_knowledge_read():
    for action_id in ("knowledge.list_collections", "knowledge.collection_composition"):
        action = next(a for a in mod.ACTIONS if a.id == action_id)
        assert action.kind.value == "read"
        assert action.permission == "knowledge:read"
        assert action.capability is None
