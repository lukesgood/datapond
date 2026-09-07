# Tool Call Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every successful call to `/api/ai/search`, `/api/ai/rag`, `/api/ai/sql` and `/api/queries/execute` leaves an append-only row saying who called which tool against which collection or tables, what was returned (hit count, citation sources, PII masked), and that row is readable, exportable as NDJSON, and included in the governance compliance report.

**Architecture:** A new table `tool_call_log` (migration `0008`) with the same append-only trigger pattern as `0005`. A new module `app/tool_call_log.py` mirrors `app/security_audit.py`: pure `build_row`, a never-raising async `record`. The four route handlers are split into `_impl` functions plus thin wrappers that time the call, call `record`, and re-raise; the chat executors keep calling the public names so they are logged with `via='chat'`. Read paths: a new router `app/api/tool_call_routes.py` (list, per-actor summary, NDJSON export) and a fourth section in the frontend compliance report.

**Tech Stack:** FastAPI, asyncpg-style `$n` SQL, Alembic wrapper migrations (`.py` + `.sql`), pydantic v2, sqlglot 26 (already a dependency), Next.js App Router, `node --test` for `frontend/lib`.

**Spec:** `docs/superpowers/specs/2026-09-07-positioning-gap-closure-design.md` §2

## Global Constraints

- Python 3.11+ (local default `python3` is 3.9 and cannot import the app; use `python3.12`).
- **No database in tests.** DB behaviour is tested with fake pool/conn classes; migrations are tested by asserting on the `.sql` text.
- Async tests use `asyncio.new_event_loop().run_until_complete(coro)`; do not add pytest-asyncio.
- New migration must be `0008_tool_call_log` with `down_revision = "0007_seed_roles"`; only `CREATE TABLE`, `CREATE INDEX`, `CREATE FUNCTION`, `CREATE TRIGGER`, `REVOKE` — `app/migration_rules.py` forbids `DROP TABLE|COLUMN`, `RENAME`, `SET NOT NULL`.
- Every mutating route needs a permission dependency (`tests/test_route_authorization_inventory.py`); the routes added here are all `GET`.
- `tests/test_chat_audit_aggregate.py` reads the SQL text of chat audit aggregates and rejects any selected column that is not a category or a count.
- Nothing raw is written: `request_masked`/`request_hash` are computed from text **after** `pii_ko` masking.
- The tool call log is written regardless of `save_history`.
- Frontend tests exist only as `frontend/lib/*.test.ts` under `node --test`; pure logic goes in `frontend/lib`, imported with explicit `.ts` extension.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PQW9stoiSQnnohhnBCDEvL
  ```
- Run backend tests from `backend/`: `python3.12 -m pytest tests -q --ignore=tests/acceptance`.

---

### Task 1: Migration `0008_tool_call_log`

**Files:**
- Create: `backend/migrations/versions/0008_tool_call_log.py`
- Create: `backend/migrations/versions/0008_tool_call_log.sql`
- Test: `backend/tests/test_tool_call_log_migration.py`

**Interfaces:**
- Produces: table `public.tool_call_log`, function `public.prune_tool_call_log(cutoff_ts timestamptz) RETURNS bigint`, trigger `tool_call_log_append_only`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tool_call_log_migration.py
"""The tool call log migration, checked as text — there is no database in this test
environment (see test_audit_append_only.py for the same approach)."""
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0008_tool_call_log.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0008_tool_call_log.py").read_text(encoding="utf-8")


def test_revision_chain_points_at_seed_roles():
    assert 'revision: str = "0008_tool_call_log"' in PY
    assert 'down_revision: Union[str, None] = "0007_seed_roles"' in PY


def test_table_columns_present():
    for col in ("actor_id", "actor_username", "actor_kind", "tool", "resource_kind",
                "resource", "request_hash", "request_masked", "hit_count",
                "citation_sources", "pii_masked", "outcome", "duration_ms",
                "client_address", "via", "occurred_at"):
        assert re.search(rf"^\s+{col}\s", SQL, re.M), col


def test_tool_and_outcome_are_constrained():
    assert "CHECK (tool IN ('ai.search', 'ai.rag', 'ai.sql', 'query.execute'))" in SQL
    assert "CHECK (outcome IN ('ok', 'degraded', 'error'))" in SQL
    assert "CHECK (actor_kind IN ('human', 'service'))" in SQL


def test_append_only_trigger_and_prune_function():
    assert "CREATE TRIGGER tool_call_log_append_only" in SQL
    assert "BEFORE UPDATE OR DELETE ON public.tool_call_log" in SQL
    assert "EXECUTE FUNCTION public.reject_audit_log_mutation()" in SQL
    assert "REVOKE UPDATE ON TABLE public.tool_call_log FROM CURRENT_USER" in SQL
    assert "CREATE OR REPLACE FUNCTION public.prune_tool_call_log(cutoff_ts timestamptz)" in SQL
    assert "set_config('datapond.audit_retention_delete', 'on', true)" in SQL


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0008_tool_call_log", SQL) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_migration.py -q`
Expected: FAIL with `FileNotFoundError` on the `.sql` read.

- [ ] **Step 3: Write the SQL migration**

```sql
-- backend/migrations/versions/0008_tool_call_log.sql
-- One row per successful data-tool call: who, which tool, which collection or tables,
-- what came back. security_audit_log records authorization *decisions* and deliberately
-- skips allows on read permissions; this table records the other fact — that a tool
-- returned data — with the columns that fact needs. Design:
-- docs/superpowers/specs/2026-09-07-positioning-gap-closure-design.md §2.
--
-- request_masked / request_hash are derived from text AFTER the pii_ko guard ran.
-- Nothing raw is written here.
CREATE TABLE IF NOT EXISTS public.tool_call_log (
    id               bigserial PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT now(),
    actor_id         uuid REFERENCES public.users (id) ON DELETE SET NULL,
    actor_username   text NOT NULL DEFAULT '',
    actor_kind       text NOT NULL CHECK (actor_kind IN ('human', 'service')),
    tool             text NOT NULL CHECK (tool IN ('ai.search', 'ai.rag', 'ai.sql', 'query.execute')),
    resource_kind    text NOT NULL CHECK (resource_kind IN ('collection', 'tables', 'none')),
    resource         text[] NOT NULL DEFAULT '{}',
    request_hash     text NOT NULL,
    request_masked   text,
    hit_count        integer NOT NULL DEFAULT 0,
    citation_sources text[] NOT NULL DEFAULT '{}',
    pii_masked       integer NOT NULL DEFAULT 0,
    outcome          text NOT NULL CHECK (outcome IN ('ok', 'degraded', 'error')),
    duration_ms      integer,
    client_address   text,
    via              text NOT NULL DEFAULT 'api'
);
CREATE INDEX IF NOT EXISTS idx_tool_call_log_actor
    ON public.tool_call_log USING btree (actor_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_call_log_time
    ON public.tool_call_log USING btree (occurred_at DESC);

-- Same append-only contract as 0005, same honesty note: the application role owns this
-- table, so this stops ordinary code paths, not a caller running arbitrary SQL as the
-- owner. reject_audit_log_mutation() already exists from 0005 and is reused unchanged.
REVOKE UPDATE ON TABLE public.tool_call_log FROM CURRENT_USER;

DROP TRIGGER IF EXISTS tool_call_log_append_only ON public.tool_call_log;
CREATE TRIGGER tool_call_log_append_only
    BEFORE UPDATE OR DELETE ON public.tool_call_log
    FOR EACH ROW EXECUTE FUNCTION public.reject_audit_log_mutation();

-- The only sanctioned delete path; app/audit_retention.py calls it and nothing else.
CREATE OR REPLACE FUNCTION public.prune_tool_call_log(cutoff_ts timestamptz)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public
AS $$
DECLARE
    deleted_count bigint;
BEGIN
    PERFORM set_config('datapond.audit_retention_delete', 'on', true);
    DELETE FROM public.tool_call_log WHERE occurred_at < cutoff_ts;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    PERFORM set_config('datapond.audit_retention_delete', 'off', true);
    RETURN deleted_count;
END;
$$;
```

