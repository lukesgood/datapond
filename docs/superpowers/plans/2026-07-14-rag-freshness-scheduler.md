# RAG Freshness Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RAG collections automatic, Airflow-free periodic re-embedding via a backend in-process scheduler, with replace (not append) semantics.

**Architecture:** New schedule columns on `ai_collections` hold a saved source + interval. A single asyncio loop started at backend startup wakes every N seconds, takes a Postgres advisory lock (so only one of the backend replicas runs a tick), selects overdue collections, and re-embeds them in-process by reusing the existing source-read + ingest code. A new `ai_chunks.source_group` column lets re-embedding delete-then-insert a logical source without duplicating chunks or clobbering other sources.

**Tech Stack:** Python 3.11, FastAPI, asyncpg (Postgres/Aurora + pgvector), pytest. Spec: `docs/superpowers/specs/2026-07-14-rag-freshness-scheduler-design.md`.

## Global Constraints

- Interval-based only (`refresh_interval_minutes: int`), no cron. Legacy Airflow presets map: `@hourly`→60, `@daily`→1440, `@weekly`→10080.
- The Airflow-DAG path is **removed**: delete `_generate_ingest_dag`, the `DAGS_PATH` write in the schedule endpoint, and the `schedule: str` Airflow-preset field's DAG behavior. `schedule_ingest` now persists to DB columns.
- Replace semantics use a new `ai_chunks.source_group` column, NOT the existing per-document `source` column (which stays for citations / `COUNT(DISTINCT source)`).
- The scheduler runs the re-embed **in-process** (no HTTP callback, no `X-Internal-Key`).
- Multi-replica safety via `pg_try_advisory_lock(LOCK_KEY)` where `LOCK_KEY = 0x64617461706F6E64 & 0x7FFFFFFFFFFFFFFF` → use the constant `LOCK_KEY = 7233183143331076964`.
- New schema columns are additive (`ADD COLUMN IF NOT EXISTS`), applied in `ensure_vector_schema(pool)`.
- Config: `RAG_SCHEDULER_ENABLED` (default `"true"`), `RAG_SCHEDULER_TICK_SECONDS` (default `"300"`).
- Tests follow the existing pure-unit style (`backend/tests/test_*.py`, `monkeypatch`, no live DB) — DB-touching logic is tested with a minimal in-file fake asyncpg connection/pool.
- Run tests with: `cd backend && python -m pytest tests/test_rag_scheduler.py tests/test_rag_ingest.py -v` (CI py3.11 is authoritative).

---

## File Structure

- `backend/app/api/ai_vectors.py` (modify) — schema columns; `_source_group`; `_ingest_documents` replace semantics; `_refresh_from_source`; rewrite `schedule_ingest`; add GET/DELETE schedule; `_preset_to_minutes`; remove `_generate_ingest_dag`/`DAGS_PATH`.
- `backend/app/rag_scheduler.py` (create) — `_is_due`, `tick`, `run_scheduler`, `LOCK_KEY`.
- `backend/main.py` (modify) — start the scheduler task in the startup handler.
- `helm/datapond/templates/backend-deployment.yaml` (modify) — `RAG_SCHEDULER_ENABLED` / `RAG_SCHEDULER_TICK_SECONDS` env.
- `helm/datapond/values.yaml` (modify) — `backend.ragScheduler.{enabled,tickSeconds}` defaults.
- `backend/tests/test_rag_ingest.py` (create) — `_source_group`, `_preset_to_minutes`, replace-semantics.
- `backend/tests/test_rag_scheduler.py` (create) — `_is_due`, `tick` advisory-lock + selection.

---

## Task 1: Schema columns (ai_collections schedule + ai_chunks.source_group)

**Files:**
- Modify: `backend/app/api/ai_vectors.py` (function `ensure_vector_schema`, lines 81-116)
- Test: `backend/tests/test_rag_ingest.py` (create)

**Interfaces:**
- Produces: `ensure_vector_schema(pool)` now also creates columns `ai_collections.refresh_source JSONB`, `ai_collections.refresh_interval_minutes INT`, `ai_collections.refresh_enabled BOOLEAN NOT NULL DEFAULT false`, `ai_collections.last_refreshed_at TIMESTAMPTZ`, `ai_collections.last_refresh_status TEXT`, `ai_chunks.source_group TEXT`, and index `ai_chunks_group_idx ON ai_chunks(collection_id, source_group)`.

