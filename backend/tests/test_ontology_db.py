"""Integration tests for the Phase 0 concept store against a REAL PostgreSQL.

Skipped unless ONTOLOGY_TEST_DB is set (e.g. postgresql://localhost/datapond_ontology_test)
so the suite stays green on machines/CI without Postgres. Covers the DB surface the
pure-function tests can't: schema idempotency, import upsert semantics, term
aggregation in load_concepts, delete cascade, and the loaded-shape → expansion path.
"""
import asyncio
import os

import pytest

TEST_DB = os.getenv("ONTOLOGY_TEST_DB", "").strip()

pytestmark = pytest.mark.skipif(not TEST_DB, reason="ONTOLOGY_TEST_DB not set")

# The PoC bootstrap shape (docs/research/ontology-poc/draft_ontology.json) — the
# exact payload /ai/concepts/import accepts.
DRAFT = {
    "concepts": [
        {"name": "Deductible", "aliases": ["excess"], "parent": None, "pii": False},
        {"name": "UB-04", "aliases": ["ub04", "hospital inpatient bill"], "parent": None, "pii": False},
        {"name": "Policyholder", "aliases": ["insured", "homeowner"], "parent": None, "pii": True},
    ]
}


async def _fresh_pool():
    import asyncpg
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    async with pool.acquire() as c:
        await c.execute("DROP TABLE IF EXISTS concept_terms")
        await c.execute("DROP TABLE IF EXISTS ontology_concepts")
    return pool


async def _import(pool, draft):
    # Mirror the import endpoint's core (endpoint itself is a thin auth wrapper).
    from app.api.ontology import ensure_ontology_schema
    await ensure_ontology_schema(pool)
    async with pool.acquire() as c:
        for item in draft["concepts"]:
            cid = await c.fetchval(
                """INSERT INTO ontology_concepts (name, description, parent, pii)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (name) DO UPDATE
                     SET parent = EXCLUDED.parent, pii = EXCLUDED.pii
                   RETURNING id""",
                item["name"], item.get("description"), item.get("parent"), bool(item.get("pii")))
            for t in item.get("aliases") or []:
                await c.execute(
                    "INSERT INTO concept_terms (concept_id, term) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    cid, t)


def test_schema_is_idempotent_and_import_round_trips():
    from app.api.ontology import ensure_ontology_schema, load_concepts

    async def run():
        pool = await _fresh_pool()
        try:
            await ensure_ontology_schema(pool)
            await ensure_ontology_schema(pool)  # second call must be a no-op
            await _import(pool, DRAFT)
            concepts = await load_concepts(pool)
            by_name = {c["name"]: c for c in concepts}
            assert set(by_name) == {"Deductible", "UB-04", "Policyholder"}
            assert sorted(by_name["UB-04"]["terms"]) == ["hospital inpatient bill", "ub04"]
            assert by_name["Policyholder"]["pii"] is True
        finally:
            await pool.close()

    asyncio.run(run())


def test_reimport_upserts_without_duplicating_terms():
    from app.api.ontology import load_concepts

    async def run():
        pool = await _fresh_pool()
        try:
            await _import(pool, DRAFT)
            # Re-import with a flipped pii flag and one new alias.
            updated = {"concepts": [
                {"name": "Deductible", "aliases": ["excess", "self-insured retention"], "pii": True},
            ]}
            await _import(pool, updated)
            by_name = {c["name"]: c for c in await load_concepts(pool)}
            assert by_name["Deductible"]["pii"] is True                      # upserted
            assert sorted(by_name["Deductible"]["terms"]) == ["excess", "self-insured retention"]
            assert len(by_name) == 3                                        # others untouched
        finally:
            await pool.close()

    asyncio.run(run())


def test_delete_cascades_terms():
    from app.api.ontology import load_concepts

    async def run():
        pool = await _fresh_pool()
        try:
            await _import(pool, DRAFT)
            async with pool.acquire() as c:
                await c.execute("DELETE FROM ontology_concepts WHERE name = 'UB-04'")
                orphans = await c.fetchval(
                    "SELECT count(*) FROM concept_terms ct "
                    "LEFT JOIN ontology_concepts oc ON oc.id = ct.concept_id WHERE oc.id IS NULL")
            assert orphans == 0
            assert {c["name"] for c in await load_concepts(pool)} == {"Deductible", "Policyholder"}
        finally:
            await pool.close()

    asyncio.run(run())


def test_loaded_shape_drives_expansion_end_to_end():
    """DB → load_concepts → expand_query_text: the real jargon path from the PoC."""
    from app.api.ontology import expand_query_text, load_concepts

    async def run():
        pool = await _fresh_pool()
        try:
            await _import(pool, DRAFT)
            concepts = await load_concepts(pool)
            q, matched = expand_query_text("which form covers a hospital inpatient bill", concepts)
            assert [m["name"] for m in matched] == ["UB-04"]
            assert "ub04" in q                      # code variant added for retrieval
            # PII-tagged concept fires and reports its flag for the UI.
            _, m2 = expand_query_text("can the insured cancel", concepts)
            assert m2 and m2[0] == {"name": "Policyholder", "pii": True,
                                    "added": ["Policyholder", "homeowner"]}
        finally:
            await pool.close()

    asyncio.run(run())
