"""Knowledge actions: search, cited answers, and creating collections.

Declaration and implementation live together. `actions.py` owns the vocabulary — the
Action type, resolution, validation, the gate — and assembles what these modules
declare.
"""
import logging
from typing import Callable, Dict, List, Literal, Optional

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


# ── The three reversible changes ──────────────────────────────────────────────
# Undoable from what is on screen — set the number back, flip the switch back,
# re-add the member — so they use the ordinary preview → approve card (MUTATE),
# not the destructive gate. See docs/superpowers/plans/... for the grading rule.

class RefreshScheduleParams(_Strict):
    collection: str
    # Neither given means "leave the interval as it is" only in the sense that
    # schedule_ingest's own default (daily) applies — see the previewer, which
    # reports the collection's *current* interval alongside these.
    interval_minutes: Optional[int] = None
    schedule: Optional[str] = None   # legacy Airflow preset (@hourly/@daily/@weekly)


class MemberGrantParams(_Strict):
    collection: str
    username: str = Field(
        description="The person's login username, not their email address — "
                    "collection membership resolves strictly on username.")
    role: Literal["reader", "editor"]


class MemberRemoveParams(_Strict):
    collection: str
    username: str = Field(
        description="The person's login username, not their email address — "
                    "collection membership resolves strictly on username.")


def build_schedule_request(params: dict, source):
    from app.api.ai_vectors import ScheduleRequest
    return ScheduleRequest(interval_minutes=params.get("interval_minutes"),
                            schedule=params.get("schedule"), source=source)


async def preview_set_refresh_schedule(params: dict, user: dict) -> dict:
    """The interval, and that this always turns refresh on — schedule_ingest has no
    "leave it off" mode; that is delete_schedule, a different route this action does
    not call."""
    from app.api.ai_vectors import get_schedule
    name = params["collection"]
    try:
        current = await get_schedule(name, user=user)
    except Exception as e:
        # Important 5: a swallowed exception must not surface as current_schedule:
        # null — that is indistinguishable from a successful lookup that found no
        # schedule. The error goes in `summary`, the same shape governance.py,
        # users.py and settings.py already use for a failed preview read.
        return {"collection": name,
                "new_interval_minutes": params.get("interval_minutes"),
                "schedule_preset": params.get("schedule"),
                "summary": f"Set the refresh schedule for {name!r} — its current "
                          f"schedule could not be read to confirm this: {e}"}
    return {
        "collection": name,
        "currently_enabled": bool(current.get("enabled")),
        "current_interval_minutes": current.get("interval_minutes"),
        "new_interval_minutes": params.get("interval_minutes"),
        "schedule_preset": params.get("schedule"),
        "will_be_enabled": True,
    }


async def set_refresh_schedule_action(params: dict, user: dict) -> dict:
    """Reschedules the source already configured for this collection — it does not
    let the model invent a new one. `schedule_ingest` requires a `source`
    (`ScheduleRequest.source` is not optional), so the one already on file, from
    `get_schedule`, is what gets resubmitted with the new interval."""
    from app.api.ai_vectors import SourceIngest, get_schedule, schedule_ingest
    name = params["collection"]
    current = await get_schedule(name, user=user)
    source = current.get("source")
    if not source:
        raise ValueError(
            f"Collection {name!r} has no source configured yet — nothing to "
            f"reschedule. Ingest a source first.")
    body = build_schedule_request(params, SourceIngest(**source))
    return await schedule_ingest(name, body, user=user)


async def preview_add_member(params: dict, user: dict) -> dict:
    """Who is being given what, on which collection — and, if they are already a
    member, what role they are being moved from."""
    from app.api.ai_vectors import list_members
    name, username = params["collection"], params["username"]
    try:
        current = await list_members(name, user=user)
        existing = next((m for m in (current.get("members") or [])
                          if m.get("username") == username), None)
    except Exception as e:
        # Important 5: current_role: null must not stand in for "the lookup failed"
        # — it is what a genuine non-member also looks like. Say the read failed.
        return {"collection": name, "username": username, "new_role": params["role"],
                "summary": f"Add {username!r} to {name!r} as {params['role']!r} — "
                          f"their current membership could not be read to confirm "
                          f"this: {e}"}
    return {
        "collection": name,
        "username": username,
        "new_role": params["role"],
        "current_role": existing.get("role") if existing else None,
    }


def build_member_grant(params: dict):
    from app.api.ai_vectors import MemberGrant
    return MemberGrant(username=params["username"], role=params["role"])


async def add_member_action(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import add_member
    return await add_member(params["collection"], build_member_grant(params), user=user)


async def preview_remove_member(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import list_members
    name, username = params["collection"], params["username"]
    try:
        current = await list_members(name, user=user)
        existing = next((m for m in (current.get("members") or [])
                          if m.get("username") == username), None)
    except Exception as e:
        # Important 5: is_member: false must not stand in for "the lookup failed"
        # — it is exactly what a genuine non-member also looks like.
        return {"collection": name, "username": username,
                "summary": f"Remove {username!r} from {name!r} — their current "
                          f"membership could not be read to confirm this: {e}"}
    return {
        "collection": name,
        "username": username,
        "current_role": existing.get("role") if existing else None,
        "is_member": existing is not None,
    }


async def remove_member_action(params: dict, user: dict) -> dict:
    from app.api.ai_vectors import remove_member
    return await remove_member(params["collection"], params["username"], user=user)


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
    Action("knowledge.set_refresh_schedule", "Set refresh schedule",
           "Change how often a collection re-embeds from its already-configured "
           "source, turning automatic refresh on.",
           ("*",), "knowledge:write", ActionKind.MUTATE, RefreshScheduleParams),
    Action("knowledge.add_member", "Add collection member",
           "Share a knowledge collection with one more person, as reader or editor.",
           ("*",), "knowledge:write", ActionKind.MUTATE, MemberGrantParams),
    Action("knowledge.remove_member", "Remove collection member",
           "Revoke one person's access to a knowledge collection.",
           ("*",), "knowledge:write", ActionKind.MUTATE, MemberRemoveParams),
)

EXECUTORS: Dict[str, Callable] = {
    "knowledge.search": search_knowledge,
    "knowledge.answer_with_citations": answer_with_citations,
    "knowledge.create_collection": create_collection,
    "knowledge.list_collections": list_collections_action,
    "knowledge.collection_composition": collection_composition_action,
    "knowledge.diagnose_collection": diagnose_collection,
    "knowledge.set_refresh_schedule": set_refresh_schedule_action,
    "knowledge.add_member": add_member_action,
    "knowledge.remove_member": remove_member_action,
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
    "knowledge.set_refresh_schedule": _r("app.api.ai_vectors", "schedule_ingest"),
    "knowledge.add_member": _r("app.api.ai_vectors", "add_member"),
    "knowledge.remove_member": _r("app.api.ai_vectors", "remove_member"),
}

PREVIEWERS: Dict[str, Callable] = {
    "knowledge.create_collection": preview_create_collection,
    "knowledge.set_refresh_schedule": preview_set_refresh_schedule,
    "knowledge.add_member": preview_add_member,
    "knowledge.remove_member": preview_remove_member,
}
