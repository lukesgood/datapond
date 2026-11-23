"""Which of a source's tables a sync runs, and what happened to jobs the source no longer has.

Found live 2026-11-23: a 2.5 source lists its tables qualified (`public.customers`), but
a job saved earlier kept the bare name (`customers`) with the job's settings on it —
its PII columns among them. The sync matched jobs by exact name, so `public.customers`
looked like a table with no job, and "tables not yet in the DB are enabled by default"
would have synced it — into the same lake table, without the masks. The full "Sync now"
did worse: it synced every listed table and ignored the enabled flag altogether.

Rules here:
- a bare job name that matches exactly one qualified table is renamed to it (healed), so
  its settings follow the table;
- a source synced for the first time (no jobs yet) adopts every table it lists, as the
  setup flow and the samples expect; after that a new table is reported as new and
  waits for a person to enable it — it never syncs unmasked on its own;
- a job whose table the source no longer lists is orphaned: reported, never run.
"""
from typing import Dict, Iterable, List


def legacy_renames(discovered: Iterable[str], job_names: Iterable[str]) -> Dict[str, str]:
    """{bare job name: the one qualified table it means}. A bare name that matches no
    table, or several (`a.customers` and `b.customers`), is left alone."""
    tables = [t for t in discovered if "." in t]
    names = set(job_names)
    out = {}
    for name in names:
        if "." in name:
            continue
        hits = [t for t in tables if t.rsplit(".", 1)[-1].lower() == name.lower()]
        if len(hits) == 1 and hits[0] not in names:
            out[name] = hits[0]
    return out


def plan(discovered: List[str], jobs: Dict[str, bool]) -> dict:
    """{sync, new, skipped, orphaned, first_run} for discovered table names and
    {job source_table: enabled}. Names are compared exactly; heal first."""
    first_run = not jobs
    listed = set(discovered)
    return {
        "first_run": first_run,
        "sync": [t for t in discovered if (jobs[t] if t in jobs else first_run)],
        "new": [] if first_run else [t for t in discovered if t not in jobs],
        "skipped": [t for t in discovered if t in jobs and not jobs[t]],
        "orphaned": sorted(j for j in jobs if j not in listed),
    }


async def heal(pool, connection_id, discovered: List[str]) -> Dict[str, str]:
    """Rename bare job names in place (connector_sync_jobs.source_table); returns what
    was renamed. Quality and history rows keep the name they were written under."""
    import uuid
    cid = uuid.UUID(str(connection_id))
    async with pool.acquire() as c:
        names = [r[0] for r in await c.fetch(
            "SELECT source_table FROM connector_sync_jobs WHERE connection_id = $1", cid)]
        renames = legacy_renames(discovered, names)
        for old, new in renames.items():
            await c.execute(
                "UPDATE connector_sync_jobs SET source_table = $3, updated_at = now() "
                "WHERE connection_id = $1 AND source_table = $2 AND NOT EXISTS ("
                "SELECT 1 FROM connector_sync_jobs WHERE connection_id = $1 AND source_table = $3)",
                cid, old, new)
    return renames
