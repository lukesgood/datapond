"""Knowledge actions: search, cited answers, and creating collections.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
import logging
from typing import Callable, Dict, List, Optional

from pydantic import Field

from app.chat.actions import Action, ActionKind, _Strict
from app.chat.analysis._resolve import _r

logger = logging.getLogger(__name__)


class CollectionCreate(_Strict):
    name: str
    description: Optional[str] = None


class KnowledgeQuery(_Strict):
    # Required, because SearchRequest.collection and RagRequest.collection are. An
    # optional field here would let the model omit what the API demands, and the call
    # would fail after the user had already been told it was happening.
    collection: str
    query: str


async def _existing_collections(user: dict) -> List[str]:
    from app.api.ai_vectors import list_collections
    collections = await list_collections(user=user)
    return [c.get("name") for c in (collections or []) if isinstance(c, dict)]


def build_search_request(params: dict):
    from app.api.ai_vectors import SearchRequest
    return SearchRequest(collection=params["collection"], query=params["query"])


async def search_knowledge(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import search
    return {"matches": await search(build_search_request(params), user=user)}


def build_rag_request(params: dict):
    from app.api.ai_vectors import RagRequest
    # `question`, not `query` — the two request models do not use the same name.
    return RagRequest(collection=params["collection"], question=params["query"])


async def answer_with_citations(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import rag
    return {"answer": await rag(build_rag_request(params), user=user)}


async def preview_create_collection(params: dict, user: dict) -> dict:
    try:
        existing = await _existing_collections(user)
    except Exception as e:
        logger.warning(f"[chat] could not list collections for preview: {e}")
        existing = []
    return {"name": params["name"], "description": params.get("description"),
            "already_exists": params["name"] in existing}


def build_collection_create(params: dict):
    from app.api.ai_vectors import CollectionCreate
    return CollectionCreate(name=params["name"], description=params.get("description"))


async def create_collection(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import create_collection as _create
    created = await _create(build_collection_create(params), user=user)
    return {"name": params["name"], "created": bool(created)}


class CollectionSearch(_Strict):
    q: Optional[str] = None
    limit: int = Field(default=25, ge=1, le=100)


class CollectionRef(_Strict):
    collection: str


async def list_collections_action(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import list_collections
    return {"collections": await list_collections(
        user=user, q=params.get("q"), limit=params["limit"])}


async def collection_composition_action(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import collection_composition
    return {"composition": await collection_composition(
        name=params["collection"], user=user)}


ACTIONS = (
    Action("knowledge.search", "Search knowledge",
           "Retrieve passages from a knowledge collection.",
           ("/knowledge",), "knowledge:read", ActionKind.READ, KnowledgeQuery),
    Action("knowledge.answer_with_citations", "Answer with citations",
           "Answer a question from a collection, with sources.",
           ("/knowledge",), "ai:generate", ActionKind.READ, KnowledgeQuery),
    Action("knowledge.create_collection", "Create collection",
           "Create an empty knowledge collection.",
           ("/knowledge",), "knowledge:write", ActionKind.CREATE, CollectionCreate),
    Action("knowledge.list_collections", "List collections",
           "Knowledge collections this caller can see, with their sizes and freshness.",
           ("*",), "knowledge:read", ActionKind.READ, CollectionSearch),
    Action("knowledge.collection_composition", "Collection composition",
           "What one collection is built from: sources, chunk counts, last refresh.",
           ("*",), "knowledge:read", ActionKind.READ, CollectionRef),
)

EXECUTORS: Dict[str, Callable] = {
    "knowledge.search": search_knowledge,
    "knowledge.answer_with_citations": answer_with_citations,
    "knowledge.create_collection": create_collection,
    "knowledge.list_collections": list_collections_action,
    "knowledge.collection_composition": collection_composition_action,
}

RESOLVERS: Dict[str, Callable] = {
    "knowledge.search": _r("app.api.ai_vectors", "search"),
    "knowledge.answer_with_citations": _r("app.api.ai_vectors", "rag"),
    "knowledge.create_collection": _r("app.api.ai_vectors", "create_collection"),
    "knowledge.list_collections": _r("app.api.ai_vectors", "list_collections"),
    "knowledge.collection_composition": _r("app.api.ai_vectors", "collection_composition"),
}

PREVIEWERS: Dict[str, Callable] = {
    "knowledge.create_collection": preview_create_collection,
}