- [ ] **Step 4: Write the Python wrapper**

```python
# backend/migrations/versions/0008_tool_call_log.py
"""tool call log — one row per successful data-tool call.

Revision ID: 0008_tool_call_log
Revises: 0007_seed_roles
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op

from app.migrations import run_sql, run_sql_file

revision: str = "0008_tool_call_log"
down_revision: Union[str, None] = "0007_seed_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    run_sql_file(op.get_bind(), Path(__file__).with_suffix(".sql"))


def downgrade() -> None:
    run_sql(
        op.get_bind(),
        "DROP FUNCTION IF EXISTS public.prune_tool_call_log(timestamptz); "
        "DROP TABLE IF EXISTS public.tool_call_log;",
    )
```

- [ ] **Step 5: Run the new test and the migration suite**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_migration.py tests/test_migrations.py tests/test_audit_append_only.py tests/test_migration_review_rules.py -q`
Expected: PASS. If `test_audit_append_only.py` asserts that only `0005` sets the `datapond.audit_retention_delete` GUC, extend that test's allowlist with `0008_tool_call_log.sql` and the function name `prune_tool_call_log` — the trigger and GUC are deliberately shared.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0008_tool_call_log.py backend/migrations/versions/0008_tool_call_log.sql backend/tests/test_tool_call_log_migration.py
git commit -m "feat(audit): tool_call_log table, append-only, with its own prune function"
```

---

### Task 2: `app/tool_call_log.py` — build a row, record it, never raise

**Files:**
- Create: `backend/app/tool_call_log.py`
- Test: `backend/tests/test_tool_call_log.py`

**Interfaces:**
- Produces:
  - `TOOLS = ("ai.search", "ai.rag", "ai.sql", "query.execute")`
  - `build_row(*, actor: dict, tool: str, resource_kind: str, resource: list[str], request_text: str, hit_count: int = 0, citation_sources: list[str] | None = None, pii_masked: int = 0, outcome: str = "ok", duration_ms: int | None = None, client_address: str | None = None, via: str | None = None, now: datetime | None = None) -> dict`
  - `async record(**same kwargs as build_row minus now) -> None`
  - `table_names(sql: str) -> list[str]` (sorted, distinct, dotted names as written; `[]` on parse failure)
  - `via(value: str)` context manager and `current_via() -> str` (ContextVar, default `"api"`)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_tool_call_log.py
import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from app import tool_call_log as tcl


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


HUMAN = {"id": "11111111-1111-1111-1111-111111111111", "username": "mina", "role": "ai_engineer"}
SERVICE = {**HUMAN, "id": "22222222-2222-2222-2222-222222222222", "username": "svc-bot",
           "auth_method": "service"}