- [ ] **Step 1: Write the failing test** — a fake pool records every `execute()` SQL string; assert the new DDL is issued.

In `backend/tests/test_rag_ingest.py`:

```python
import asyncio


class _FakeConn:
    def __init__(self, sink): self.sink = sink
    async def execute(self, sql, *a): self.sink.append(sql)
    async def executemany(self, sql, rows): self.sink.append(("many", sql, list(rows)))
    async def fetchrow(self, sql, *a): return None
    async def fetch(self, sql, *a): return []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self): self.sql = []
    def acquire(self): return _FakeConn(self.sql)


def test_ensure_vector_schema_adds_schedule_columns(monkeypatch):
    import app.api.ai_vectors as v
    pool = _FakePool()
    asyncio.get_event_loop().run_until_complete(v.ensure_vector_schema(pool))
    joined = " ".join(pool.sql if isinstance(pool.sql[0], str) else [s if isinstance(s, str) else s[1] for s in pool.sql])
    assert "refresh_source" in joined and "JSONB" in joined.upper()
    assert "refresh_interval_minutes" in joined
    assert "refresh_enabled" in joined
    assert "last_refreshed_at" in joined
    assert "last_refresh_status" in joined
    assert "source_group" in joined
    assert "ai_chunks_group_idx" in joined
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd backend && python -m pytest tests/test_rag_ingest.py::test_ensure_vector_schema_adds_schedule_columns -v`
Expected: FAIL (assert `refresh_source` not present).

- [ ] **Step 3: Add the columns** in `ensure_vector_schema`, immediately after the existing `owner_id` ALTER (line 109) and before the `ai_chunks_coll_idx` index:

```python
            # RAG freshness scheduler: saved source + interval per collection.
            await c.execute("ALTER TABLE ai_collections ADD COLUMN IF NOT EXISTS refresh_source JSONB")
            await c.execute("ALTER TABLE ai_collections ADD COLUMN IF NOT EXISTS refresh_interval_minutes INT")
            await c.execute("ALTER TABLE ai_collections ADD COLUMN IF NOT EXISTS refresh_enabled BOOLEAN NOT NULL DEFAULT false")
            await c.execute("ALTER TABLE ai_collections ADD COLUMN IF NOT EXISTS last_refreshed_at TIMESTAMPTZ")
            await c.execute("ALTER TABLE ai_collections ADD COLUMN IF NOT EXISTS last_refresh_status TEXT")
            # Replace-scope for re-embedding: a logical source group (distinct from
            # per-document `source`, which stays for citations / COUNT(DISTINCT)).
            await c.execute("ALTER TABLE ai_chunks ADD COLUMN IF NOT EXISTS source_group TEXT")
            await c.execute("CREATE INDEX IF NOT EXISTS ai_chunks_group_idx ON ai_chunks(collection_id, source_group)")
```

- [ ] **Step 4: Run the test and make sure it passes**

Run: `cd backend && python -m pytest tests/test_rag_ingest.py::test_ensure_vector_schema_adds_schedule_columns -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_vectors.py backend/tests/test_rag_ingest.py
git commit -m "feat(rag): add schedule columns + ai_chunks.source_group"
```

---

## Task 2: Replace semantics + shared refresh function

**Files:**
- Modify: `backend/app/api/ai_vectors.py` (`_ingest_documents` 286-310; `ingest` 313-324; `ingest_source` 386-414)
- Test: `backend/tests/test_rag_ingest.py`

**Interfaces:**
- Consumes: `_FakeConn`/`_FakePool` from Task 1's test file.
- Produces:
  - `_source_group(src: "SourceIngest") -> str`
  - `_ingest_documents(coll_id, docs, chunk_size, overlap, source_group: Optional[str] = None) -> dict` (new trailing param)
  - `_refresh_from_source(pool, coll_id, src: "SourceIngest") -> dict` returning `{"documents": int, "chunks": int, "pii_masked": int}`

- [ ] **Step 1: Write the failing tests** (pure `_source_group` + replace behavior via fake conn):

