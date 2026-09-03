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


# Stale once it is this many times past its own refresh interval. Two, not one: a tick
# that lands a minute late is not a fault, and a signal that fires on every healthy
# collection is a signal people learn to ignore.
_STALE_INTERVALS = 2


async def diagnose_collection(params: dict, user: dict) -> dict:
    """Is this collection still worth querying?

    Access is gated through `_collection_id`, the same read-access check every route
    in app/api/ai_vectors.py runs before it touches an existing collection by name. A
    caller who may not read the collection gets that function's 404/403 propagated —
    diagnosis never runs for a collection this caller can't see, and never confirms a
    name exists to a caller who can't.
    """
    from datetime import datetime, timezone

    from app.api.ai_vectors import _collection_id, _embed_model
    from app.api.auth import _get_pool
    from app.chat.diagnosis import Diagnosis

    name = params["collection"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        coll_id = await _collection_id(conn, name, user)
        row = await conn.fetchrow(
            """SELECT id, embed_model, refresh_enabled, refresh_interval_minutes,
                      last_refreshed_at, last_refresh_status, owner_id
               FROM ai_collections WHERE id = $1""", coll_id)
        if row is None:
            raise ValueError(f"No collection named {name!r}.")
        chunks = await conn.fetchval(
            "SELECT count(*) FROM ai_chunks WHERE collection_id = $1", row["id"])

    d = Diagnosis(f"collection {name!r}")
    d.fact("chunks", chunks)
    d.fact("embed_model", row["embed_model"])
    d.fact("refresh_enabled", bool(row["refresh_enabled"]))
    d.fact("last_refreshed_at", str(row["last_refreshed_at"] or ""))
    d.fact("last_refresh_status", row["last_refresh_status"] or "")

    configured = _embed_model()
    if row["embed_model"] != configured:
        d.signal("bad",
                 "Embedded with a different model than the one queries use now — "
                 "retrieval degrades silently, with nothing logged.",
                 collection_model=row["embed_model"], configured_model=configured)
    else:
        d.signal("ok", "Embedding model matches the configured one.",
                 model=configured)

    if chunks == 0:
        d.signal("bad", "The collection is empty — nothing to retrieve.")

    if not row["refresh_enabled"] or not row["refresh_interval_minutes"]:
        d.skipped("Freshness not checked: the collection is not scheduled to refresh.")
    elif row["last_refreshed_at"] is None:
        d.signal("warn", "Scheduled to refresh but has never refreshed.")
    else:
        age_min = (datetime.now(timezone.utc)
                   - row["last_refreshed_at"]).total_seconds() / 60
        overdue = age_min > row["refresh_interval_minutes"] * _STALE_INTERVALS
        d.signal("warn" if overdue else "ok",
                 "Stale against its own schedule." if overdue
                 else "Refreshed within its schedule.",
                 minutes_since_refresh=int(age_min),
                 interval_minutes=row["refresh_interval_minutes"])

    if row["last_refresh_status"] and row["last_refresh_status"] != "ok":
        d.signal("bad", "The last refresh did not succeed.",
                 status=row["last_refresh_status"])

    return d.done()


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
    Action("knowledge.diagnose_collection", "Diagnose collection",
           "Whether one collection is still worth querying: size, freshness against "
           "its own schedule, last refresh outcome, and whether it was embedded with "
           "the model queries use now.",
           ("*",), "knowledge:read", ActionKind.READ, CollectionRef),
)

EXECUTORS: Dict[str, Callable] = {
    "knowledge.search": search_knowledge,
    "knowledge.answer_with_citations": answer_with_citations,
    "knowledge.create_collection": create_collection,
    "knowledge.list_collections": list_collections_action,
    "knowledge.collection_composition": collection_composition_action,
    "knowledge.diagnose_collection": diagnose_collection,
}

RESOLVERS: Dict[str, Callable] = {
    "knowledge.search": _r("app.api.ai_vectors", "search"),
    "knowledge.answer_with_citations": _r("app.api.ai_vectors", "rag"),
    "knowledge.create_collection": _r("app.api.ai_vectors", "create_collection"),
    "knowledge.list_collections": _r("app.api.ai_vectors", "list_collections"),
    "knowledge.collection_composition": _r("app.api.ai_vectors", "collection_composition"),
    # The access gate the fix for Critical 1 routes through, not _embed_model: this
    # is the call whose signature matters if diagnose_collection's access check is
    # ever weakened by a refactor elsewhere in ai_vectors.py.
    "knowledge.diagnose_collection": _r("app.api.ai_vectors", "_collection_id"),
}

PREVIEWERS: Dict[str, Callable] = {
    "knowledge.create_collection": preview_create_collection,
}