def test_build_row_masks_hash_and_truncates():
    text = "x" * 600
    row = tcl.build_row(actor=HUMAN, tool="ai.search", resource_kind="collection",
                        resource=["faq"], request_text=text, hit_count=3,
                        citation_sources=["b.md", "a.md", "a.md"], pii_masked=2,
                        now=datetime(2026, 9, 7, tzinfo=timezone.utc))
    assert row["request_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert row["request_masked"] == "x" * 512
    assert row["citation_sources"] == ["a.md", "b.md"]
    assert row["actor_kind"] == "human"
    assert row["via"] == "api"
    assert row["occurred_at"] == datetime(2026, 9, 7, tzinfo=timezone.utc)


def test_build_row_service_account_kind():
    row = tcl.build_row(actor=SERVICE, tool="ai.rag", resource_kind="collection",
                        resource=["faq"], request_text="q")
    assert row["actor_kind"] == "service"
    assert row["actor_id"] == SERVICE["id"]
    assert row["actor_username"] == "svc-bot"


@pytest.mark.parametrize("field,value", [
    ("tool", "nope"), ("resource_kind", "shelf"), ("outcome", "meh"),
])
def test_build_row_rejects_unknown_vocabulary(field, value):
    kwargs = dict(actor=HUMAN, tool="ai.sql", resource_kind="none", resource=[],
                  request_text="q", outcome="ok")
    kwargs[field] = value
    with pytest.raises(ValueError):
        tcl.build_row(**kwargs)


def test_via_context_defaults_to_api_and_restores():
    assert tcl.current_via() == "api"
    with tcl.via("chat"):
        assert tcl.current_via() == "chat"
    assert tcl.current_via() == "api"


def test_table_names_from_sql():
    assert tcl.table_names("SELECT a.x FROM sales.orders a JOIN dim.customer c ON a.c = c.id") \
        == ["dim.customer", "sales.orders"]
    assert tcl.table_names("this is not sql (") == []


class _FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


class _BrokenPool:
    def acquire(self):
        raise RuntimeError("pool is gone")


def _patch_pool(monkeypatch, pool):
    async def _get_db_pool():
        return pool
    import app.api.connectors as connectors
    monkeypatch.setattr(connectors, "get_db_pool", _get_db_pool)


def test_record_inserts_one_row(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, _FakePool(conn))
    _run(tcl.record(actor=HUMAN, tool="query.execute", resource_kind="tables",
                    resource=["sales.orders"], request_text="SELECT 1", hit_count=1,
                    outcome="ok", duration_ms=12))
    assert len(conn.calls) == 1
    sql, args = conn.calls[0]
    assert "INSERT INTO public.tool_call_log" in sql
    assert "query.execute" in args and ["sales.orders"] in args


def test_record_never_raises(monkeypatch):
    _patch_pool(monkeypatch, _BrokenPool())
    _run(tcl.record(actor=HUMAN, tool="ai.sql", resource_kind="none", resource=[],
                    request_text="q"))  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log.py -q`
Expected: FAIL with `ModuleNotFoundError: app.tool_call_log`.

- [ ] **Step 3: Implement the module**

```python
# backend/app/tool_call_log.py
"""One row per successful data-tool call.

security_audit records authorization decisions and skips allows on read permissions so
the read paths pay nothing. This module records a different fact — a tool returned data
to a caller — with the columns that fact needs: which collection or tables, how many
hits, which sources were cited, how much PII was masked. It is written after the guard
ran, so nothing raw lands here, and like security_audit it never raises into the caller.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)

TOOLS = ("ai.search", "ai.rag", "ai.sql", "query.execute")
RESOURCE_KINDS = ("collection", "tables", "none")
OUTCOMES = ("ok", "degraded", "error")
_MASKED_LIMIT = 512

_via: contextvars.ContextVar[str] = contextvars.ContextVar("tool_call_via", default="api")


def current_via() -> str:
    return _via.get()


@contextmanager
def via(value: str) -> Iterator[None]:
    token = _via.set(value)
    try:
        yield
    finally:
        _via.reset(token)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def table_names(sql: str) -> List[str]:
    """Distinct dotted table names as written in `sql`, sorted; [] if unparseable."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql)
    except Exception:
        return []
    names = set()
    for t in tree.find_all(exp.Table):
        parts = [p for p in (t.catalog, t.db, t.name) if p]
        if parts:
            names.add(".".join(parts))
    return sorted(names)


def build_row(*, actor: dict, tool: str, resource_kind: str, resource: List[str],
              request_text: str, hit_count: int = 0,
              citation_sources: Optional[List[str]] = None, pii_masked: int = 0,
              outcome: str = "ok", duration_ms: Optional[int] = None,
              client_address: Optional[str] = None, via: Optional[str] = None,
              now: Optional[datetime] = None) -> dict:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}")
    if resource_kind not in RESOURCE_KINDS:
        raise ValueError(f"unknown resource_kind {resource_kind!r}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    actor = actor or {}
    text = request_text or ""
    return {
        "occurred_at": now or utcnow(),
        "actor_id": actor.get("id"),
        "actor_username": actor.get("username") or "",
        "actor_kind": "service" if actor.get("auth_method") == "service" else "human",
        "tool": tool,
        "resource_kind": resource_kind,
        "resource": list(resource or []),
        "request_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "request_masked": text[:_MASKED_LIMIT],
        "hit_count": int(hit_count or 0),
        "citation_sources": sorted(set(citation_sources or [])),
        "pii_masked": int(pii_masked or 0),
        "outcome": outcome,
        "duration_ms": duration_ms,
        "client_address": client_address,
        "via": via or current_via(),
    }


_INSERT = """
INSERT INTO public.tool_call_log
    (occurred_at, actor_id, actor_username, actor_kind, tool, resource_kind, resource,
     request_hash, request_masked, hit_count, citation_sources, pii_masked, outcome,
     duration_ms, client_address, via)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
"""


async def record(*, actor: dict, tool: str, resource_kind: str, resource: List[str],
                 request_text: str, hit_count: int = 0,
                 citation_sources: Optional[List[str]] = None, pii_masked: int = 0,
                 outcome: str = "ok", duration_ms: Optional[int] = None,
                 client_address: Optional[str] = None, via: Optional[str] = None) -> None:
    """Write one row. Never raises into the caller — a failed audit write is logged."""
    try:
        row = build_row(actor=actor, tool=tool, resource_kind=resource_kind,
                        resource=resource, request_text=request_text,
                        hit_count=hit_count, citation_sources=citation_sources,
                        pii_masked=pii_masked, outcome=outcome, duration_ms=duration_ms,
                        client_address=client_address, via=via)
        # Lazy import, same reason as security_audit: app.api.connectors imports
        # app.api.auth at module load and this module is imported by route modules.
        from app.api.connectors import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                _INSERT, row["occurred_at"], row["actor_id"], row["actor_username"],
                row["actor_kind"], row["tool"], row["resource_kind"], row["resource"],
                row["request_hash"], row["request_masked"], row["hit_count"],
                row["citation_sources"], row["pii_masked"], row["outcome"],
                row["duration_ms"], row["client_address"], row["via"],
            )
    except Exception:
        logger.error("tool_call_log: failed to record tool=%s actor=%s — this call is "
                     "not in the tool call log", tool, (actor or {}).get("username"),
                     exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/tool_call_log.py backend/tests/test_tool_call_log.py
git commit -m "feat(audit): tool_call_log module — build a masked row, record it, never raise"
```

---

### Task 3: Log `/ai/search` and `/ai/rag`

**Files:**
- Modify: `backend/app/api/ai_vectors.py:1282-1379` (the `search` and `rag` handlers)
- Test: `backend/tests/test_tool_call_log_routes_ai.py`

**Interfaces:**
- Consumes: `app.tool_call_log.record`, `TOOLS` vocabulary from Task 2.
- Produces: `_search_impl(req, user) -> dict` and `_rag_impl(req, user) -> dict` (the old bodies); public `search`/`rag` keep their names, decorators and signatures so `app/chat/analysis/knowledge.py:42-56` keeps working unchanged.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tool_call_log_routes_ai.py
"""search/rag wrappers record one tool_call_log row per successful call and re-raise
on failure. The bodies are stubbed; only the wrapper contract is under test."""
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import ai_vectors, auth

_REAL_REQUIRE_USER = auth.require_user
USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "eng", "role": "ai_engineer"}


def _app():
    app = FastAPI()
    app.include_router(ai_vectors.router, prefix="/api")

    async def _override():
        return USER
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def _capture(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)
    return calls


def test_search_records_hits_and_sources(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        return {"collection": req.collection, "query": req.query, "pii_masked": 2,
                "concepts": [], "results": [{"source": "b.md"}, {"source": "a.md"}]}
    monkeypatch.setattr(ai_vectors, "_search_impl", _impl)

    r = TestClient(_app()).post("/api/ai/search", json={"collection": "faq", "query": "hi"})
    assert r.status_code == 200
    assert len(calls) == 1
    c = calls[0]
    assert c["tool"] == "ai.search" and c["resource_kind"] == "collection"
    assert c["resource"] == ["faq"] and c["hit_count"] == 2
    assert c["citation_sources"] == ["b.md", "a.md"] and c["pii_masked"] == 2
    assert c["outcome"] == "ok" and isinstance(c["duration_ms"], int)


def test_rag_without_answer_is_degraded(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        return {"answer": "", "citations": [{"source": "x.md"}], "has_ai": False,
                "pii_masked": 0, "concepts": []}
    monkeypatch.setattr(ai_vectors, "_rag_impl", _impl)

    r = TestClient(_app()).post("/api/ai/rag", json={"collection": "faq", "question": "why"})
    assert r.status_code == 200
    assert calls[0]["tool"] == "ai.rag" and calls[0]["outcome"] == "degraded"
    assert calls[0]["hit_count"] == 1


def test_failure_is_recorded_as_error_and_reraised(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        raise HTTPException(403, "not a member")
    monkeypatch.setattr(ai_vectors, "_search_impl", _impl)

    r = TestClient(_app()).post("/api/ai/search", json={"collection": "faq", "query": "hi"})
    assert r.status_code == 403
    assert calls[0]["outcome"] == "error" and calls[0]["hit_count"] == 0


def test_request_text_is_the_masked_query(monkeypatch):
    calls = _capture(monkeypatch)

    async def _impl(req, user):
        return {"collection": req.collection, "query": req.query, "pii_masked": 1,
                "concepts": [], "results": []}
    monkeypatch.setattr(ai_vectors, "_search_impl", _impl)
    TestClient(_app()).post("/api/ai/search",
                            json={"collection": "faq", "query": "연락처 010-1234-5678"})
    assert "010-1234-5678" not in calls[0]["request_text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_routes_ai.py -q`
Expected: FAIL — `AttributeError: module 'app.api.ai_vectors' has no attribute '_search_impl'`.

- [ ] **Step 3: Split the handlers and add the wrappers**

In `backend/app/api/ai_vectors.py`, add near the other imports:

```python
import time
from app import tool_call_log
```

Rename the existing `search` (`:1282-1299`) to `_search_impl` and remove its decorator; rename the existing `rag` (`:1302-1379`) to `_rag_impl` and remove its decorator. Keep both bodies byte-for-byte. Then add, directly below `_search_impl`:

```python
def _sources(hits) -> list:
    return [h.get("source") for h in (hits or []) if isinstance(h, dict) and h.get("source")]


async def _logged(tool: str, req_collection: str, masked_text: str, user: dict, impl):
    """Run `impl()`, then record one tool_call_log row describing what it returned.
    Failures are recorded as `error` and re-raised; the log never changes the response."""
    started = time.perf_counter()
    try:
        result = await impl()
    except Exception:
        await tool_call_log.record(
            actor=user, tool=tool, resource_kind="collection", resource=[req_collection],
            request_text=masked_text, outcome="error",
            duration_ms=int((time.perf_counter() - started) * 1000))
        raise
    hits = result.get("results") if tool == "ai.search" else result.get("citations")
    outcome = "degraded" if (tool == "ai.rag" and not result.get("has_ai")) else "ok"
    await tool_call_log.record(
        actor=user, tool=tool, resource_kind="collection", resource=[req_collection],
        request_text=masked_text, hit_count=len(hits or []),
        citation_sources=_sources(hits), pii_masked=int(result.get("pii_masked") or 0),
        outcome=outcome, duration_ms=int((time.perf_counter() - started) * 1000))
    return result


@router.post("/ai/search", dependencies=[Depends(require_permission("ai:generate"))])
async def search(req: SearchRequest, user: dict = Depends(require_user)):
    masked, _, _ = _guard(req.query)
    return await _logged("ai.search", req.collection, masked, user,
                         lambda: _search_impl(req, user))


@router.post("/ai/rag", dependencies=[Depends(require_permission("ai:generate"))])
async def rag(req: RagRequest, user: dict = Depends(require_user)):
    masked, _, _ = _guard(req.question)
    return await _logged("ai.rag", req.collection, masked, user,
                         lambda: _rag_impl(req, user))
```

`_guard` is the existing helper the handlers already call (returns `(masked_text, findings, blocked)`); calling it twice is a pure regex pass and keeps the wrapper free of guard-mode logic.

- [ ] **Step 4: Run the new test and the existing vector suites**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_routes_ai.py tests/test_knowledge_lifecycle_roles.py tests/test_rag_ingest.py tests/test_security_boundaries.py tests/test_route_authorization_inventory.py -q`
Expected: PASS. Existing tests that patch `ai_vectors._retrieve` still pass because `_search_impl`/`_rag_impl` call it as before.

- [ ] **Step 5: Confirm the chat executors still resolve**

Run: `cd backend && python3.12 -m pytest tests -q -k "chat and knowledge"`
Expected: PASS — `app/chat/analysis/knowledge.py` calls `ai_vectors.search(...)`/`rag(...)` which are now the wrappers.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ai_vectors.py backend/tests/test_tool_call_log_routes_ai.py
git commit -m "feat(audit): every /ai/search and /ai/rag call leaves a tool_call_log row"
```

---

### Task 4: Log `/ai/sql`

**Files:**
- Modify: `backend/app/api/ai_sql.py:374-376` (`generate_sql`)
- Test: `backend/tests/test_tool_call_log_routes_sql.py`

**Interfaces:**
- Produces: `_generate_sql_impl(req, user) -> AskResponse`; public `generate_sql` unchanged in name/signature/decorator.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tool_call_log_routes_sql.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import ai_sql, auth

_REAL_REQUIRE_USER = auth.require_user
USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "eng", "role": "ai_engineer"}


