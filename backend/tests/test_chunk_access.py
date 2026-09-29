"""Chunk-level access: a caller retrieves only the chunks its attributes match.

See app/chunk_access.py for the rule and why it fails closed.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from app import chunk_access
from app.api import ai_vectors
from app.chunk_access import ChunkRule, InvalidRule

USER_ID = "11111111-1111-1111-1111-111111111111"
HR = {"id": USER_ID, "username": "ada", "role": "analyst"}


# ── the rule ──────────────────────────────────────────────────────────────────

def test_a_rule_names_a_metadata_key_and_a_user_attribute():
    assert chunk_access.validate({"metadata_key": "dept", "user_attribute": "department"}) \
        == ChunkRule("dept", "department")


@pytest.mark.parametrize("raw", [
    None, "dept", {"metadata_key": "dept"},
    {"metadata_key": "de pt", "user_attribute": "department"},
    {"metadata_key": "dept", "user_attribute": "x" * 65},
    {"metadata_key": "dept'; drop", "user_attribute": "department"},
])
def test_a_malformed_rule_is_refused(raw):
    with pytest.raises(InvalidRule):
        chunk_access.validate(raw)


def test_no_stored_rule_means_no_filter():
    assert chunk_access.parse_stored(None) is None
    assert chunk_access.parse_stored({}) is None


def test_a_stored_rule_that_no_longer_parses_denies_rather_than_opens():
    rule = chunk_access.parse_stored('{"metadata_key": "bad key"}')
    assert rule is not None
    assert chunk_access.parse_stored("not json") is not None


def test_caller_values_accept_a_string_a_list_and_json_text():
    assert chunk_access.caller_values({"department": "hr"}, "department") == ["hr"]
    assert chunk_access.caller_values({"department": ["hr", "legal"]}, "department") == ["hr", "legal"]
    assert chunk_access.caller_values('{"level": 3}', "level") == ["3"]
    assert chunk_access.caller_values({"on": True}, "on") == ["true"]


def test_a_caller_without_the_attribute_has_no_values():
    assert chunk_access.caller_values({}, "department") == []
    assert chunk_access.caller_values(None, "department") == []
    assert chunk_access.caller_values({"department": ""}, "department") == []
    assert chunk_access.caller_values({"department": {"x": 1}}, "department") == []


def test_labels_cannot_overwrite_what_ingest_writes():
    assert chunk_access.validate_labels({"department": "hr"}) == {"department": "hr"}
    with pytest.raises(InvalidRule):
        chunk_access.validate_labels({"row": "3"})
    with pytest.raises(InvalidRule):
        chunk_access.validate_labels({"bad key": "x"})


# ── retrieval ─────────────────────────────────────────────────────────────────

class _Conn:
    """Answers the three queries _retrieve issues: the access gate, the rule +
    caller attributes, and the vector search (plus the withheld count)."""

    def __init__(self, rule, attributes, rows=(), withheld=0):
        self.rule, self.attributes, self.rows, self.withheld = rule, attributes, list(rows), withheld
        self.fetches = []       # vector searches (fetch) and counts (fetchval) alike
        self.searches = []      # vector searches only

    async def fetchrow(self, sql, *args):
        if "ai_collection_members" in sql:
            return {"id": "coll-1", "owner_id": None, "pii_mode": None,
                    "sensitivity": None, "member_role": None}
        if "chunk_access" in sql:
            return {"chunk_access": json.dumps(self.rule) if self.rule else None,
                    "attributes": json.dumps(self.attributes)}
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        self.fetches.append((sql, args))
        self.searches.append((sql, args))
        return self.rows

    async def fetchval(self, sql, *args):
        self.fetches.append((sql, args))
        return self.withheld

    async def execute(self, sql, *args):      # the iterative-scan setting
        return "SELECT 1"

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self, *a, **kw):
        return self.conn


def _install(monkeypatch, conn):
    async def _pool():
        return _Pool(conn)

    async def _embed(texts):
        return [[0.0] * 4 for _ in texts]
    monkeypatch.setattr(ai_vectors, "get_db_pool", _pool)
    monkeypatch.setattr(ai_vectors, "_embed", _embed)
    monkeypatch.setattr(ai_vectors, "_rerank_model", lambda: "")


def _row(dept):
    return {"source": f"doc-{dept}", "chunk_index": 0, "content": "text",
            "metadata": json.dumps({"dept": dept}), "score": 0.9}


RULE = {"metadata_key": "dept", "user_attribute": "department"}


def test_without_a_rule_retrieval_is_unchanged(monkeypatch):
    conn = _Conn(None, {"department": "hr"}, rows=[_row("hr"), _row("sales")])
    _install(monkeypatch, conn)
    hits, _ = asyncio.run(ai_vectors._retrieve("c", "q", 5, HR))
    assert len(hits) == 2
    sql, args = conn.fetches[0]
    assert "metadata" not in sql.split("WHERE", 1)[1]


def test_the_filter_is_in_the_vector_query_before_the_limit(monkeypatch):
    conn = _Conn(RULE, {"department": ["hr", "legal"]}, rows=[_row("hr")])
    _install(monkeypatch, conn)
    asyncio.run(ai_vectors._retrieve("c", "q", 5, HR))
    sql, args = conn.fetches[0]
    where = sql.split("WHERE", 1)[1]
    assert "metadata ->> $4::text" in where and "= ANY($5::text[])" in where
    assert where.index("ANY") < where.index("LIMIT")
    assert args[3] == "dept" and args[4] == ["hr", "legal"]


def test_a_caller_without_the_attribute_retrieves_nothing(monkeypatch):
    conn = _Conn(RULE, {}, rows=[_row("hr")], withheld=3)
    _install(monkeypatch, conn)
    hits, _ = asyncio.run(ai_vectors._retrieve("c", "q", 5, HR))
    assert hits == []
    assert conn.searches == []            # nothing to match, so no search at all


def test_how_many_near_chunks_were_withheld_is_recorded(monkeypatch):
    conn = _Conn(RULE, {"department": "hr"}, rows=[_row("hr")], withheld=4)
    _install(monkeypatch, conn)
    async def _run():
        await ai_vectors._retrieve("c", "q", 5, HR)
        return ai_vectors._withheld.get()
    assert asyncio.run(_run()) == 4


def test_the_withheld_count_reaches_the_tool_call_log(monkeypatch):
    from app import tool_call_log
    recorded = []

    async def _record(**kw):
        recorded.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl():
        ai_vectors._withheld.set(2)
        return {"results": [], "pii_masked": 0}
    asyncio.run(ai_vectors._logged("ai.search", "c", "q", HR, _impl))
    assert recorded[0]["chunks_withheld"] == 2


def test_the_caller_is_not_told_what_was_withheld(monkeypatch):
    conn = _Conn(RULE, {"department": "hr"}, rows=[_row("hr")], withheld=4)
    _install(monkeypatch, conn)
    from app import tool_call_log

    async def _record(**kw):
        return None
    monkeypatch.setattr(tool_call_log, "record", _record)
    out = asyncio.run(ai_vectors.search(ai_vectors.SearchRequest(collection="c", query="q"), HR))
    assert "withheld" not in json.dumps(out)


# ── the tool call log row ─────────────────────────────────────────────────────

def test_the_row_carries_chunks_withheld():
    from app import tool_call_log
    row = tool_call_log.build_row(actor=HR, tool="ai.search", resource_kind="collection",
                                  resource=["c"], request_text="q", chunks_withheld=3)
    assert row["chunks_withheld"] == 3
    assert "chunks_withheld" in tool_call_log._INSERT


# ── setting the rule ──────────────────────────────────────────────────────────

class _SetConn:
    def __init__(self):
        self.executed = []

    async def fetchrow(self, sql, *args):
        return {"id": "coll-1", "owner_id": USER_ID, "pii_mode": None,
                "sensitivity": None, "member_role": None}

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "UPDATE 1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_an_owner_sets_and_clears_the_rule(monkeypatch):
    conn = _SetConn()

    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(ai_vectors, "get_db_pool", _pool)
    out = asyncio.run(ai_vectors.set_chunk_access(
        "c", ai_vectors.ChunkAccessBody(metadata_key="dept", user_attribute="department"), HR))
    assert out["chunk_access"] == {"metadata_key": "dept", "user_attribute": "department"}
    assert json.loads(conn.executed[-1][1][1]) == out["chunk_access"]

    asyncio.run(ai_vectors.clear_chunk_access("c", HR))
    assert conn.executed[-1][1][1] is None


def test_setting_a_bad_rule_is_a_400(monkeypatch):
    conn = _SetConn()

    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(ai_vectors, "get_db_pool", _pool)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_vectors.set_chunk_access(
            "c", ai_vectors.ChunkAccessBody(metadata_key="bad key", user_attribute="d"), HR))
    assert exc.value.status_code == 400
    assert conn.executed == []


# ── showing the rule ──────────────────────────────────────────────────────────

class _ListConn:
    def __init__(self, stored):
        self.stored = stored

    async def fetchval(self, sql, *args):
        return 1

    async def fetch(self, sql, *args):
        assert "col.chunk_access" in sql
        import datetime
        return [{"name": "c", "embed_model": "m", "dim": 3, "description": None,
                 "created_at": datetime.datetime(2026, 1, 1), "owner_id": None,
                 "chunk_access": self.stored, "chunks": 0, "sources": 0,
                 "last_ingested": None}]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.parametrize("stored,shown", [
    (None, None),
    ('{"metadata_key": "dept", "user_attribute": "department"}',
     {"metadata_key": "dept", "user_attribute": "department"}),
    ('{"metadata_key": "bad key", "user_attribute": "d"}', {"invalid": True}),
])
def test_the_collection_list_carries_the_rule(monkeypatch, stored, shown):
    async def _pool():
        return _Pool(_ListConn(stored))
    monkeypatch.setattr(ai_vectors, "get_db_pool", _pool)
    out = asyncio.run(ai_vectors.list_collections(user={**HR, "role": "admin"}))
    assert out["collections"][0]["chunk_access"] == shown


# ── labels at ingest ──────────────────────────────────────────────────────────

def test_an_iceberg_label_column_lands_in_each_chunks_metadata(monkeypatch):
    captured = {}

    class _Eng:
        ai_table_prefix = "iceberg"

    class _Cur:
        def execute(self, sql):
            captured["sql"] = sql

        def fetchall(self):
            return [("hello", "hr"), ("world", None)]

    class _TConn:
        def cursor(self):
            return _Cur()

    import app.api.query_engine as qe
    import app.api.trino_util as tu
    monkeypatch.setattr(qe, "get_engine", lambda: _Eng())
    monkeypatch.setattr(tu, "trino_conn", lambda timeout=60: _TConn())
    docs = ai_vectors._read_iceberg_docs("s", "t", "body", 10, label_column="dept")
    assert '"dept"' in captured["sql"]
    assert docs[0][2]["dept"] == "hr"
    assert "dept" not in docs[1][2]          # no label, no key: the rule hides it


def test_constant_labels_are_validated_on_the_source():
    with pytest.raises(HTTPException) as exc:
        ai_vectors._source_labels(ai_vectors.SourceIngest(type="s3", bucket="b",
                                                          labels={"row": "1"}))
    assert exc.value.status_code == 400
    ok = ai_vectors.SourceIngest(type="s3", bucket="b", labels={"department": "hr"})
    assert ai_vectors._source_labels(ok) == {"department": "hr"}
