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
    # The import endpoint's core (the endpoint itself is a thin auth wrapper).
    from app.api.ontology import ensure_ontology_schema, import_items
    await ensure_ontology_schema(pool)
    return await import_items(pool, draft["concepts"])


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


def test_parent_is_an_id_so_a_rename_keeps_the_tree():
    from app.api.ontology import load_concepts

    async def run():
        pool = await _fresh_pool()
        try:
            out = await _import(pool, {"concepts": [
                {"name": "VIP 고객", "parent": "고객"},          # child before its parent
                {"name": "고객", "aliases": ["customer"]},
                {"name": "고아", "parent": "없는 개념"},
            ]})
            assert out["unresolved_parents"] == ["고아"]
            by = {c["name"]: c for c in await load_concepts(pool)}
            assert by["VIP 고객"]["parent"] == "고객" and by["고아"]["parent"] is None
            async with pool.acquire() as c:
                await c.execute("UPDATE ontology_concepts SET name = '회원' WHERE name = '고객'")
            by = {c["name"]: c for c in await load_concepts(pool)}
            assert by["VIP 고객"]["parent"] == "회원"
            async with pool.acquire() as c:
                await c.execute("DELETE FROM ontology_concepts WHERE name = '회원'")
            by = {c["name"]: c for c in await load_concepts(pool)}
            assert by["VIP 고객"]["parent"] is None
        finally:
            await pool.close()

    asyncio.run(run())


def test_a_parent_cannot_make_a_cycle():
    from app.api.ontology import ParentError, parent_id_for

    async def run():
        pool = await _fresh_pool()
        try:
            await _import(pool, {"concepts": [{"name": "A"}, {"name": "B", "parent": "A"},
                                              {"name": "C", "parent": "B"}]})
            async with pool.acquire() as c:
                a = await c.fetchval("SELECT id FROM ontology_concepts WHERE name = 'A'")
                for bad in ("A", "C"):
                    with pytest.raises(ParentError):
                        await parent_id_for(c, bad, a)
                with pytest.raises(ParentError):
                    await parent_id_for(c, "Z", a)
                assert await parent_id_for(c, "", a) is None
        finally:
            await pool.close()

    asyncio.run(run())


def test_migration_moves_text_parents_to_ids():
    from pathlib import Path

    async def run():
        pool = await _fresh_pool()
        try:
            async with pool.acquire() as c:
                await c.execute("""CREATE TABLE ontology_concepts (
                    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text UNIQUE NOT NULL,
                    description text, parent text, pii boolean NOT NULL DEFAULT false,
                    created_at timestamptz DEFAULT now())""")
                await c.execute("INSERT INTO ontology_concepts (name, parent) VALUES "
                                "('고객', NULL), ('VIP 고객', '고객'), ('고아', '없음'), ('자기', '자기')")
                sql = (Path(__file__).resolve().parents[1] / "migrations/versions/0033_concept_parent_id.sql").read_text()
                await c.execute(sql)
                await c.execute(sql)                       # idempotent
                rows = dict(await c.fetch("SELECT c.name, p.name FROM ontology_concepts c "
                                          "LEFT JOIN ontology_concepts p ON p.id = c.parent_id"))
                assert rows == {"고객": None, "VIP 고객": "고객", "고아": None, "자기": None}
                cols = {r[0] for r in await c.fetch("SELECT column_name FROM information_schema.columns "
                                                     "WHERE table_name = 'ontology_concepts'")}
                assert "parent_id" in cols        # the text column stays until the contract step
        finally:
            await pool.close()

    asyncio.run(run())