```python
def test_source_group_iceberg_and_s3(monkeypatch):
    import app.api.ai_vectors as v
    ice = v.SourceIngest(type="iceberg", schema="sales", table="orders", text_column="note")
    s3 = v.SourceIngest(type="s3", bucket="b", prefix="docs/")
    assert v._source_group(ice) == "iceberg:sales.orders.note"
    assert v._source_group(s3) == "s3:b/docs/"


def test_ingest_documents_replaces_when_group_given(monkeypatch):
    import app.api.ai_vectors as v

    class Conn(_FakeConn):
        def __init__(self, sink): super().__init__(sink)
        def transaction(self):
            outer = self
            class _Tx:
                async def __aenter__(self_): return outer
                async def __aexit__(self_, *a): return False
            return _Tx()

    sink = []
    pool = _FakePool(); pool.acquire = lambda: Conn(sink)
    monkeypatch.setattr(v, "get_db_pool", lambda: _aval(pool))
    monkeypatch.setattr(v, "_embed", lambda texts: _aval([[0.0] for _ in texts]))
    docs = [("s3://b/a.txt", "hello world", {"k": 1})]
    asyncio.get_event_loop().run_until_complete(
        v._ingest_documents("cid", docs, 1000, 150, source_group="s3:b/"))
    dels = [s for s in sink if isinstance(s, str) and s.strip().upper().startswith("DELETE")]
    assert dels and "source_group" in dels[0]


def test_ingest_documents_appends_when_no_group(monkeypatch):
    import app.api.ai_vectors as v
    sink = []
    pool = _FakePool(); pool.acquire = lambda: _FakeConn(sink)
    monkeypatch.setattr(v, "get_db_pool", lambda: _aval(pool))
    monkeypatch.setattr(v, "_embed", lambda texts: _aval([[0.0] for _ in texts]))
    asyncio.get_event_loop().run_until_complete(
        v._ingest_documents("cid", [("s", "text", {})], 1000, 150))
    dels = [s for s in sink if isinstance(s, str) and s.strip().upper().startswith("DELETE")]
    assert not dels
```

Add this helper at the top of `test_rag_ingest.py` (after imports):

```python
def _aval(value):
    async def _coro(): return value
    return _coro()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_rag_ingest.py -k "source_group or replaces or appends" -v`
Expected: FAIL (`_source_group` missing; `_ingest_documents` has no `source_group` param).

- [ ] **Step 3: Implement.** Add `_source_group`, extend `_ingest_documents`, add `_refresh_from_source`, and rewire `ingest`/`ingest_source`.

Replace `_ingest_documents` (286-310) with:

```python
async def _ingest_documents(coll_id, docs: List[tuple], chunk_size: int, overlap: int,
                            source_group: Optional[str] = None) -> dict:
    """docs: list of (source, text, metadata). Chunk → PII-mask → embed → insert.
    When source_group is given, replace (delete-then-insert) all chunks for that
    (collection, source_group) so recurring re-embeds don't duplicate."""
    from app.guardrails import pii_ko
    items = []  # (source, idx, content, metadata_json)
    pii_masked = 0
    for source, text, meta in docs:
        for idx, raw in enumerate(_chunk(text, chunk_size, overlap)):
            masked, found, _blk = pii_ko.apply(raw)
            pii_masked += len(found)
            items.append((source, idx, masked, json.dumps(meta or {})))
    embeddings: List[List[float]] = []
    B = 64
    for i in range(0, len(items), B):
        embeddings.extend(await _embed([it[2] for it in items[i:i + B]]))
    pool = await get_db_pool()
    async with pool.acquire() as c:
        async with c.transaction():
            if source_group is not None:
                await c.execute(
                    "DELETE FROM ai_chunks WHERE collection_id = $1 AND source_group = $2",
                    coll_id, source_group)
            if items:
                await c.executemany(
                    """INSERT INTO ai_chunks (collection_id, source, chunk_index, content, metadata, embedding, source_group)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector, $7)""",
                    [(coll_id, it[0], it[1], it[2], it[3], _vec_literal(emb), source_group)
                     for it, emb in zip(items, embeddings)],
                )
    return {"chunks": len(items), "pii_masked": pii_masked}
```

Add `_source_group` and `_refresh_from_source` just above `ingest_source` (before line 386):

