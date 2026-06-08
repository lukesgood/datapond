"""
AI vector store + RAG on pgvector (in the shared Postgres).

Sovereign by design: embeddings and chat both go through the LiteLLM gateway, so the
local-only egress policy applies (documents are embedded by a LOCAL model and never
leave the cluster). Chunk content is PII-masked at ingest. Vectors live in the
existing Postgres (no new infra), so air-gap / on-prem just works.

Endpoints (all under /api):
  POST   /ai/embed                          text(s) → embedding(s)
  GET    /ai/collections                    list collections (+ chunk counts)
  POST   /ai/collections                    create a collection
  DELETE /ai/collections/{name}             drop a collection (+ its chunks)
  POST   /ai/collections/{name}/ingest      chunk → PII-mask → embed → upsert
  POST   /ai/search                         semantic (vector) search
  POST   /ai/rag                            retrieve → LiteLLM chat → cited answer
"""
import os
import re
import json
import asyncio
import logging
import uuid
import pathlib
from typing import Optional, List

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.api.connectors import get_db_pool
from app.api.auth import require_user, require_user_or_internal
from app.ai_context import set_actor, actor_payload
from app.api.ai_backends import egress_policy, is_external_provider, provider_of_model

logger = logging.getLogger(__name__)
router = APIRouter()


def _embed_model() -> str:
    return os.getenv("AI_EMBED_MODEL", "embed").strip() or "embed"


def EMBED_DIM() -> int:
    return int(os.getenv("AI_EMBED_DIM", "1024"))


def _gateway() -> tuple[str, str]:
    url = os.getenv("LITELLM_URL", "").strip().rstrip("/")
    key = os.getenv("LITELLM_MASTER_KEY", "").strip()
    if not url:
        raise HTTPException(503, "LiteLLM gateway not configured (LITELLM_URL empty).")
    return url, key


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


def _vec_literal(v: List[float]) -> str:
    """pgvector text literal — asyncpg has no native vector codec, so we cast $n::vector."""
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def _chunk(text: str, size: int = 1000, overlap: int = 150) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out, i, step = [], 0, max(1, size - overlap)
    while i < len(text):
        out.append(text[i:i + size])
        i += step
    return out


# ── Schema ──────────────────────────────────────────────────────────────────────

async def ensure_vector_schema(pool) -> None:
    """Idempotent: pgvector extension + ai_collections / ai_chunks + indexes.
    Best-effort (logs and continues if pgvector isn't available)."""
    dim = EMBED_DIM()
    try:
        async with pool.acquire() as c:
            await c.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await c.execute("""
                CREATE TABLE IF NOT EXISTS ai_collections (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name        TEXT UNIQUE NOT NULL,
                    embed_model TEXT NOT NULL,
                    dim         INT NOT NULL,
                    description TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )""")
            await c.execute(f"""
                CREATE TABLE IF NOT EXISTS ai_chunks (
                    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    collection_id UUID NOT NULL REFERENCES ai_collections(id) ON DELETE CASCADE,
                    source        TEXT,
                    chunk_index   INT,
                    content       TEXT NOT NULL,
                    metadata      JSONB DEFAULT '{{}}',
                    embedding     vector({dim}),
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                )""")
            # Per-collection access control (RLS): the creating user owns it.
            await c.execute("ALTER TABLE ai_collections ADD COLUMN IF NOT EXISTS owner_id UUID")
            await c.execute("CREATE INDEX IF NOT EXISTS ai_chunks_coll_idx ON ai_chunks(collection_id)")
            await c.execute(
                "CREATE INDEX IF NOT EXISTS ai_chunks_embed_idx "
                "ON ai_chunks USING hnsw (embedding vector_cosine_ops)"
            )
    except Exception as e:
        logger.warning(f"[ai_vectors] schema ensure failed (pgvector available?): {e}")


# ── Embeddings (via LiteLLM, egress-guarded) ─────────────────────────────────────

async def _assert_embed_egress_ok() -> None:
    """Under local-only, refuse an external embedding model (no data egress)."""
    if egress_policy() != "local-only":
        return
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{url}/model/info", headers=_headers(key))
            if r.status_code < 400:
                for m in r.json().get("data", []):
                    if m.get("model_name") == _embed_model():
                        prov = provider_of_model((m.get("litellm_params") or {}).get("model", ""))
                        if is_external_provider(prov):
                            raise HTTPException(
                                403,
                                f"AI egress policy is 'local-only': external embedding "
                                f"provider '{prov}' is blocked. Use a local model "
                                f"(Ollama bge-m3 / nomic-embed-text).",
                            )
                        return
    except HTTPException:
        raise
    except Exception:
        return  # best-effort; registration-time guard is the primary control


