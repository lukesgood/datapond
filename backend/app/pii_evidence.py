"""Evidence that personal data did not reach the lake (design thinking D1).

Masking happens inside the sync's SELECT, so nothing on screen used to show a security
officer that it worked. For every synced table this reports which columns were masked at
sync time, and scans a sample of the lake table (SAMPLE_ROWS rows of each string column)
with the Korean PII detector (app/guardrails/pii_ko.py) for values that still look like
resident numbers, phone numbers, emails, cards or credentials.

Status per table: ok (no raw value in the sample), raw_found (columns listed), unverified
(the table could not be read). The evidence never repeats a raw value. Results are cached
for CACHE_SECONDS; `GET /api/governance/pii-evidence` serves them, `?format=ndjson` exports.
"""
import asyncio
import json
import time
from typing import Dict, List, Optional

from app.guardrails import pii_ko

SAMPLE_ROWS = 200
CACHE_SECONDS = 600
_cache = {"at": 0.0, "data": None}


def reset_cache() -> None:
    _cache.update(at=0.0, data=None)


def assess(table: str, configured: List[str], samples: Optional[Dict[str, list]],
           error: Optional[str] = None) -> dict:
    if samples is None:
        return {"table": table, "status": "unverified", "error": (error or "")[:300], "columns": [], "raw_columns": []}
    star = "*" in (configured or [])
    masked = {c.lower() for c in configured or []}
    cols = []
    for col, values in samples.items():
        types, raw = set(), 0
        for v in values:
            if v is None:
                continue
            found = pii_ko.detect(str(v))
            if found:
                raw += 1
                types.update(f["type"] for f in found)
        cols.append({"column": col, "masked_at_sync": star or col.lower() in masked,
                     "sampled": sum(1 for v in values if v is not None), "raw_found": raw, "types": sorted(types)})
    raw_cols = [c["column"] for c in cols if c["raw_found"]]
    return {"table": table, "status": "raw_found" if raw_cols else "ok", "error": None,
            "columns": cols, "raw_columns": raw_cols}


async def _load_jobs() -> List[dict]:
    from app.api.connectors import get_db_pool
    from app.connectors import trino_sync
    pool = await get_db_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            """SELECT j.source_table, j.target_table, j.target_catalog, j.pii_columns, j.last_run_at,
                      cc.name AS source
                 FROM connector_sync_jobs j JOIN connector_connections cc ON cc.id = j.connection_id
                WHERE j.enabled AND j.last_run_status = 'success'
                ORDER BY cc.name, j.source_table""")
    out = []
    for r in rows:
        pii = r["pii_columns"]
        if isinstance(pii, str):
            pii = json.loads(pii)
        ref = trino_sync.target_ref(r["source_table"], r["target_table"], r["target_catalog"])
        out.append({"table": ref.sql(), "source": r["source"], "source_table": r["source_table"],
                    "configured": list(pii or []),
                    "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None})
    return out


def _sample(table: str):
    """({column: [values]}, None) for the table's string columns, or (None, error)."""
    from app.api.trino_util import trino_conn
    from app.catalog_export import ident
    try:
        cat, schema, name = table.split(".")
        cur = trino_conn(timeout=60).cursor()
        cur.execute(f"SELECT column_name FROM {ident(cat)}.information_schema.columns "
                    f"WHERE table_schema = '{schema}' AND table_name = '{name}' AND data_type LIKE 'varchar%'")
        cols = [r[0] for r in cur.fetchall()]
        if not cols:
            return {}, None
        cur.execute(f"SELECT {', '.join(ident(c) for c in cols)} FROM {ident(cat)}.{ident(schema)}.{ident(name)} "
                    f"LIMIT {SAMPLE_ROWS}")
        rows = cur.fetchall()
        return {c: [row[i] for row in rows] for i, c in enumerate(cols)}, None
    except Exception as e:
        return None, str(e)


async def collect(force: bool = False) -> dict:
    if not force and _cache["data"] and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    jobs = await _load_jobs()
    tables = []
    for j in jobs:
        samples, err = await asyncio.to_thread(_sample, j["table"])
        r = assess(j["table"], j["configured"], samples, err)
        tables.append({**r, "source": j["source"], "source_table": j["source_table"], "last_run_at": j["last_run_at"]})
    summary = {"tables": len(tables), "ok": sum(t["status"] == "ok" for t in tables),
               "raw_found": sum(t["status"] == "raw_found" for t in tables),
               "unverified": sum(t["status"] == "unverified" for t in tables)}
    data = {"summary": summary, "tables": tables, "sample_rows": SAMPLE_ROWS,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _cache.update(at=time.monotonic(), data=data)
    return data


def to_ndjson(data: dict) -> str:
    return "".join(json.dumps({**t, "checked_at": data["checked_at"]}, ensure_ascii=False) + "\n" for t in data["tables"])