```python
def _source_group(src: "SourceIngest") -> str:
    if src.type == "iceberg":
        return f"iceberg:{src.db_schema}.{src.table}.{src.text_column}"
    return f"s3:{src.bucket}/{src.prefix or ''}"


async def _refresh_from_source(pool, coll_id, src: "SourceIngest") -> dict:
    """Read a source (Iceberg column / S3 prefix) and re-embed it into coll_id with
    replace semantics. Shared by the ingest-source endpoint and the scheduler."""
    if src.type == "iceberg":
        if not (src.db_schema and src.table and src.text_column):
            raise HTTPException(400, "iceberg source needs schema, table, text_column.")
        if not _ident_ok(src.db_schema, src.table, src.text_column):
            raise HTTPException(400, "schema/table/text_column must be bare identifiers.")
        docs = await asyncio.to_thread(_read_iceberg_docs, src.db_schema, src.table,
                                       src.text_column, src.limit)
    elif src.type == "s3":
        if not src.bucket:
            raise HTTPException(400, "s3 source needs bucket (and optional prefix).")
        docs = await asyncio.to_thread(_read_s3_docs, src.bucket, src.prefix, src.max_files)
    else:
        raise HTTPException(400, "type must be 'iceberg' or 's3'.")
    res = await _ingest_documents(coll_id, docs, src.chunk_size, src.chunk_overlap,
                                  source_group=_source_group(src))
    return {"documents": len(docs), **res}
```

Rewrite the body of `ingest_source` (399-414) to use it:

```python
    res = await _refresh_from_source(pool, coll_id, req)
    return {"success": True, **res}
```

(Leave `ingest` at 313-324 unchanged — inline text still calls `_ingest_documents(...)` with no `source_group`, preserving append.)

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && python -m pytest tests/test_rag_ingest.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_vectors.py backend/tests/test_rag_ingest.py
git commit -m "fix(rag): replace-by-source_group; share _refresh_from_source"
```

---

## Task 3: Schedule CRUD endpoints (replace the Airflow-DAG path)

**Files:**
- Modify: `backend/app/api/ai_vectors.py` (`ScheduleRequest` 423-425; `_generate_ingest_dag` 428-454 → delete; `schedule_ingest` 457-471 → rewrite; `DAGS_PATH` 419 → delete)
- Test: `backend/tests/test_rag_ingest.py`

**Interfaces:**
- Consumes: `_source_group`, `_FakePool`/`_FakeConn`.
- Produces:
  - `_preset_to_minutes(schedule: Optional[str], interval_minutes: Optional[int]) -> int`
  - `POST /ai/collections/{name}/schedule` persists `refresh_source`/`refresh_interval_minutes`/`refresh_enabled=true`.
  - `GET /ai/collections/{name}/schedule` and `DELETE /ai/collections/{name}/schedule`.

- [ ] **Step 1: Write the failing test** for the preset mapping (pure):

```python
def test_preset_to_minutes(monkeypatch):
    import app.api.ai_vectors as v
    assert v._preset_to_minutes(None, 90) == 90
    assert v._preset_to_minutes("@hourly", None) == 60
    assert v._preset_to_minutes("@daily", None) == 1440
    assert v._preset_to_minutes("@weekly", None) == 10080
    assert v._preset_to_minutes(None, None) == 1440   # default daily
    import pytest
    with pytest.raises(Exception):
        v._preset_to_minutes(None, 0)                 # must be > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_rag_ingest.py::test_preset_to_minutes -v`
Expected: FAIL (`_preset_to_minutes` missing).

- [ ] **Step 3: Implement.** Delete `DAGS_PATH` (419) and the whole `_generate_ingest_dag` function (428-454). Change `ScheduleRequest` to:

```python
class ScheduleRequest(BaseModel):
    interval_minutes: Optional[int] = None
    schedule: Optional[str] = None      # legacy Airflow preset (@hourly/@daily/@weekly)
    source: SourceIngest
```

Add `_preset_to_minutes` above `schedule_ingest`:

```python
_PRESETS = {"@hourly": 60, "@daily": 1440, "@weekly": 10080}

def _preset_to_minutes(schedule: Optional[str], interval_minutes: Optional[int]) -> int:
    if interval_minutes is not None:
        if interval_minutes <= 0:
            raise HTTPException(400, "interval_minutes must be > 0.")
        return interval_minutes
    if schedule:
        if schedule not in _PRESETS:
            raise HTTPException(400, f"unknown schedule preset '{schedule}'.")
        return _PRESETS[schedule]
    return 1440  # default: daily
```