async def _embed(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    await _assert_embed_egress_ok()
    url, key = _gateway()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{url}/v1/embeddings", headers=_headers(key),
                         json={"model": _embed_model(), "input": texts, **actor_payload("ai_embed")})
    if r.status_code >= 400:
        raise HTTPException(502, f"Embedding failed: {(r.text or '')[:200]}")
    data = r.json().get("data", [])
    data.sort(key=lambda x: x.get("index", 0))
    return [d["embedding"] for d in data]


# ── Request models ───────────────────────────────────────────────────────────────

class EmbedRequest(BaseModel):
    input: List[str]


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class Document(BaseModel):
    source: Optional[str] = None
    text: str
    metadata: Optional[dict] = None


class IngestRequest(BaseModel):
    documents: List[Document]
    chunk_size: int = 1000
    chunk_overlap: int = 150


class SearchRequest(BaseModel):
    collection: str
    query: str
    k: int = 5


class RagRequest(BaseModel):
    collection: str
    question: str
    k: int = 5


# ── Routes ───────────────────────────────────────────────────────────────────────

@router.post("/ai/embed")
async def embed(req: EmbedRequest, user: dict = Depends(require_user)):
    set_actor(user)
    vecs = await _embed(req.input)
    return {"model": _embed_model(), "dim": len(vecs[0]) if vecs else EMBED_DIM(), "embeddings": vecs}


def _uid(user: dict):
    try:
        return uuid.UUID(user["id"])
    except Exception:
        return None


