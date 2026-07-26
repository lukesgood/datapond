"""Concept store + query expansion — the Phase 0 ontology slice.

Scope (docs/CONCEPT_RECONFIRMATION.md §5.1): a curated concept/alias store in the
shared Postgres, opt-in lexical query expansion for /ai/search and /ai/rag, and
concept-level PII tags surfaced to the UI. Deliberately NOT here (demand-gated):
entity graphs, relation extraction, GraphRAG, authoring UI.

Fail-closed behind FEATURE_ONTOLOGY (capability "ontology"). Import format matches
the PoC bootstrap output (docs/research/ontology-poc/draft_ontology.json):
{"concepts":[{"name","aliases":[...],"parent","pii"}]}.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_admin, require_user
from app.api.connectors import get_db_pool

logger = logging.getLogger(__name__)
router = APIRouter()


def ontology_enabled() -> bool:
    return os.getenv("FEATURE_ONTOLOGY", "").strip().lower() in ("1", "true", "yes", "on")


def _require_enabled():
    # Fail-closed like the rest of the capability system: the API surface simply
    # doesn't exist unless the flag is on.
    if not ontology_enabled():
        raise HTTPException(404, "Ontology capability is not enabled (FEATURE_ONTOLOGY).")


# ── Schema ───────────────────────────────────────────────────────────────────────

async def ensure_ontology_schema(pool) -> None:
    """Idempotent concept-store tables (mirrors ensure_vector_schema's pattern)."""
    try:
        async with pool.acquire() as c:
            await c.execute("""
                CREATE TABLE IF NOT EXISTS ontology_concepts (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name        TEXT UNIQUE NOT NULL,
                    description TEXT,
                    parent      TEXT,
                    pii         BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )""")
            await c.execute("""
                CREATE TABLE IF NOT EXISTS concept_terms (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    concept_id  UUID NOT NULL REFERENCES ontology_concepts(id) ON DELETE CASCADE,
                    term        TEXT NOT NULL,
                    kind        TEXT NOT NULL DEFAULT 'alias',
                    UNIQUE (concept_id, term)
                )""")
            await c.execute(
                "CREATE INDEX IF NOT EXISTS concept_terms_term_idx ON concept_terms (lower(term))")
    except Exception as e:  # best-effort, like the vector schema
        logger.warning(f"[ontology] schema ensure failed: {e}")


# ── Expansion (pure core — unit-testable without a DB) ───────────────────────────

def _phrase(s: str) -> str:
    """Normalize a term/query fragment to space-delimited alphanumerics."""
    return " " + " ".join(re.findall(r"[a-z0-9가-힣]+", (s or "").lower())) + " "


def expand_query_text(query: str, concepts: list[dict]) -> tuple[str, list[dict]]:
    """Expand `query` with the terms of every concept whose name or any term appears
    in it (word-boundary phrase match). Returns (expanded_query, matched_concepts)
    where each match is {"name", "pii", "added": [terms appended]}.

    Lexical by design for the Phase 0 slice: the PoC showed expansion pays on
    jargon/codes, where exact vocabulary is the whole point. Pure function.
    """
    q = _phrase(query)

    def hit(term: str) -> bool:
        p = _phrase(term).strip()
        return bool(p) and (" " + p + " ") in q

    matched: list[dict] = []
    added_all: list[str] = []
    for c in concepts:
        terms = [c["name"], *(c.get("terms") or [])]
        if not any(hit(t) for t in terms if t):
            continue
        add = []
        for t in terms:
            if t and not hit(t) and t not in added_all:
                add.append(t)
                added_all.append(t)
        matched.append({"name": c["name"], "pii": bool(c.get("pii")), "added": add})
    if not added_all:
        return query, matched
    return query + " " + " ".join(added_all), matched


async def load_concepts(pool) -> list[dict]:
    """Concept list with terms, shaped for expand_query_text."""
    await ensure_ontology_schema(pool)
    async with pool.acquire() as c:
        rows = await c.fetch("""
            SELECT oc.name, oc.pii, oc.parent, oc.description,
                   COALESCE(array_agg(ct.term) FILTER (WHERE ct.term IS NOT NULL), '{}') AS terms
            FROM ontology_concepts oc
            LEFT JOIN concept_terms ct ON ct.concept_id = oc.id
            GROUP BY oc.id ORDER BY oc.name""")
    return [{"name": r["name"], "pii": r["pii"], "parent": r["parent"],
             "description": r["description"], "terms": list(r["terms"])} for r in rows]


async def expand_for_query(query: str) -> tuple[str, list[dict]]:
    """Convenience used by /ai/search and /ai/rag. No-op when disabled or empty."""
    if not ontology_enabled():
        return query, []
    try:
        concepts = await load_concepts(await get_db_pool())
    except Exception as e:
        logger.warning(f"[ontology] expansion skipped (load failed): {e}")
        return query, []
    return expand_query_text(query, concepts)


# ── API ──────────────────────────────────────────────────────────────────────────

class ConceptIn(BaseModel):
    name: str
    description: Optional[str] = None
    parent: Optional[str] = None
    pii: bool = False
    terms: list[str] = []


class ConceptImport(BaseModel):
    # Matches the PoC bootstrap draft: aliases == terms.
    concepts: list[dict]


@router.get("/ai/concepts")
async def list_concepts(user: dict = Depends(require_user)):
    _require_enabled()
    return {"concepts": await load_concepts(await get_db_pool())}


@router.post("/ai/concepts")
async def create_concept(body: ConceptIn, user: dict = Depends(require_admin)):
    _require_enabled()
    pool = await get_db_pool()
    await ensure_ontology_schema(pool)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Concept name is required.")
    async with pool.acquire() as c:
        cid = await c.fetchval("""
            INSERT INTO ontology_concepts (name, description, parent, pii)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (name) DO UPDATE
              SET description = EXCLUDED.description, parent = EXCLUDED.parent, pii = EXCLUDED.pii
            RETURNING id""", name, body.description, body.parent, body.pii)
        for t in body.terms:
            t = (t or "").strip()
            if t:
                await c.execute(
                    "INSERT INTO concept_terms (concept_id, term) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    cid, t)
    return {"ok": True, "name": name}


@router.delete("/ai/concepts/{name}")
async def delete_concept(name: str, user: dict = Depends(require_admin)):
    _require_enabled()
    pool = await get_db_pool()
    await ensure_ontology_schema(pool)
    async with pool.acquire() as c:
        deleted = await c.execute("DELETE FROM ontology_concepts WHERE name = $1", name)
    return {"ok": True, "deleted": deleted.endswith("1")}


@router.post("/ai/concepts/import")
async def import_concepts(body: ConceptImport, user: dict = Depends(require_admin)):
    """Bulk upsert in the PoC bootstrap shape ({name, aliases, parent, pii})."""
    _require_enabled()
    pool = await get_db_pool()
    await ensure_ontology_schema(pool)
    n = 0
    async with pool.acquire() as c:
        for item in body.concepts:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            cid = await c.fetchval("""
                INSERT INTO ontology_concepts (name, description, parent, pii)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (name) DO UPDATE
                  SET parent = EXCLUDED.parent, pii = EXCLUDED.pii
                RETURNING id""",
                name, item.get("description"), item.get("parent"), bool(item.get("pii")))
            for t in (item.get("aliases") or item.get("terms") or []):
                t = str(t or "").strip()
                if t:
                    await c.execute(
                        "INSERT INTO concept_terms (concept_id, term) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        cid, t)
            n += 1
    return {"ok": True, "imported": n}