Rewrite `schedule_ingest` (457-471) and add GET/DELETE:

```python
@router.post("/ai/collections/{name}/schedule")
async def schedule_ingest(name: str, body: ScheduleRequest, user: dict = Depends(require_user)):
    """Save a recurring re-embed schedule for this collection. The backend
    in-process scheduler (rag_scheduler) runs due collections — no Airflow."""
    minutes = _preset_to_minutes(body.schedule, body.interval_minutes)
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    async with pool.acquire() as c:
        coll_id = await _collection_id(c, name, user)  # 404/403 gate
        source_json = json.dumps(body.source.model_dump(by_alias=True, exclude_none=True))
        await c.execute(
            """UPDATE ai_collections
               SET refresh_source = $2::jsonb, refresh_interval_minutes = $3, refresh_enabled = true
               WHERE id = $1""",
            coll_id, source_json, minutes)
    return {"success": True, "enabled": True, "interval_minutes": minutes}


@router.get("/ai/collections/{name}/schedule")
async def get_schedule(name: str, user: dict = Depends(require_user)):
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    async with pool.acquire() as c:
        coll_id = await _collection_id(c, name, user)
        row = await c.fetchrow(
            """SELECT refresh_enabled, refresh_interval_minutes, refresh_source,
                      last_refreshed_at, last_refresh_status
               FROM ai_collections WHERE id = $1""", coll_id)
    return {
        "enabled": bool(row["refresh_enabled"]),
        "interval_minutes": row["refresh_interval_minutes"],
        "source": (json.loads(row["refresh_source"]) if row["refresh_source"] else None),
        "last_refreshed_at": row["last_refreshed_at"].isoformat() if row["last_refreshed_at"] else None,
        "last_refresh_status": row["last_refresh_status"],
    }


@router.delete("/ai/collections/{name}/schedule")
async def delete_schedule(name: str, user: dict = Depends(require_user)):
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    async with pool.acquire() as c:
        coll_id = await _collection_id(c, name, user)
        await c.execute("UPDATE ai_collections SET refresh_enabled = false WHERE id = $1", coll_id)
    return {"success": True, "enabled": False}
```

Remove the now-unused `pathlib` import if nothing else uses it (grep first: `grep -n pathlib backend/app/api/ai_vectors.py`; keep the import only if other references remain).

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && python -m pytest tests/test_rag_ingest.py -v`
Expected: PASS. Also confirm no import error: `cd backend && python -c "import app.api.ai_vectors"` (expect no output / exit 0).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_vectors.py backend/tests/test_rag_ingest.py
git commit -m "feat(rag): DB-backed schedule CRUD; remove Airflow DAG path"
```

---

## Task 4: The scheduler loop + startup wiring + Helm config

**Files:**
- Create: `backend/app/rag_scheduler.py`
- Modify: `backend/main.py` (startup handler ~119-206)
- Modify: `helm/datapond/templates/backend-deployment.yaml`, `helm/datapond/values.yaml`
- Test: `backend/tests/test_rag_scheduler.py` (create)

**Interfaces:**
- Consumes: `ai_vectors._refresh_from_source`, `ai_vectors.SourceIngest`, `connectors.get_db_pool`.
- Produces: `rag_scheduler.LOCK_KEY: int`, `rag_scheduler._is_due(last, interval_minutes, now) -> bool`, `async rag_scheduler.tick(pool) -> int` (returns count refreshed), `async rag_scheduler.run_scheduler(pool)`.

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_rag_scheduler.py`):

```python
import asyncio
from datetime import datetime, timedelta, timezone


def _aval(v):
    async def _c(): return v
    return _c()


def test_is_due():
    import app.rag_scheduler as s
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    assert s._is_due(None, 60, now) is True                                  # never run
    assert s._is_due(now - timedelta(minutes=61), 60, now) is True           # overdue
    assert s._is_due(now - timedelta(minutes=10), 60, now) is False          # not yet


class _Conn:
    def __init__(self, lock=True, rows=None, sink=None):
        self._lock = lock; self._rows = rows or []; self.sink = sink if sink is not None else []
    async def fetchval(self, sql, *a):
        if "pg_try_advisory_lock" in sql: return self._lock
        return None
    async def fetch(self, sql, *a):
        if "FROM ai_collections" in sql: return self._rows
        return []
    async def execute(self, sql, *a): self.sink.append((sql, a))
    async def __aenter__(self): return self
    async def __aexit__(self, *e): return False


