# RAG Freshness Scheduler — Design Spec

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan
**Positioning driver:** #1 identified "AI Data Foundation" product gap — automatic freshness of RAG collections without Airflow.

## Problem

RAG collections can be re-embedded from a source (an Iceberg table column or an S3 prefix). Today the only *automatic* path is `POST /api/ai/collections/{name}/schedule`, which writes an **Airflow DAG file** to `/opt/airflow/dags`; Airflow's cron then calls back into `POST /ingest-source`. In the **AWS foundation profile Airflow is disabled**, so scheduled re-embedding never runs — collections silently go stale. This is the platform's core "always-fresh governed data" promise, unmet.

Two coupled defects make this worse:
1. **No Airflow-free trigger** exists (backend has no in-process scheduler; all recurrence is externalized to Airflow).
2. **`_ingest_documents` APPENDS** chunks with no upsert/delete (`ai_vectors.py:304-309`) — so *any* repeated re-embed (even manual) **duplicates** chunks and corrupts retrieval. A freshness feature that re-runs on a timer would multiply this.

## Goal

A backend-internal, profile-agnostic scheduler that periodically re-embeds collections that have a saved source + interval, with **replace** (not append) semantics, coordinated safely across backend replicas, with no new AWS infrastructure and no dependency on Airflow.

## Non-goals (YAGNI)

- Cron expressions — **interval-based only** (`refresh_interval_minutes`). Legacy Airflow presets map: `@hourly`→60, `@daily`→1440, `@weekly`→10080.
- Multi-source-per-collection scheduling — one saved refresh source per collection (the existing model).
- Backfill/audit history of past runs beyond the last-run status.
- The Iceberg maintenance DAG (`deploy_maintenance_dag`) — separate concern, out of scope.

## Decisions (approved)

1. **Interval-based**, not cron.
2. **Backend scheduler is THE mechanism on all profiles.** Remove the Airflow-DAG generation path (`_generate_ingest_dag`, `DAGS_PATH` use in the schedule endpoint) — it is dead in foundation and redundant elsewhere.
3. **Replace semantics** keyed by a deterministic `source_key` stored in `ai_chunks.source`.

## Architecture

```
startup handler ── starts ──▶ rag_scheduler asyncio loop (every RAG_SCHEDULER_TICK_SECONDS)
                                     │
                          pg_try_advisory_lock(LOCK_KEY)   ← only one replica proceeds
                                     │ acquired
                    SELECT collections WHERE refresh_enabled
                      AND (last_refreshed_at IS NULL OR
                           last_refreshed_at + interval <= now())
                                     │ for each due collection
                    refresh_collection(coll)  ── reuses ──▶ _read_iceberg_docs / _read_s3_docs
                                     │                        + _ingest_documents (REPLACE)
                    UPDATE last_refreshed_at, last_refresh_status
                                     │
                          pg_advisory_unlock(LOCK_KEY)
```

### Component 1 — Schema (new columns on `ai_collections`)

Added idempotently in `ensure_vector_schema()` (`ai_vectors.py`) via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`:

| Column | Type | Meaning |
|--------|------|---------|
| `refresh_source` | `JSONB` | the `SourceIngest` config to re-embed from (null = no schedule) |
| `refresh_interval_minutes` | `INT` | how often to re-embed |
| `refresh_enabled` | `BOOLEAN NOT NULL DEFAULT false` | schedule active flag |
| `last_refreshed_at` | `TIMESTAMPTZ` | last successful (or attempted) run start |
| `last_refresh_status` | `TEXT` | `"ok"`, `"ok: N chunks"`, or `"error: <msg>"` |

No new table. `ai_chunks.source` (existing) becomes the replace key.

### Component 2 — API changes (`ai_vectors.py`)

- **`POST /api/ai/collections/{name}/schedule`** — *behavior change*. Request `ScheduleRequest { interval_minutes: int (>0), source: SourceIngest }` (accepts legacy `schedule: str` preset and maps to `interval_minutes` for back-compat). Persists `refresh_source`, `refresh_interval_minutes`, `refresh_enabled=true` on the collection. **No longer writes an Airflow DAG.** Returns the saved schedule + `last_refreshed_at`. Auth: `require_user` (owner/admin per existing collection RLS).
- **`GET /api/ai/collections/{name}/schedule`** — returns `{ enabled, interval_minutes, source, last_refreshed_at, last_refresh_status, next_due_at }`. Auth: `require_user`.
- **`DELETE /api/ai/collections/{name}/schedule`** — sets `refresh_enabled=false` (keeps source/interval for easy re-enable). Auth: `require_user`.
- **`POST /api/ai/collections/{name}/ingest-source`** — signature unchanged; internally switches to **replace** semantics (Component 4). Still `require_user_or_internal`.
- **Removed:** `_generate_ingest_dag(...)` and the `DAGS_PATH` write. `ScheduleRequest.schedule` (Airflow preset) demoted to optional legacy alias.

### Component 3 — Scheduler loop (`backend/app/rag_scheduler.py`, new)

- `async def run_scheduler(pool)` — loop: `await asyncio.sleep(TICK)`, then one `tick(pool)`, wrapped so no exception ever escapes (log + continue).
- `async def tick(pool)`:
  1. `got = SELECT pg_try_advisory_lock(LOCK_KEY)` on a dedicated connection. If not `got`, return (another replica owns this tick).
  2. `SELECT id, name, refresh_source, refresh_interval_minutes FROM ai_collections WHERE refresh_enabled AND refresh_source IS NOT NULL AND (last_refreshed_at IS NULL OR last_refreshed_at + (refresh_interval_minutes * interval '1 minute') <= now())`.
  3. For each: `UPDATE ... SET last_refreshed_at = now()` first (claim, so a crash mid-run doesn't hot-loop), then `await refresh_collection(pool, coll)`, then set `last_refresh_status`.
  4. `pg_advisory_unlock(LOCK_KEY)` in a `finally`.
- `LOCK_KEY` — a fixed 64-bit constant (documented) unique to this subsystem.
- Started from the `@app.on_event("startup")` handler in `backend/main.py` via `asyncio.create_task(run_scheduler(pool))`, guarded by `RAG_SCHEDULER_ENABLED`.
- **Catch-up:** because selection is `overdue`, a node that was stopped (weekday schedule) runs each overdue collection **once** on the next tick after startup — not N times.

### Component 4 — Replace semantics (fix the append bug)

`ai_chunks.source` is per-document (S3 stores one distinct `s3://bucket/key` per file; it is surfaced as the citation and counted by `COUNT(DISTINCT ch.source)` in the collection stats). It therefore cannot double as the replace key. Add a dedicated **`ai_chunks.source_group TEXT`** column (indexed on `(collection_id, source_group)`) that scopes a logical source for replacement while leaving `source` for citations.