@router.get("/ai/collections")
async def list_collections(user: dict = Depends(require_user)):
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    is_admin = user.get("role") == "admin"
    async with pool.acquire() as c:
        # Admins see all collections; everyone else sees their own + shared (no owner).
        rows = await c.fetch(f"""
            SELECT col.name, col.embed_model, col.dim, col.description, col.created_at,
                   col.owner_id, COUNT(ch.id) AS chunks
            FROM ai_collections col
            LEFT JOIN ai_chunks ch ON ch.collection_id = col.id
            {"" if is_admin else "WHERE col.owner_id = $1 OR col.owner_id IS NULL"}
            GROUP BY col.id ORDER BY col.created_at DESC
        """, *([] if is_admin else [_uid(user)]))
    return {"collections": [
        {"name": r["name"], "embed_model": r["embed_model"], "dim": r["dim"],
         "description": r["description"], "chunks": r["chunks"],
         "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
         "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]}


@router.post("/ai/collections")
async def create_collection(body: CollectionCreate, user: dict = Depends(require_user)):
    if not body.name.strip():
        raise HTTPException(400, "name is required.")
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO ai_collections (name, embed_model, dim, description, owner_id)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description""",
            body.name.strip(), _embed_model(), EMBED_DIM(), body.description, _uid(user),
        )
    return {"success": True, "name": body.name.strip(),
            "embed_model": _embed_model(), "dim": EMBED_DIM()}


@router.delete("/ai/collections/{name}")
async def delete_collection(name: str, user: dict = Depends(require_user)):
    pool = await get_db_pool()
    async with pool.acquire() as c:
        await _collection_id(c, name, user, destroy=True)   # 404/403 gate (owner/admin only)
        res = await c.execute("DELETE FROM ai_collections WHERE name = $1", name)
    return {"success": True, "deleted": res}


async def _collection_id(c, name: str, user: dict, *, destroy: bool = False):
    """Resolve a collection id, enforcing access.

    Read/ingest: owner, admin, or anyone for shared (owner_id IS NULL) collections.
    Destroy: only the owner or an admin — shared collections are admin-only to delete.
    """
    row = await c.fetchrow("SELECT id, owner_id FROM ai_collections WHERE name = $1", name)
    if not row:
        raise HTTPException(404, f"Collection '{name}' not found.")
    if user.get("role") != "admin":
        owner = row["owner_id"]
        if destroy:
            allowed = owner is not None and owner == _uid(user)
        else:
            allowed = owner is None or owner == _uid(user)
        if not allowed:
            raise HTTPException(403, f"Not authorized for collection '{name}'.")
    return row["id"]


async def _ingest_documents(coll_id, docs: List[tuple], chunk_size: int, overlap: int) -> dict:
    """docs: list of (source, text, metadata). Chunk → PII-mask → embed → upsert."""
    from app.guardrails import pii_ko
    items = []  # (source, idx, content, metadata_json)
    pii_masked = 0
    for source, text, meta in docs:
        for idx, raw in enumerate(_chunk(text, chunk_size, overlap)):
            masked, found, _blk = pii_ko.apply(raw)
            pii_masked += len(found)
            items.append((source, idx, masked, json.dumps(meta or {})))
    if not items:
        return {"chunks": 0, "pii_masked": 0}
    embeddings: List[List[float]] = []
    B = 64
    for i in range(0, len(items), B):
        embeddings.extend(await _embed([it[2] for it in items[i:i + B]]))
    pool = await get_db_pool()
    async with pool.acquire() as c:
        await c.executemany(
            """INSERT INTO ai_chunks (collection_id, source, chunk_index, content, metadata, embedding)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)""",
            [(coll_id, it[0], it[1], it[2], it[3], _vec_literal(emb))
             for it, emb in zip(items, embeddings)],
        )
    return {"chunks": len(items), "pii_masked": pii_masked}


@router.post("/ai/collections/{name}/ingest")
async def ingest(name: str, req: IngestRequest, user: dict = Depends(require_user)):
    """Ingest inline documents. Chunk → PII-mask → embed → upsert."""
    set_actor(user)
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    async with pool.acquire() as c:
        coll_id = await _collection_id(c, name, user)
    res = await _ingest_documents(
        coll_id, [(d.source, d.text, d.metadata) for d in req.documents],
        req.chunk_size, req.chunk_overlap)
    return {"success": True, **res}


# ── Source ingestion (the AI data pipeline: lakehouse / object store → vectors) ──

def _read_iceberg_docs(schema: str, table: str, text_column: str, limit: int) -> List[tuple]:
    """One document per row of iceberg.<schema>.<table>.<text_column> (via Trino)."""
    from app.api.trino_util import trino_conn
    src = f"iceberg.{schema}.{table}.{text_column}"
    conn = trino_conn(timeout=60)
    cur = conn.cursor()
    cur.execute(
        f'SELECT "{text_column}" FROM iceberg."{schema}"."{table}" '
        f'WHERE "{text_column}" IS NOT NULL LIMIT {int(limit)}'
    )
    return [(src, str(r[0]), {"schema": schema, "table": table, "row": i})
            for i, r in enumerate(cur.fetchall())]


def _read_s3_docs(bucket: str, prefix: str, max_files: int) -> List[tuple]:
    """One document per text/markdown object under s3://bucket/prefix."""
    from app.api.storage import get_s3_client
    s3 = get_s3_client()
    docs, n = [], 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix or ""):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith((".txt", ".md", ".markdown", ".csv", ".json", ".log")):
                continue
            if obj.get("Size", 0) > 5_000_000:
                continue
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            docs.append((f"s3://{bucket}/{key}", body.decode("utf-8", errors="replace"),
                         {"bucket": bucket, "key": key}))
            n += 1
            if n >= max_files:
                return docs
    return docs


class SourceIngest(BaseModel):
    type: str                                    # "iceberg" | "s3"
    # iceberg
    db_schema: Optional[str] = Field(None, alias="schema")
    table: Optional[str] = None
    text_column: Optional[str] = None
    limit: int = 1000
    # s3
    bucket: Optional[str] = None
    prefix: Optional[str] = None
    max_files: int = 200
    chunk_size: int = 1000
    chunk_overlap: int = 150

    class Config:
        populate_by_name = True


def _ident_ok(*vals) -> bool:
    return all(re.fullmatch(r"[A-Za-z0-9_]+", v or "") for v in vals)


@router.post("/ai/collections/{name}/ingest-source")
async def ingest_source(name: str, req: SourceIngest, user: dict = Depends(require_user_or_internal)):
    """Feed the vector store from a lakehouse/object-store source — the AI data
    pipeline over DataPond's own data (Iceberg table column, or S3 text files).

    Accepts either a user JWT or the in-cluster X-Internal-Key so scheduled Airflow
    DAGs (which run unattended) can call back to re-ingest on a schedule."""
    set_actor(user)
    pool = await get_db_pool()
    await ensure_vector_schema(pool)
    async with pool.acquire() as c:
        coll_id = await _collection_id(c, name, user)

    if req.type == "iceberg":
        if not (req.db_schema and req.table and req.text_column):
            raise HTTPException(400, "iceberg source needs schema, table, text_column.")
        if not _ident_ok(req.db_schema, req.table, req.text_column):
            raise HTTPException(400, "schema/table/text_column must be bare identifiers.")
        docs = await asyncio.to_thread(_read_iceberg_docs, req.db_schema, req.table,
                                       req.text_column, req.limit)
    elif req.type == "s3":
        if not req.bucket:
            raise HTTPException(400, "s3 source needs bucket (and optional prefix).")
        docs = await asyncio.to_thread(_read_s3_docs, req.bucket, req.prefix, req.max_files)
    else:
        raise HTTPException(400, "type must be 'iceberg' or 's3'.")

    res = await _ingest_documents(coll_id, docs, req.chunk_size, req.chunk_overlap)
    return {"success": True, "documents": len(docs), **res}


# ── Scheduled ingestion (recurring AI data pipeline via Airflow) ─────────────────

DAGS_PATH = pathlib.Path(os.getenv("AIRFLOW_DAGS_PATH", "/opt/airflow/dags"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend.datapond.svc.cluster.local:8000")


class ScheduleRequest(BaseModel):
    schedule: str = "@daily"
    source: SourceIngest


def _generate_ingest_dag(dag_id: str, collection: str, schedule: str, source_json: str) -> str:
    return f'''"""DataPond RAG ingestion — auto-generated. Re-embeds a source into a
collection on a schedule (AI data pipeline: lakehouse/object-store → vector store)."""
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
import json, os, urllib.request

COLLECTION = {collection!r}
SOURCE = json.loads({source_json!r})
URL = "{BACKEND_URL}/api/ai/collections/" + COLLECTION + "/ingest-source"

def ingest(**_):
    headers = {{"Content-Type": "application/json"}}
    # Unattended auth: present the in-cluster shared key (mounted from datapond-secrets).
    key = (os.getenv("DATAPOND_INTERNAL_KEY") or "").strip()
    if key:
        headers["X-Internal-Key"] = key
    req = urllib.request.Request(URL, data=json.dumps(SOURCE).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        print(r.read().decode())

with DAG(dag_id={dag_id!r}, start_date=datetime(2024,1,1), schedule={schedule!r},
         catchup=False, tags=["datapond","rag","ai"]) as dag:
    PythonOperator(task_id="ingest_source", python_callable=ingest)
'''


@router.post("/ai/collections/{name}/schedule")
async def schedule_ingest(name: str, body: ScheduleRequest, user: dict = Depends(require_user)):
    """Deploy an Airflow DAG that re-ingests `source` into this collection on a schedule."""
    pool = await get_db_pool()
    async with pool.acquire() as c:
        await _collection_id(c, name, user)  # 404/403 gate
    dag_id = "datapond_rag_ingest_" + re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    source_json = json.dumps(body.source.model_dump(by_alias=True, exclude_none=True))
    code = _generate_ingest_dag(dag_id, name, body.schedule, source_json)
    try:
        DAGS_PATH.mkdir(parents=True, exist_ok=True)
        (DAGS_PATH / f"{dag_id}.py").write_text(code, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Failed to write DAG (Airflow DAGs volume mounted?): {e}")
    return {"success": True, "dag_id": dag_id, "schedule": body.schedule}


def _rerank_model() -> str:
    """Optional cross-encoder rerank model registered in LiteLLM (e.g.
    bedrock/amazon.rerank-v1:0, cohere rerank). Empty = vector order only."""
    return os.getenv("AI_RERANK_MODEL", "").strip()


async def _rerank(query: str, hits: List[dict], k: int) -> List[dict]:
    """Reorder vector hits with a LiteLLM rerank model (/v1/rerank). Graceful: returns
    the original top-k on any error so retrieval never hard-fails on rerank."""
    model = _rerank_model()
    if not model or len(hits) <= 1:
        return hits[:k]
    url, key = _gateway()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{url}/v1/rerank", headers=_headers(key),
                             json={"model": model, "query": query,
                                   "documents": [h["content"] for h in hits],
                                   "top_n": k, **actor_payload("ai_rerank")})
        if r.status_code >= 400:
            logger.warning(f"[ai_vectors] rerank {r.status_code}: {(r.text or '')[:120]}")
            return hits[:k]
        out = []
        for res in (r.json().get("results") or [])[:k]:
            idx = res.get("index")
            if isinstance(idx, int) and 0 <= idx < len(hits):
                h = dict(hits[idx]); h["rerank_score"] = round(float(res.get("relevance_score") or 0), 4)
                out.append(h)
        return out or hits[:k]
    except Exception as e:
        logger.warning(f"[ai_vectors] rerank failed: {e}")
        return hits[:k]


async def _retrieve(name: str, query: str, k: int, user: dict):
    pool = await get_db_pool()
    qvec = (await _embed([query]))[0]
    # Over-fetch candidates when a reranker is configured, then rerank down to k.
    fetch_k = min(max(k * 4, k), 50) if _rerank_model() else max(1, min(k, 50))
    async with pool.acquire() as c:
        coll_id = await _collection_id(c, name, user)
        rows = await c.fetch(
            """SELECT source, chunk_index, content, metadata,
                      1 - (embedding <=> $1::vector) AS score
               FROM ai_chunks
               WHERE collection_id = $2
               ORDER BY embedding <=> $1::vector
               LIMIT $3""",
            _vec_literal(qvec), coll_id, fetch_k,
        )
    hits = [
        {"source": r["source"], "chunk_index": r["chunk_index"], "content": r["content"],
         "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else (r["metadata"] or {}),
         "score": round(float(r["score"]), 4)}
        for r in rows
    ]
    return await _rerank(query, hits, k)


def _guard(text: str):
    """Korean PII guardrail (mask/block) — same engine as ai_sql, now on the query
    path too so RAG/search are covered (not just /ai/sql + ingest)."""
    from app.guardrails import pii_ko
    return pii_ko.apply(text or "")


@router.post("/ai/search")
async def search(req: SearchRequest, user: dict = Depends(require_user)):
    set_actor(user)
    q_text, q_find, q_block = _guard(req.query)
    if q_block:
        raise HTTPException(400, "Query blocked by PII guardrail (PII_GUARDRAIL_MODE=block).")
    return {"collection": req.collection, "query": req.query,
            "pii_masked": len(q_find),
            "results": await _retrieve(req.collection, q_text, req.k, user)}


@router.post("/ai/rag")
async def rag(req: RagRequest, user: dict = Depends(require_user)):
    """Retrieve top-k chunks, then ask the active LiteLLM chat model with that context.
    Returns the answer + the citations it was grounded on."""
    set_actor(user)
    # PII guardrail on the question before it reaches retrieval/the LLM.
    q_text, q_find, q_block = _guard(req.question)
    if q_block:
        return {"answer": "질문에 개인정보(PII)가 감지되어 차단되었습니다 (PII_GUARDRAIL_MODE=block).",
                "citations": [], "has_ai": False, "pii_masked": len(q_find)}

    hits = await _retrieve(req.collection, q_text, req.k, user)
    if not hits:
        return {"answer": "참고할 문서를 찾지 못했습니다. (컬렉션이 비었거나 관련 내용 없음)",
                "citations": [], "has_ai": False, "pii_masked": len(q_find)}

    context = "\n\n".join(
        f"[{i+1}] (source: {h['source'] or 'n/a'})\n{h['content']}" for i, h in enumerate(hits)
    )
    system = (
        "You answer strictly from the provided context. Cite sources as [n]. "
        "If the answer isn't in the context, say you don't know. Answer in the user's language."
    )
    user_msg = f"Context:\n{context}\n\nQuestion: {q_text}"

    url, key = _gateway()
    model = os.getenv("LITELLM_MODEL", "default")
    # Reuse the chat egress guard from ai_sql (blocks external chat under local-only).
    try:
        from app.api.ai_sql import _active_provider_is_external
        import asyncio as _a
        if egress_policy() == "local-only" and await _a.to_thread(_active_provider_is_external) is True:
            raise HTTPException(403, "AI egress policy 'local-only': external chat model blocked.")
    except HTTPException:
        raise
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{url}/v1/chat/completions", headers=_headers(key),
                             json={"model": model, "max_tokens": 1024,
                                   "messages": [{"role": "system", "content": system},
                                                {"role": "user", "content": user_msg}],
                                   **actor_payload("ai_rag")})
        if r.status_code >= 400:
            return {"answer": f"(LLM 호출 실패: {r.status_code}) 검색 결과만 반환합니다.",
                    "citations": hits, "has_ai": False, "pii_masked": len(q_find)}
        answer = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[ai_vectors] rag chat failed: {e}")
        return {"answer": "(LLM 미설정/오류) 검색 결과만 반환합니다.", "citations": hits,
                "has_ai": False, "pii_masked": len(q_find)}

    return {"answer": answer, "citations": hits, "has_ai": True, "pii_masked": len(q_find)}