class _Pool:
    def __init__(self, conn): self._c = conn
    def acquire(self): return self._c


def test_tick_skips_when_lock_not_acquired(monkeypatch):
    import app.rag_scheduler as s
    conn = _Conn(lock=False, rows=[{"id": "c1"}])
    n = asyncio.get_event_loop().run_until_complete(s.tick(_Pool(conn)))
    assert n == 0                                   # did not run despite a due row


def test_tick_refreshes_due_and_records_status(monkeypatch):
    import app.rag_scheduler as s
    import app.api.ai_vectors as v
    calls = []
    async def fake_refresh(pool, coll_id, src):
        calls.append((coll_id, src.type)); return {"documents": 1, "chunks": 2, "pii_masked": 0}
    monkeypatch.setattr(v, "_refresh_from_source", fake_refresh)
    row = {"id": "c1", "name": "kb",
           "refresh_source": '{"type": "s3", "bucket": "b", "prefix": "p/"}',
           "refresh_interval_minutes": 60}
    conn = _Conn(lock=True, rows=[row])
    n = asyncio.get_event_loop().run_until_complete(s.tick(_Pool(conn)))
    assert n == 1 and calls == [("c1", "s3")]
    statuses = [a for (sql, a) in conn.sink if "last_refresh_status" in sql]
    assert statuses and "ok" in str(statuses[0])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_rag_scheduler.py -v`
Expected: FAIL (module `app.rag_scheduler` does not exist).

- [ ] **Step 3: Create `backend/app/rag_scheduler.py`:**

```python
"""Airflow-free RAG freshness scheduler. A single asyncio loop (started at backend
startup) periodically re-embeds collections that have a saved source + interval.
Multi-replica safe via a Postgres advisory lock — only the replica that holds the
lock runs a given tick."""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("rag_scheduler")

# Fixed 64-bit key (derived from ASCII 'datapond', high bit cleared) for pg_try_advisory_lock.
LOCK_KEY = 7233183143331076964


def _is_due(last_refreshed_at, interval_minutes: int, now: datetime) -> bool:
    if last_refreshed_at is None:
        return True
    delta_min = (now - last_refreshed_at).total_seconds() / 60.0
    return delta_min >= interval_minutes


async def tick(pool) -> int:
    """One scheduling pass. Returns the number of collections refreshed."""
    from app.api.ai_vectors import _refresh_from_source, SourceIngest
    refreshed = 0
    async with pool.acquire() as c:
        got = await c.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY)
        if not got:
            return 0
        try:
            rows = await c.fetch(
                """SELECT id, name, refresh_source, refresh_interval_minutes, last_refreshed_at
                   FROM ai_collections
                   WHERE refresh_enabled AND refresh_source IS NOT NULL""")
            now = datetime.now(timezone.utc)
            for r in rows:
                if not _is_due(r["last_refreshed_at"], r["refresh_interval_minutes"], now):
                    continue
                # Claim first (so a crash mid-run doesn't hot-loop this collection).
                await c.execute("UPDATE ai_collections SET last_refreshed_at = now() WHERE id = $1", r["id"])
                try:
                    src = SourceIngest(**json.loads(r["refresh_source"]))
                    res = await _refresh_from_source(pool, r["id"], src)
                    status = f"ok: {res.get('chunks', 0)} chunks"
                    refreshed += 1
                except Exception as e:
                    status = f"error: {e}"[:500]
                    logger.warning("refresh failed for collection %s: %s", r["name"], e)
                await c.execute("UPDATE ai_collections SET last_refresh_status = $2 WHERE id = $1",
                                r["id"], status)
        finally:
            await c.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    return refreshed


async def run_scheduler(pool) -> None:
    tick_seconds = int(os.getenv("RAG_SCHEDULER_TICK_SECONDS", "300"))
    logger.info("RAG freshness scheduler started (tick=%ss)", tick_seconds)
    while True:
        await asyncio.sleep(tick_seconds)
        try:
            n = await tick(pool)
            if n:
                logger.info("RAG scheduler refreshed %s collection(s)", n)
        except Exception as e:                     # never let the loop die
            logger.warning("RAG scheduler tick error: %s", e)
