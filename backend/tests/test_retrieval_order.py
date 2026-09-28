"""A collection's rules apply before its query leaves the building.

`_collection_id` is where a collection's own PII mode and its local-only label are
applied to the request. Search and RAG used to guard the query and embed it first,
and ask the collection second, so a query against a local-only collection went to the
deployment's external embedding model, a query against a `pii_mode=block` collection
was masked rather than refused, and a caller with no access still paid for an
embedding before being told 403.

And a chunk access rule filters inside an HNSW `ORDER BY … LIMIT`: without iterative
scan pgvector filters only the first `ef_search` candidates, so a caller entitled to
a small slice of a large collection got a few results, or none, while matching chunks
existed.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from app.api import ai_vectors
from app.api.ai_backends import egress_policy
from app.guardrails import pii_ko

USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "ada", "role": "analyst"}
PHONE = "연락처 010-1234-5678 로 알려줘"


class _Conn:
    def __init__(self, events, *, collection=None, rule=None, attributes=None, rows=()):
        self.events = events
        self.collection = collection or {}
        self.rule, self.attributes, self.rows = rule, attributes or {}, list(rows)
        self.executed = []
        self.in_transaction = 0

    async def fetchrow(self, sql, *args):
        if "ai_collection_members" in sql:
            self.events.append("gate")
            if self.collection.get("denied"):
                return {"id": "coll-1", "owner_id": "someone-else", "pii_mode": None,
                        "sensitivity": None, "member_role": None}
            return {"id": "coll-1", "owner_id": None,
                    "pii_mode": self.collection.get("pii_mode"),
                    "sensitivity": self.collection.get("sensitivity"), "member_role": None}
        if "chunk_access" in sql:
            return {"chunk_access": json.dumps(self.rule) if self.rule else None,
                    "attributes": json.dumps(self.attributes)}
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        self.events.append(("search", self.in_transaction))
        return self.rows

    async def fetchval(self, sql, *args):
        return 0

    async def execute(self, sql, *args):
        self.executed.append((sql, args, self.in_transaction))
        return "SELECT 1"

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                conn.in_transaction += 1

            async def __aexit__(self, *exc):
                conn.in_transaction -= 1
                return False
        return _Tx()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install(monkeypatch, conn, events):
    class _Pool:
        def acquire(self, *a, **k):
            return conn

    async def _pool():
        return _Pool()

    async def _embed(texts):
        # What the embedding call would see: the policy and guardrail in force.
        events.append(("embed", egress_policy(), pii_ko.get_mode(), texts[0]))
        return [[0.0] * 4 for _ in texts]
    monkeypatch.setattr(ai_vectors, "get_db_pool", _pool)
    monkeypatch.setattr(ai_vectors, "_embed", _embed)
    monkeypatch.setattr(ai_vectors, "_rerank_model", lambda: "")


def _embed_event(events):
    return next(e for e in events if isinstance(e, tuple) and e[0] == "embed")


def test_retrieve_asks_the_collection_before_embedding(monkeypatch):
    events = []
    _install(monkeypatch, _Conn(events), events)
    asyncio.run(ai_vectors._retrieve("c", "q", 5, USER))
    assert events.index("gate") < events.index(_embed_event(events))


def test_a_caller_without_access_costs_no_embedding(monkeypatch):
    events = []
    _install(monkeypatch, _Conn(events, collection={"denied": True}), events)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_vectors._retrieve("c", "q", 5, USER))
    assert exc.value.status_code == 403
    assert not any(isinstance(e, tuple) and e[0] == "embed" for e in events)


def test_a_local_only_collection_holds_its_own_query_to_local_models(monkeypatch):
    monkeypatch.delenv("AI_EGRESS_POLICY", raising=False)
    events = []
    _install(monkeypatch, _Conn(events, collection={"sensitivity": "restricted"}), events)
    asyncio.run(ai_vectors._search_impl(
        ai_vectors.SearchRequest(collection="c", query="q"), USER))
    assert _embed_event(events)[1] == "local-only"


def test_a_block_collection_refuses_a_query_carrying_pii(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    events = []
    _install(monkeypatch, _Conn(events, collection={"pii_mode": "block"}), events)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_vectors._search_impl(
            ai_vectors.SearchRequest(collection="c", query=PHONE), USER))
    assert exc.value.status_code == 400
    assert not any(isinstance(e, tuple) and e[0] == "embed" for e in events)


def test_rag_on_a_block_collection_refuses_a_question_carrying_pii(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    events = []
    _install(monkeypatch, _Conn(events, collection={"pii_mode": "block"}), events)
    out = asyncio.run(ai_vectors._rag_impl(
        ai_vectors.RagRequest(collection="c", question=PHONE), USER))
    assert out["has_ai"] is False and out["citations"] == []
    assert not any(isinstance(e, tuple) and e[0] == "embed" for e in events)


def test_a_chunk_rule_turns_on_iterative_scan_for_its_search(monkeypatch):
    events = []
    conn = _Conn(events, rule={"metadata_key": "dept", "user_attribute": "department"},
                 attributes={"department": "hr"})
    _install(monkeypatch, conn, events)
    asyncio.run(ai_vectors._retrieve("c", "q", 5, USER))
    scan = [(sql, args, tx) for sql, args, tx in conn.executed if "iterative_scan" in str(args) + sql]
    assert scan, "iterative scan was not requested"
    assert scan[0][2] >= 1                  # SET LOCAL-scoped: inside a transaction
    assert ("search", 1) in events or any(e == ("search", 2) for e in events)