`_ingest_documents(coll_id, docs, chunk_size, chunk_overlap, source_group=None)` gains an optional `source_group`:
- Deterministic group key `_source_group(src: SourceIngest)`:
  - iceberg → `f"iceberg:{schema}.{table}.{text_column}"`
  - s3 → `f"s3:{bucket}/{prefix or ''}"`
- When `source_group` is provided (the `ingest-source` path, manual or scheduled): in one transaction `DELETE FROM ai_chunks WHERE collection_id = $1 AND source_group = $2`, then insert fresh chunks with that `source_group` (and per-doc `source` unchanged).
- When `source_group` is `None` (the inline `/ingest` text path): behave exactly as today — append, no delete.
- Scoping by `source_group` means re-embedding an Iceberg source does **not** wipe a different source or inline text in the same collection.
- Reading + ingest is extracted into `_refresh_from_source(pool, coll_id, src: SourceIngest) -> dict` shared by the `ingest-source` endpoint and the scheduler (DRY).
- This fixes both scheduled re-embeds and manual `ingest-source` re-runs.

### Component 5 — Config / Helm

- `RAG_SCHEDULER_ENABLED` (default `"true"`) and `RAG_SCHEDULER_TICK_SECONDS` (default `"300"`) — read in `main.py`.
- Wired as backend env in `helm/datapond/templates/backend-deployment.yaml` with values keys (e.g. `backend.ragScheduler.enabled`, `backend.ragScheduler.tickSeconds`), defaulting on.
- No new AWS/terraform resources.

## Error handling

- Loop body fully wrapped: a bad tick logs and the loop continues (never crashes the process / event loop).
- Per-collection `try/except`: one failing collection records `last_refresh_status="error: <msg>"` and the tick moves to the next; it will retry next interval.
- Advisory lock released in `finally`; connection returned to pool in `finally`.
- Embedding calls already run in batches via LiteLLM; a LiteLLM/Bedrock outage surfaces as an `error:` status, not a crash.

## Testing

- `refresh_interval_minutes` due-selection SQL: overdue included, not-yet-due excluded, null-last-run included.
- Advisory-lock: second concurrent `tick` returns early when the lock is held (simulate held lock).
- **Replace semantics:** ingest a source twice → chunk count stable (no duplication); a *different* source in the same collection is untouched.
- `source_key` derivation for iceberg/s3/text.
- Legacy preset mapping (`@daily`→1440).
- Schedule CRUD endpoints: POST persists, GET reflects, DELETE disables; ownership/RLS enforced.
- Startup wiring: scheduler task created iff `RAG_SCHEDULER_ENABLED`.

## Migration / compatibility

- New columns are additive (`ADD COLUMN IF NOT EXISTS`) — safe on existing `ai_collections`.
- Existing Airflow DAG files previously written by the old `/schedule` become inert (Airflow off in foundation; and the endpoint no longer creates them). No cleanup required for foundation; a full-profile note documents that pre-existing `datapond_rag_ingest_*` DAGs can be deleted from the DAGs volume.
- `_ingest_documents` signature gains `source_key` — all call sites (schedule path, manual ingest-source, text ingest) updated in the same change.

## Out of scope / follow-ups

- Cron-expression scheduling (interval covers the need now).
- Per-source multiple schedules per collection.
- Connector→RAG sink auto re-embed (separate roadmap item — a source *change* trigger vs a timer).
- Prometheus metric for last-refresh age (nice-to-have observability).
