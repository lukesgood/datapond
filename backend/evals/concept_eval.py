"""Concept-binding evaluation for /ai/sql: the same questions with and without concepts.

Runs inside the backend container (python evals/concept_eval.py [--refs-only] [--attempts N]).
For each question in concept_questions.json and each attempt, /ai/sql's own generator
(`_generate_sql_impl`) is called twice: arm `off` with no concepts (concept_context.for_caller
returns nothing, so no concept block, no metric aliases, no join check), arm `on` as
deployed. The generated SQL and the reference SQL are executed read-only on Trino and the
results compared like the 2026-10-15 metric evaluation. The gateway's response cache is
bypassed (`cache: {"no-cache": true}`) so that attempts are independent samples: row multisets, column order
ignored, numbers rounded to 2 decimals, strict otherwise.

Prints one `R {json}` line per attempt and a summary. Read-only: only SELECT/WITH runs.
"""
import argparse
import asyncio
import json
import os
import time
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))


def _norm(v):
    if isinstance(v, bool) or v is None:
        return repr(v)
    if isinstance(v, (int, float, Decimal)):
        return f"{round(float(v), 2):.2f}"
    return str(v)


def canon(rows):
    return sorted(tuple(sorted(_norm(v) for v in row)) for row in rows)


def run_sql(sql):
    from app.api.trino_util import trino_conn
    head = sql.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise ValueError("not a SELECT")
    cur = trino_conn(catalog="iceberg", timeout=90).cursor()
    cur.execute(sql)
    return cur.fetchall()


async def admin_user():
    from app import catalog_registry
    from app.api.connectors import get_db_pool
    p = await get_db_pool()
    # The server loads the catalog registry at startup; a standalone process must too, or
    # metric context fails to resolve catalogs and both arms lose their metrics block.
    await catalog_registry.load(p, force=True)
    async with p.acquire() as c:
        r = await c.fetchrow("SELECT id::text, username FROM users WHERE role = 'admin' "
                             "ORDER BY created_at LIMIT 1")
    return {"id": r["id"], "username": r["username"], "role": "admin"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs-only", action="store_true")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()
    qs = json.load(open(os.path.join(HERE, "concept_questions.json")))
    if args.only:
        keep = {int(x) for x in args.only.split(",")}
        qs = [q for q in qs if q["id"] in keep]
    user = await admin_user()
    refs = {}
    for q in qs:
        rows = run_sql(q["ref"])
        refs[q["id"]] = canon(rows)
        if args.refs_only:
            print(f"REF {q['id']:>2} rows={len(rows)} sample={rows[:3]}")
    if args.refs_only:
        return

    import httpx
    import app.api.ai_sql as m
    # LiteLLM caches identical prompts for an hour, which would make attempts 2 and 3
    # copies of attempt 1. Ask it not to use the cache for these calls.
    _post = httpx.Client.post

    def post(self, url, *a, **kw):
        if str(url).endswith("/chat/completions") and isinstance(kw.get("json"), dict):
            kw["json"] = dict(kw["json"], cache={"no-cache": True})
        return _post(self, url, *a, **kw)
    httpx.Client.post = post
    from app.semantic import concept_context, context
    real = concept_context.for_caller
    # Same context as the server gives: approved metrics must load in both arms.
    print(f"CONTEXT metrics={len(await context.for_caller(user))} "
          f"concepts={len(await real(user))}", flush=True)

    async def none(user):
        return []
    score = {"off": 0, "on": 0}
    per_q = {}
    for q in qs:
        for attempt in range(1, args.attempts + 1):
            for arm in ("off", "on"):
                concept_context.for_caller = none if arm == "off" else real
                t0 = time.time()
                rec = {"id": q["id"], "kind": q["kind"], "arm": arm, "attempt": attempt}
                try:
                    res = await m._generate_sql_impl(m.AskRequest(question=q["q"]), user)
                    rec.update(sql=" ".join((res.sql or "").split()),
                               concepts=[c["name"] for c in (res.concepts_provided or [])],
                               warnings=list(res.concept_warnings or []))
                    try:
                        rec["ok"] = canon(run_sql(res.sql)) == refs[q["id"]]
                    except Exception as e:
                        rec.update(ok=False, err=f"exec: {str(e)[:200]}")
                except Exception as e:
                    rec.update(ok=False, err=f"gen: {str(e)[:200]}")
                rec["s"] = round(time.time() - t0, 1)
                score[arm] += rec["ok"]
                per_q.setdefault(q["id"], {"off": 0, "on": 0})[arm] += rec["ok"]
                print("R " + json.dumps(rec, ensure_ascii=False), flush=True)
    concept_context.for_caller = real
    n = len(qs) * args.attempts
    print(f"SUMMARY off {score['off']}/{n}  on {score['on']}/{n}")
    for qid, s in per_q.items():
        print(f"Q{qid:>2} off {s['off']}/{args.attempts} on {s['on']}/{args.attempts}")


if __name__ == "__main__":
    asyncio.run(main())
