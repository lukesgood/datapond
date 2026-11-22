"""concept_bindings rows (migration 0031). See app/semantic/concepts.py for what they mean."""
from typing import Iterable, List, Optional


def _row(r) -> dict:
    d = dict(r)
    return {"id": d["id"], "concept": d["concept"], "catalog": d["catalog"],
            "namespace": d["namespace"], "table": d["table_name"], "column": d["column_name"],
            "role": d["role"], "filter_sql": d["filter_sql"], "status": d["status"],
            "source": d["source"], "evidence": d["evidence"],
            "proposed_by_name": d.get("proposed_by_name"),
            "decided_by_name": d.get("decided_by_name"),
            "decided_at": d["decided_at"].isoformat() if d.get("decided_at") else None}


_SELECT = ("SELECT b.*, oc.name AS concept FROM concept_bindings b "
           "JOIN ontology_concepts oc ON oc.id = b.concept_id ")


async def list_bindings(pool, statuses: Optional[Iterable[str]] = None) -> List[dict]:
    wanted = list(statuses) if statuses else None
    async with pool.acquire() as c:
        rows = await c.fetch(
            _SELECT + "WHERE $1::text[] IS NULL OR b.status = ANY($1::text[]) "
            "ORDER BY oc.name, b.catalog, b.namespace, b.table_name, b.column_name, b.id", wanted)
    return [_row(r) for r in rows]


async def get_binding(pool, binding_id: int) -> Optional[dict]:
    async with pool.acquire() as c:
        r = await c.fetchrow(_SELECT + "WHERE b.id = $1", binding_id)
    return _row(r) if r else None


async def concept_id(pool, name: str):
    async with pool.acquire() as c:
        return await c.fetchval("SELECT id FROM ontology_concepts WHERE name = $1", name)


async def upsert_binding(pool, *, concept_id, catalog, namespace, table, column, role,
                         filter_sql, status, source, evidence, actor_id, actor_name) -> int:
    """Insert, or move an existing identical binding to `status` (a rejected suggestion
    approved later, a retired binding brought back). Who proposed it stays; who decided
    is recorded when the status is a decision."""
    decided = status != "proposed"
    async with pool.acquire() as c:
        return await c.fetchval(
            """INSERT INTO concept_bindings
                 (concept_id, catalog, namespace, table_name, column_name, role, filter_sql,
                  status, source, evidence, proposed_by, proposed_by_name,
                  decided_by, decided_by_name, decided_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::uuid,$12::text,
                       CASE WHEN $13::boolean THEN $11::uuid END,
                       CASE WHEN $13::boolean THEN $12::text END,
                       CASE WHEN $13::boolean THEN now() END)
               ON CONFLICT (concept_id, catalog, namespace, table_name, column_name, role,
                            COALESCE(filter_sql, ''))
               DO UPDATE SET status = EXCLUDED.status, source = EXCLUDED.source,
                             evidence = EXCLUDED.evidence,
                             decided_by = EXCLUDED.decided_by,
                             decided_by_name = EXCLUDED.decided_by_name,
                             decided_at = EXCLUDED.decided_at
               RETURNING id""",
            concept_id, catalog, namespace, table, column, role, filter_sql, status, source,
            evidence, actor_id, actor_name, decided)


async def decide(pool, binding_id: int, *, from_status: str, to_status: str,
                 actor_id, actor_name) -> bool:
    """Move one binding from `from_status` to `to_status`; False if it was not there."""
    async with pool.acquire() as c:
        done = await c.execute(
            "UPDATE concept_bindings SET status = $3, decided_by = $4, decided_by_name = $5, "
            "decided_at = now() WHERE id = $1 AND status = $2",
            binding_id, from_status, to_status, actor_id, actor_name)
    return done == "UPDATE 1"