```

Note the fake `SourceIngest(**json.loads(...))` uses field names; the stored JSON uses aliases (`schema`). `SourceIngest` has `populate_by_name = True` and `db_schema` aliased to `schema`, so `SourceIngest(**{"type": "s3", "bucket": "b"})` and `{"schema": "s"...}` both parse.

- [ ] **Step 4: Run scheduler tests to verify pass**

Run: `cd backend && python -m pytest tests/test_rag_scheduler.py -v`
Expected: PASS.

- [ ] **Step 5: Wire startup.** In `backend/main.py`, inside the `startup()` handler, immediately after the `ensure_vector_schema` block (~line 203), add:

```python
    try:
        if os.getenv("RAG_SCHEDULER_ENABLED", "true").lower() in ("1", "true", "yes"):
            from app.api.connectors import get_db_pool
            from app.rag_scheduler import run_scheduler
            asyncio.create_task(run_scheduler(await get_db_pool()))
    except Exception as e:
        logger.warning(f"[startup] RAG scheduler not started: {e}")
```

Confirm `os` and `asyncio` are imported in `main.py` (add `import os` / `import asyncio` at the top if absent — grep first).

- [ ] **Step 6: Wire Helm env.** In `helm/datapond/templates/backend-deployment.yaml`, in the backend container `env:` list, add:

```yaml
            - name: RAG_SCHEDULER_ENABLED
              value: {{ .Values.backend.ragScheduler.enabled | default true | quote }}
            - name: RAG_SCHEDULER_TICK_SECONDS
              value: {{ .Values.backend.ragScheduler.tickSeconds | default 300 | quote }}
```

In `helm/datapond/values.yaml`, under `backend:`, add:

```yaml
  ragScheduler:
    enabled: true
    tickSeconds: 300
```

- [ ] **Step 7: Verify Helm renders.** Run:

`helm template datapond helm/datapond -f helm/datapond/values-prod-single.yaml --set externalDatabase.host=x --set backend.image.repository=x --set frontend.image.repository=x --set ingress.domain=x 2>/dev/null | grep -A1 RAG_SCHEDULER`
Expected: shows both env vars with values `"true"` and `"300"`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/rag_scheduler.py backend/main.py backend/tests/test_rag_scheduler.py \
        helm/datapond/templates/backend-deployment.yaml helm/datapond/values.yaml
git commit -m "feat(rag): in-process freshness scheduler + startup + Helm wiring"
```

---

## Task 5: Docs — record the Airflow-path removal

**Files:**
- Modify: `CLAUDE.md` (roadmap line for auto-freshness)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the roadmap.** In `CLAUDE.md`, find the `[ ] **자동 신선도` roadmap line added earlier and mark it done, e.g.:

```markdown
- ✅ ~~**자동 신선도**~~ — 완료: 백엔드 인프로세스 재임베딩 스케줄러(`rag_scheduler.py`, pg advisory-lock, interval 기반). Airflow DAG 경로 제거, append→replace(source_group) 수정.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark auto-freshness scheduler done"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (schema) → Task 1. ✓
- Component 2 (API: schedule POST/GET/DELETE, ingest-source replace) → Tasks 2 (ingest-source/replace) + 3 (CRUD). ✓
- Component 3 (scheduler loop, advisory lock, catch-up, startup) → Task 4. ✓
- Component 4 (source_group replace, `_refresh_from_source`) → Task 2. ✓
- Component 5 (config/Helm) → Task 4 steps 6-7. ✓
- Testing section → tests across Tasks 1-4. ✓
- Non-goal "remove Airflow path" → Task 3 (delete `_generate_ingest_dag`/`DAGS_PATH`). ✓

**Type consistency:** `_ingest_documents(..., source_group=None)` signature matches its callers (Task 2 `_refresh_from_source`, unchanged `ingest`); `_refresh_from_source(pool, coll_id, src)` matches the scheduler call in Task 4; `_source_group(src)` returns the same `iceberg:...`/`s3:...` strings asserted in Task 2's test and used as the DELETE key. `_is_due(last, interval_minutes, now)` signature identical in `rag_scheduler.py` and its test. `LOCK_KEY` constant identical in code and used consistently.

**Placeholder scan:** No TBD/TODO; every code + test block is concrete; every command has an expected result.