def _app():
    app = FastAPI()
    app.include_router(ai_sql.router, prefix="/api")

    async def _override():
        return USER
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


def test_generate_sql_records_generation_only(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(req, user):
        return ai_sql.AskResponse(sql="SELECT 1", explanation="", has_ai=True,
                                  provider="litellm", pii_masked=1)
    monkeypatch.setattr(ai_sql, "_generate_sql_impl", _impl)

    r = TestClient(_app()).post("/api/ai/sql", json={"question": "count orders"})
    assert r.status_code == 200
    c = calls[0]
    assert c["tool"] == "ai.sql" and c["resource_kind"] == "none" and c["resource"] == []
    assert c["hit_count"] == 0 and c["pii_masked"] == 1 and c["outcome"] == "ok"


def test_generate_sql_without_backend_is_degraded(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(req, user):
        return ai_sql.AskResponse(sql="-- no backend", explanation="", has_ai=False,
                                  provider="none", pii_masked=0)
    monkeypatch.setattr(ai_sql, "_generate_sql_impl", _impl)
    TestClient(_app()).post("/api/ai/sql", json={"question": "count orders"})
    assert calls[0]["outcome"] == "degraded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_routes_sql.py -q`
Expected: FAIL with `AttributeError ... '_generate_sql_impl'`.

- [ ] **Step 3: Split and wrap**

In `backend/app/api/ai_sql.py`: add `import time` and `from app import tool_call_log`. Rename `generate_sql` (`:374`) to `_generate_sql_impl`, drop its decorator, keep the body. Add below it:

```python
@router.post("/ai/sql", response_model=AskResponse,
             dependencies=[Depends(require_permission("ai:generate"))])
async def generate_sql(req: AskRequest, user: dict = Depends(require_user)):
    """Convert a natural language question to a SQL query, and log that it happened."""
    from app.guardrails import pii_ko
    masked_question = pii_ko.apply(req.question or "")[0]
    started = time.perf_counter()
    try:
        resp = await _generate_sql_impl(req, user)
    except Exception:
        await tool_call_log.record(actor=user, tool="ai.sql", resource_kind="none",
                                   resource=[], request_text=masked_question,
                                   outcome="error",
                                   duration_ms=int((time.perf_counter() - started) * 1000))
        raise
    await tool_call_log.record(actor=user, tool="ai.sql", resource_kind="none",
                               resource=[], request_text=masked_question,
                               pii_masked=int(resp.pii_masked or 0),
                               outcome="ok" if resp.has_ai else "degraded",
                               duration_ms=int((time.perf_counter() - started) * 1000))
    return resp
```

`pii_ko.apply(text)` returns `(masked_text, findings, blocked)` — the same tuple `ai_vectors._guard` (`ai_vectors.py:1133-1137`) passes through — so `[0]` is the masked text.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_routes_sql.py tests -q -k "ai_sql or sql_parser or salvage"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_sql.py backend/tests/test_tool_call_log_routes_sql.py
git commit -m "feat(audit): every /ai/sql generation leaves a tool_call_log row"
```

---

### Task 5: Log `/queries/execute` with the table names as written

**Files:**
- Modify: `backend/app/api/queries.py:199-364` (`execute_query`)
- Test: `backend/tests/test_tool_call_log_routes_query.py`

**Interfaces:**
- Consumes: `tool_call_log.table_names(sql)` from Task 2.
- Produces: `_execute_query_impl(request, db, user) -> QueryResult`; public `execute_query` unchanged.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tool_call_log_routes_query.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tool_call_log
from app.api import auth, queries
from app.schemas.query import QueryResult

_REAL_REQUIRE_USER = auth.require_user
USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "ana",
        "role": "business_analyst"}


def _app():
    app = FastAPI()
    app.include_router(queries.router, prefix="/api")

    async def _override():
        return USER
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    app.dependency_overrides[queries.get_db] = lambda: None
    return app


def test_execute_records_tables_and_row_count(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(request, db, user):
        return QueryResult(columns=["n"], rows=[[1], [2]], execution_time_ms=3.0,
                           row_count=2, truncated=False)
    monkeypatch.setattr(queries, "_execute_query_impl", _impl)

    r = TestClient(_app()).post("/api/queries/execute",
                                json={"query": "SELECT count(*) FROM sales.orders",
                                      "save_history": False})
    assert r.status_code == 200
    c = calls[0]
    assert c["tool"] == "query.execute" and c["resource_kind"] == "tables"
    assert c["resource"] == ["sales.orders"] and c["hit_count"] == 2
    assert c["outcome"] == "ok"


def test_save_history_false_does_not_skip_the_log(monkeypatch):
    calls = []

    async def _record(**kw):
        calls.append(kw)
    monkeypatch.setattr(tool_call_log, "record", _record)

    async def _impl(request, db, user):
        return QueryResult(columns=[], rows=[], execution_time_ms=1.0, row_count=0,
                           truncated=False)
    monkeypatch.setattr(queries, "_execute_query_impl", _impl)
    TestClient(_app()).post("/api/queries/execute",
                            json={"query": "SELECT 1", "save_history": False})
    assert len(calls) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_routes_query.py -q`
Expected: FAIL with `AttributeError ... '_execute_query_impl'`.

- [ ] **Step 3: Split and wrap**

In `backend/app/api/queries.py`: add `from app import tool_call_log` (`time` is already imported). Rename `execute_query` (`:200`) to `_execute_query_impl`, drop its decorator, keep the body and its `db: Session = Depends(get_db)` default (harmless on a plain function). Add below it:

```python
@router.post("/queries/execute", response_model=QueryResult,
             dependencies=[Depends(require_permission("query:run"))])
async def execute_query(
    request: QueryExecuteRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_user),
):
    from app.guardrails import pii_ko
    masked_sql = pii_ko.apply(request.query or "")[0]
    tables = tool_call_log.table_names(request.query or "")
    started = time.perf_counter()
    try:
        result = await _execute_query_impl(request, db, user)
    except Exception:
        await tool_call_log.record(actor=user, tool="query.execute", resource_kind="tables",
                                   resource=tables, request_text=masked_sql,
                                   outcome="error",
                                   duration_ms=int((time.perf_counter() - started) * 1000))
        raise
    await tool_call_log.record(actor=user, tool="query.execute", resource_kind="tables",
                               resource=tables, request_text=masked_sql,
                               hit_count=int(result.row_count or 0), outcome="ok",
                               duration_ms=int((time.perf_counter() - started) * 1000))
    return result
```

`pii_ko.apply(text)[0]` is the masked text, as in Task 4.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_routes_query.py tests -q -k "quer or sql_kind or rls"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/queries.py backend/tests/test_tool_call_log_routes_query.py
git commit -m "feat(audit): every /queries/execute leaves a tool_call_log row, save_history or not"
```

---

### Task 6: Retention prune and NDJSON export streaming

**Files:**
- Modify: `backend/app/audit_retention.py` (`prune` at `:110`, add row serializer and export SQL + stream)
- Test: `backend/tests/test_tool_call_log_export.py`

**Interfaces:**
- Produces: `tool_call_row_to_json(row: dict) -> str`, `stream_tool_call_export(pool, since, until, page_size=_DEFAULT_PAGE_SIZE) -> AsyncIterator[str]`; `prune()` result gains key `"tool_call_log"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tool_call_log_export.py
import asyncio
import json
from datetime import datetime, timezone

from app import audit_retention as ar


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_prune_calls_the_sanctioned_function_only():
    import inspect
    src = inspect.getsource(ar.prune)
    assert "prune_tool_call_log($1)" in src
    assert "DELETE" not in src.upper().replace("PRUNE_", "")


def test_row_to_json_is_one_line_with_all_fields():
    row = {"id": 7, "occurred_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
           "actor_id": "11111111-1111-1111-1111-111111111111", "actor_username": "svc-bot",
           "actor_kind": "service", "tool": "ai.rag", "resource_kind": "collection",
           "resource": ["faq"], "request_hash": "abc", "request_masked": "q",
           "hit_count": 3, "citation_sources": ["a.md"], "pii_masked": 1,
           "outcome": "ok", "duration_ms": 12, "client_address": None, "via": "api"}
    line = ar.tool_call_row_to_json(row)
    assert "\n" not in line
    d = json.loads(line)
    assert d["tool"] == "ai.rag" and d["resource"] == ["faq"] and d["occurred_at"].startswith("2026-09-07")


class _Conn:
    def __init__(self, pages):
        self._pages = list(pages)

    async def fetch(self, sql, *args):
        return self._pages.pop(0) if self._pages else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


def _row(i):
    return {"id": i, "occurred_at": datetime(2026, 9, 7, i, tzinfo=timezone.utc),
            "actor_id": None, "actor_username": "u", "actor_kind": "human",
            "tool": "ai.search", "resource_kind": "collection", "resource": ["c"],
            "request_hash": "h", "request_masked": "q", "hit_count": 1,
            "citation_sources": [], "pii_masked": 0, "outcome": "ok",
            "duration_ms": 1, "client_address": None, "via": "api"}


def test_stream_pages_until_short_page():
    pool = _Pool(_Conn([[_row(1), _row(2)], [_row(3)]]))

    async def _collect():
        out = []
        async for line in ar.stream_tool_call_export(
                pool, datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 12, 31, tzinfo=timezone.utc), page_size=2):
            out.append(line)
        return out
    lines = _run(_collect())
    assert len(lines) == 3 and all(l.endswith("\n") for l in lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_export.py -q`
Expected: FAIL with `AttributeError: ... 'tool_call_row_to_json'`.

- [ ] **Step 3: Implement in `audit_retention.py`**

Extend `prune` (`:110`) so its returned dict has a third key. Following the two existing `SELECT prune_*($1)` calls at `:106-107`, add a constant and a call:

```python
_PRUNE_TOOL_CALL_SQL = "SELECT prune_tool_call_log($1)"
```

and inside `prune`, after the `auth_audit_log` count, `result["tool_call_log"] = await conn.fetchval(_PRUNE_TOOL_CALL_SQL, cutoff)` (match how the existing two counts are fetched and keyed).

Add the serializer and stream after `stream_security_audit_export` (`:209`):

```python
_TOOL_COLUMNS = ("id, occurred_at, actor_id::text AS actor_id, actor_username, actor_kind, "
                 "tool, resource_kind, resource, request_hash, request_masked, hit_count, "
                 "citation_sources, pii_masked, outcome, duration_ms, client_address, via")

_TOOL_EXPORT_FIRST_PAGE_SQL = f"""
SELECT {_TOOL_COLUMNS} FROM public.tool_call_log
 WHERE occurred_at >= $1 AND occurred_at <= $2
 ORDER BY occurred_at ASC, id ASC
 LIMIT $3
"""

_TOOL_EXPORT_NEXT_PAGE_SQL = f"""
SELECT {_TOOL_COLUMNS} FROM public.tool_call_log
 WHERE occurred_at >= $1 AND occurred_at <= $2
   AND (occurred_at, id) > ($4, $5)
 ORDER BY occurred_at ASC, id ASC
 LIMIT $3
"""


def tool_call_row_to_json(row: dict) -> str:
    d = dict(row)
    ts = d.get("occurred_at")
    d["occurred_at"] = ts.isoformat() if hasattr(ts, "isoformat") else ts
    d["resource"] = list(d.get("resource") or [])
    d["citation_sources"] = list(d.get("citation_sources") or [])
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


async def stream_tool_call_export(pool, since: datetime, until: datetime,
                                  page_size: int = _DEFAULT_PAGE_SIZE) -> AsyncIterator[str]:
    """tool_call_log rows in [since, until], oldest first, one JSON object per line.
    Keyset-paged on (occurred_at, id); a connection is held only per page."""
    last = None
    while True:
        async with pool.acquire() as conn:
            if last is None:
                rows = await conn.fetch(_TOOL_EXPORT_FIRST_PAGE_SQL, since, until, page_size)
            else:
                rows = await conn.fetch(_TOOL_EXPORT_NEXT_PAGE_SQL, since, until,
                                        page_size, last[0], last[1])
        for r in rows:
            d = dict(r)
            yield tool_call_row_to_json(d) + "\n"
            last = (d["occurred_at"], d["id"])
        if len(rows) < page_size:
            return
```

`json`, `datetime`, `AsyncIterator`, `_DEFAULT_PAGE_SIZE` already exist in the module; add any missing import at the top.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_log_export.py tests -q -k "retention or audit_export"`
Expected: PASS. If an existing retention test asserts the exact set of keys `prune` returns, add `"tool_call_log"` to its expectation.

- [ ] **Step 5: Commit**

```bash
git add backend/app/audit_retention.py backend/tests/test_tool_call_log_export.py
git commit -m "feat(audit): tool_call_log joins retention and gains a keyset NDJSON stream"
```

---

### Task 7: Read routes — list, per-actor summary, export

**Files:**
- Create: `backend/app/api/tool_call_routes.py`
- Modify: `backend/main.py:48,398` (import and include the router beside `audit_export_router`)
- Test: `backend/tests/test_tool_call_routes.py`

**Interfaces:**
- Produces:
  - `GET /api/audit/tool-calls?since&until&actor_id&tool&limit=200&offset=0` → `{"rows": [...], "total": int, "capped": bool}` — `audit:read`
  - `GET /api/audit/tool-calls/summary?since&until` → `{"by_actor": [{actor_id, actor_username, actor_kind, calls, ok, degraded, error, collections: [...], tables: [...], hits, pii_masked}]}` — `audit:read`
  - `GET /api/audit/tool-calls/export?since&until` → NDJSON stream — `audit:read`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tool_call_routes.py
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, tool_call_routes

_REAL_REQUIRE_USER = auth.require_user
AUDITOR = {"id": "33333333-3333-3333-3333-333333333333", "username": "aud", "role": "auditor",
           "permissions": {"audit:read"}}


def _app():
    app = FastAPI()
    app.include_router(tool_call_routes.router, prefix="/api")

    async def _override():
        return AUDITOR
    app.dependency_overrides[_REAL_REQUIRE_USER] = _override
    return app


class _Conn:
    def __init__(self, rows, total):
        self.rows, self.total, self.sql = rows, total, []

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return self.rows

    async def fetchval(self, sql, *args):
        return self.total

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _patch(monkeypatch, conn):
    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(tool_call_routes, "get_db_pool", _pool)


def _row():
    return {"id": 1, "occurred_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
            "actor_id": "22222222-2222-2222-2222-222222222222", "actor_username": "svc-bot",
            "actor_kind": "service", "tool": "ai.rag", "resource_kind": "collection",
            "resource": ["faq"], "request_hash": "h", "request_masked": "q", "hit_count": 2,
            "citation_sources": ["a.md"], "pii_masked": 1, "outcome": "ok",
            "duration_ms": 5, "client_address": None, "via": "api"}


def test_list_requires_tz_aware_window(monkeypatch):
    _patch(monkeypatch, _Conn([], 0))
    r = TestClient(_app()).get("/api/audit/tool-calls?since=2026-09-01T00:00:00")
    assert r.status_code == 400


def test_list_returns_rows_total_capped(monkeypatch):
    _patch(monkeypatch, _Conn([_row()], 250))
    r = TestClient(_app()).get("/api/audit/tool-calls?limit=1")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 250 and d["capped"] is True and d["rows"][0]["tool"] == "ai.rag"


def test_summary_groups_by_actor(monkeypatch):
    conn = _Conn([{"actor_id": "2", "actor_username": "svc-bot", "actor_kind": "service",
                   "calls": 3, "ok": 2, "degraded": 1, "error": 0,
                   "collections": ["faq"], "tables": [], "hits": 5, "pii_masked": 1}], 0)
    _patch(monkeypatch, conn)
    r = TestClient(_app()).get("/api/audit/tool-calls/summary")
    assert r.status_code == 200
    assert r.json()["by_actor"][0]["actor_username"] == "svc-bot"
    assert "GROUP BY" in conn.sql[0]


def test_export_streams_ndjson(monkeypatch):
    _patch(monkeypatch, _Conn([_row()], 0))
    r = TestClient(_app()).get("/api/audit/tool-calls/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert r.text.count("\n") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_routes.py -q`
Expected: FAIL with `ImportError: cannot import name 'tool_call_routes'`.

- [ ] **Step 3: Implement the router**

```python
# backend/app/api/tool_call_routes.py
"""Read side of the tool call log: a paged list, a per-actor summary, and an NDJSON
export. All three answer 'which caller read what' — the question the compliance
reviewer asks and security_audit_log cannot answer."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.auth import require_permission
from app.api.connectors import get_db_pool
from app.audit_retention import (retention_days, stream_tool_call_export,
                                 tool_call_row_to_json, utcnow)
from app.tool_call_log import TOOLS

router = APIRouter(dependencies=[Depends(require_permission("audit:read"))])

_MAX_LIMIT = 200

_LIST_COLUMNS = ("id, occurred_at, actor_id::text AS actor_id, actor_username, actor_kind, "
                 "tool, resource_kind, resource, request_hash, request_masked, hit_count, "
                 "citation_sources, pii_masked, outcome, duration_ms, client_address, via")

_SUMMARY_SQL = """
SELECT actor_id::text AS actor_id, actor_username, actor_kind,
       count(*)                                    AS calls,
       count(*) FILTER (WHERE outcome = 'ok')       AS ok,
       count(*) FILTER (WHERE outcome = 'degraded') AS degraded,
       count(*) FILTER (WHERE outcome = 'error')    AS error,
       array_remove(array_agg(DISTINCT r) FILTER (WHERE resource_kind = 'collection'), NULL) AS collections,
       array_remove(array_agg(DISTINCT r) FILTER (WHERE resource_kind = 'tables'), NULL)     AS tables,
       coalesce(sum(hit_count), 0)                  AS hits,
       coalesce(sum(pii_masked), 0)                 AS pii_masked
  FROM public.tool_call_log t
  LEFT JOIN LATERAL unnest(t.resource) AS r ON true
 WHERE occurred_at >= $1 AND occurred_at <= $2
 GROUP BY actor_id, actor_username, actor_kind
 ORDER BY calls DESC
"""


def _window(since: Optional[datetime], until: Optional[datetime]):
    now = utcnow()
    since_ts = since or (now - timedelta(days=retention_days()))
    until_ts = until or now
    for ts in (since_ts, until_ts):
        if ts.tzinfo is None:
            raise HTTPException(status_code=400, detail="since/until must include a timezone")
    if since_ts > until_ts:
        raise HTTPException(status_code=400, detail="since must not be after until")
    return since_ts, until_ts


@router.get("/audit/tool-calls")
async def list_tool_calls(
    since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
    actor_id: Optional[str] = Query(None), tool: Optional[str] = Query(None),
    limit: int = Query(_MAX_LIMIT, ge=1, le=_MAX_LIMIT), offset: int = Query(0, ge=0),
):
    since_ts, until_ts = _window(since, until)
    if tool is not None and tool not in TOOLS:
        raise HTTPException(status_code=400, detail=f"tool must be one of {list(TOOLS)}")
    where = ["occurred_at >= $1", "occurred_at <= $2"]
    args = [since_ts, until_ts]
    if actor_id:
        args.append(actor_id); where.append(f"actor_id::text = ${len(args)}")
    if tool:
        args.append(tool); where.append(f"tool = ${len(args)}")
    clause = " AND ".join(where)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM public.tool_call_log WHERE {clause}", *args)
        rows = await conn.fetch(
            f"SELECT {_LIST_COLUMNS} FROM public.tool_call_log WHERE {clause} "
            f"ORDER BY occurred_at DESC, id DESC LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}",
            *args, limit, offset)
    out = []
    for r in rows:
        d = dict(r)
        d["occurred_at"] = d["occurred_at"].isoformat()
        d["resource"] = list(d.get("resource") or [])
        d["citation_sources"] = list(d.get("citation_sources") or [])
        out.append(d)
    return {"rows": out, "total": int(total or 0), "capped": int(total or 0) > offset + len(out)}


@router.get("/audit/tool-calls/summary")
async def summarize_tool_calls(
    since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
):
    since_ts, until_ts = _window(since, until)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SUMMARY_SQL, since_ts, until_ts)
    by_actor = []
    for r in rows:
        d = dict(r)
        d["collections"] = list(d.get("collections") or [])
        d["tables"] = list(d.get("tables") or [])
        by_actor.append(d)
    return {"since": since_ts.isoformat(), "until": until_ts.isoformat(), "by_actor": by_actor}


@router.get("/audit/tool-calls/export")
async def export_tool_calls(
    since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
):
    since_ts, until_ts = _window(since, until)
    pool = await get_db_pool()
    return StreamingResponse(
        stream_tool_call_export(pool, since_ts, until_ts),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="tool-call-log.ndjson"'},
    )
```

`utcnow` is defined in `app/audit_retention.py:99`.

- [ ] **Step 4: Register the router**

In `backend/main.py`, next to line 48:

```python
from app.api.tool_call_routes import router as tool_call_router
```

and next to line 398:

```python
app.include_router(tool_call_router, prefix="/api")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_tool_call_routes.py tests/test_route_authorization_inventory.py tests/test_app_imports.py -q`
Expected: PASS (if `test_app_imports.py` does not exist, run `python3.12 -c "import main"` from `backend/` instead and expect no error).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/tool_call_routes.py backend/main.py backend/tests/test_tool_call_routes.py
git commit -m "feat(audit): list, per-actor summary and NDJSON export of tool calls"
```

---

### Task 8: Chat — mark executor calls `via='chat'`, add tool-call counts to `audit.activity_summary`

**Files:**
- Modify: `backend/app/chat/gate.py:298-320` (`_execute`)
- Modify: `backend/app/chat/analysis/audit.py:26-68`
- Modify: `backend/tests/test_chat_audit_aggregate.py` (extend the SQL-text check to the new constant)
- Test: `backend/tests/test_chat_tool_call_via.py`

**Interfaces:**
- Consumes: `tool_call_log.via`, `tool_call_log.current_via` (Task 2).
- Produces: `activity_summary` result gains `"tool_calls": {"totals": {...}, "by_tool": [...]}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_chat_tool_call_via.py
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
        execute = staticmethod(_exec)

    class _Store:
        async def update(self, *a, **kw):
            return {"status": "executed"}

        async def record_audit(self, *a, **kw):
            return None

    async def _audit(*a, **kw):
        return None
    monkeypatch.setattr(gate, "_audit", _audit)
    _run(gate._execute(_Store(), _Action(), {"id": "inv-1", "params": {}},
                       {"id": "u", "username": "u", "role": "ai_engineer"}))
    assert seen["via"] == "chat"
```

Match `_execute`'s real parameter order from `gate.py:298` when writing the call above (store, action, invocation, user or whichever it is); the assertion is what matters.

Extend `backend/tests/test_chat_audit_aggregate.py`: wherever it reads `audit._SUMMARY_SQL` and asserts every selected column is a category or a count, apply the same assertion to `audit._TOOL_SUMMARY_SQL`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3.12 -m pytest tests/test_chat_tool_call_via.py tests/test_chat_audit_aggregate.py -q`
Expected: FAIL — `seen["via"] == "api"`, and `AttributeError ... '_TOOL_SUMMARY_SQL'`.

- [ ] **Step 3: Wrap `_execute`**

In `backend/app/chat/gate.py`, import `from app import tool_call_log` and wrap the line that awaits `action.execute(...)` inside `_execute` (`:298-320`):

```python
    with tool_call_log.via("chat"):
        result = await action.execute(invocation["params"], user)
```

Keep everything else in `_execute` unchanged.

- [ ] **Step 4: Add tool-call aggregates to `activity_summary`**

In `backend/app/chat/analysis/audit.py`, add beside `_SUMMARY_SQL` (`:26-36`):

```python
# Same constraint as _SUMMARY_SQL, enforced by tests/test_chat_audit_aggregate.py:
# categories and counts only. No actor, no resource, no request text.
_TOOL_SUMMARY_SQL = """
    SELECT tool, outcome, date_trunc('day', occurred_at)::date AS day, count(*) AS n
      FROM public.tool_call_log
     WHERE occurred_at >= now() - ($1::int * interval '1 day')
     GROUP BY tool, outcome, day
     ORDER BY day
"""
```

In `activity_summary` (`:38`), after fetching the existing rows, fetch `tool_rows = await conn.fetch(_TOOL_SUMMARY_SQL, params["days"])` on the same connection and add to the returned dict:

```python
        "tool_calls": {
            "totals": {o: sum(int(r["n"]) for r in tool_rows if r["outcome"] == o)
                       for o in ("ok", "degraded", "error")},
            "by_tool": [{"tool": r["tool"], "outcome": r["outcome"],
                         "day": r["day"].isoformat(), "n": int(r["n"])} for r in tool_rows],
        },
```

Update the action's `description` string in the same file so the model knows the summary now includes data-tool calls (search, answers, SQL) by day and outcome.

- [ ] **Step 5: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_chat_tool_call_via.py tests/test_chat_audit_aggregate.py tests -q -k chat`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/gate.py backend/app/chat/analysis/audit.py backend/tests/test_chat_tool_call_via.py backend/tests/test_chat_audit_aggregate.py
git commit -m "feat(chat): executor calls are logged via=chat; activity summary counts tool calls"
```

---

### Task 9: Compliance report — fourth section "Agent tool calls"

**Files:**
- Create: `frontend/lib/compliance-report.ts`
- Test: `frontend/lib/compliance-report.test.ts`
- Modify: `frontend/app/governance/page.tsx:824-828` (state), `:837-895` (`exportReport`), `:1526-1530` (checkbox list)

**Interfaces:**
- Consumes: `GET /api/audit/tool-calls?since&until&limit=200`, `GET /api/audit/tool-calls/summary?since&until` (Task 7).
- Produces: `buildToolCallSection(list: {rows, total, capped}, summary: {by_actor}) -> ToolCallSection`; report JSON gains `sections.agent_tool_calls`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/compliance-report.test.ts
import assert from "node:assert/strict"
import { test } from "node:test"
import { buildToolCallSection, windowParams } from "./compliance-report.ts"

test("windowParams turns date inputs into tz-aware ISO bounds", () => {
  const p = windowParams("2026-09-01", "2026-09-07")
  assert.equal(p.get("since"), new Date("2026-09-01T00:00:00").toISOString())
  assert.equal(p.get("until"), new Date("2026-09-07T23:59:59").toISOString())
  assert.equal(windowParams("", "").has("since"), false)
})

test("buildToolCallSection carries totals, capped flag and per-actor rows", () => {
  const s = buildToolCallSection(
    { rows: [{ tool: "ai.rag", outcome: "ok" }], total: 300, capped: true },
    { by_actor: [{ actor_username: "svc-bot", actor_kind: "service", calls: 3,
                   ok: 3, degraded: 0, error: 0, collections: ["faq"], tables: [],
                   hits: 9, pii_masked: 2 }] },
  )
  assert.equal(s.total_available, 300)
  assert.equal(s.returned, 1)
  assert.equal(s.capped, true)
  assert.equal(s.by_actor[0].actor_username, "svc-bot")
  assert.equal(s.by_actor[0].collections[0], "faq")
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot find module `./compliance-report.ts`.

- [ ] **Step 3: Implement the lib module**

```ts
// frontend/lib/compliance-report.ts
// Pure pieces of the governance compliance report, kept out of the page so they can be
// tested with node --test (see collection-members.ts for the same split).

export type ToolCallRow = Record<string, unknown>
export type ToolCallActor = {
  actor_id?: string | null; actor_username: string; actor_kind: string
  calls: number; ok: number; degraded: number; error: number
  collections: string[]; tables: string[]; hits: number; pii_masked: number
}
export type ToolCallSection = {
  total_available: number; returned: number; capped: boolean
  by_actor: ToolCallActor[]; rows: ToolCallRow[]
}

/** since/until query params for the audit endpoints; empty inputs mean "open". */
export function windowParams(from: string, to: string): URLSearchParams {
  const p = new URLSearchParams()
  if (from) p.set("since", new Date(`${from}T00:00:00`).toISOString())
  if (to) p.set("until", new Date(`${to}T23:59:59`).toISOString())
  return p
}

export function buildToolCallSection(
  list: { rows: ToolCallRow[]; total: number; capped: boolean },
  summary: { by_actor: ToolCallActor[] },
): ToolCallSection {
  return {
    total_available: list.total,
    returned: list.rows.length,
    capped: list.capped,
    by_actor: summary.by_actor,
    rows: list.rows,
  }
}
```

- [ ] **Step 4: Wire the page**

In `frontend/app/governance/page.tsx`:

1. Import at the top: `import { buildToolCallSection, windowParams } from "@/lib/compliance-report"`.
2. State (`:824-828`): add `toolCalls: true` to the `reportChecks` initial object.
3. Inside `exportReport`, after the `reportChecks.pii` block and before the empty-sections check, add:

```tsx
      if (reportChecks.toolCalls) {
        const qs = windowParams(reportFrom, reportTo)
        qs.set("limit", String(AUDIT_LIMIT))
        const [lr, sr] = await Promise.all([
          fetch(`/api/audit/tool-calls?${qs}`),
          fetch(`/api/audit/tool-calls/summary?${windowParams(reportFrom, reportTo)}`),
        ])
        if (!lr.ok) throw new Error(`tool-calls HTTP ${lr.status}`)
        if (!sr.ok) throw new Error(`tool-calls summary HTTP ${sr.status}`)
        sections.agent_tool_calls = buildToolCallSection(await lr.json(), await sr.json())
      }
```

4. Update the `note` string in the report object to: `"AI-SQL safety and PII sections are current snapshots; the query audit log and agent tool calls are time-scoped per event."`
5. Checkbox list (`:1526-1530`): add `{ key: "toolCalls", label: "Agent tool calls (search, cited answers, SQL) by caller" }` after the `pii` entry.

- [ ] **Step 5: Run tests, lint and build**

Run: `cd frontend && npm test && npm run lint && npm run build`
Expected: tests PASS, lint 0 errors, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/compliance-report.ts frontend/lib/compliance-report.test.ts frontend/app/governance/page.tsx
git commit -m "feat(governance): compliance report includes agent tool calls by caller"
```

---

### Task 10: Documents — upgrade note, README status, audit rows

**Files:**
- Modify: `docs/UPGRADING.md` (new entry at the top)
- Modify: `README.md` (move "Audit records for successful … calls" from Roadmap to Shipped)
- Modify: `docs/PRODUCT_CONCEPT.md` (핵심 가치 1: move the audit bullet from "아직 아닌 것" to "현재 구현된 것"; 거버넌스 경계: "성공한 읽기 호출의 내용 기록은 roadmap이다" → shipped)
- Modify: `docs/POSITIONING_FIT_AUDIT.md` §7.1 axis B/C rows for "성공한 검색·답변의 감사 기록", "인용·마스킹 수의 영속", "컴플라이언스 리포트 … 에이전트 호출" → ○ with the new file paths as evidence

- [ ] **Step 1: Write the upgrade note**

Add at the top of the changelog section in `docs/UPGRADING.md`:

```markdown
### tool_call_log (migration 0008)

Every successful `/api/ai/search`, `/api/ai/rag`, `/api/ai/sql` and `/api/queries/execute`
call now writes one row to `public.tool_call_log` (who, which tool, which collection or
tables, hit count, cited sources, PII masked). The row is written after PII masking and is
append-only under the same trigger as the security audit log. `save_history=false` no
longer hides a query from the audit trail — it only controls the user-facing history.
Retention: same window as `AUDIT_RETENTION_DAYS`. New read endpoints under
`/api/audit/tool-calls` (`audit:read`). The governance compliance report gains an
"Agent tool calls" section. Expect one extra INSERT per tool call.
```

- [ ] **Step 2: Flip the status lines**

- `README.md`: delete the roadmap bullet `- Audit records for successful …` and add under **Shipped**: `- Append-only tool call log: who called search, cited answers, SQL generation or query execution, against which collection or tables, with hit count, cited sources and PII masked; NDJSON export and compliance-report section`.
- `docs/PRODUCT_CONCEPT.md`: move `성공한 /ai/search·/ai/rag·/ai/sql 호출의 감사 기록…` into the 현재 구현된 것 list as `- 성공한 search·rag·sql·query 호출의 append-only 도구 호출 감사(호출자, 컬렉션·테이블, hit 수, 인용 source, 마스킹 수), NDJSON export`; change the 거버넌스 경계 bullet to `- 감사는 권한 결정과 도구 호출 두 축이다. 둘 다 append-only이며 WORM은 아니다.`
- `docs/POSITIONING_FIT_AUDIT.md` §7.1: flip the three rows named above to ○, citing `backend/app/tool_call_log.py`, `backend/app/api/tool_call_routes.py`, `frontend/lib/compliance-report.ts`.

- [ ] **Step 3: Full backend and frontend check**

Run: `cd backend && python3.12 -m pytest tests -q --ignore=tests/acceptance && cd ../frontend && npm test && npm run lint`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add docs/UPGRADING.md README.md docs/PRODUCT_CONCEPT.md docs/POSITIONING_FIT_AUDIT.md
git commit -m "docs: tool call log is shipped — upgrade note, README, concept, fit audit"
```
