"""Concept-binding evaluation for /ai/sql: the same questions with and without concepts.

Runs inside the backend container (python evals/concept_eval.py [--refs-only] [--attempts N]).
For each question in concept_questions.json and each attempt, /ai/sql's own generator
(`_generate_sql_impl`) is called twice: arm `off` with no concepts (concept_context.for_caller
returns nothing, so no concept block, no metric aliases, no join check), arm `on` as
deployed. The generated SQL and the reference SQL are executed read-only on Trino and the
results compared like the 2026-10-15 metric evaluation. The gateway's response cache is
bypassed (`cache: {"no-cache": true}`) so that attempts are independent samples: row multisets, column order
ignored, numbers rounded to 2 decimals, strict otherwise.

`--schema obf` repeats it on the same data shown under legacy-style names
(obf_schema.json: iceberg.erp.TB_ORD.BUYER_NO is orders.customer_id). The model sees only
the renamed schema; its SQL is translated back by name, then validated and executed on
the real tables. Concepts are the deployed bindings renamed the same way. Metrics are left
out in both arms there, since their definitions name the real tables. Nothing is written.

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


class Obf:
    """The renamed view of the lake and the translation back to real names."""

    def __init__(self, spec):
        self.ns = spec["namespace"]
        self.tables = spec["tables"]
        self.questions = {int(k): v for k, v in spec.get("questions", {}).items()}
        self.table_back = {v["as"].lower(): real for real, v in self.tables.items()}
        self.col_back = {oc.lower(): rc for v in self.tables.values() for rc, oc in v["cols"].items()}
        self.col_table = {oc.lower(): v["as"].lower() for v in self.tables.values() for oc in v["cols"].values()}

    def to_real(self, sql):
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read="trino")
        # An unqualified renamed column was unambiguous (every renamed name belongs to one
        # table); its real name (`id`) may not be. Qualify it with its table's alias first.
        ref = {}
        for t in tree.find_all(exp.Table):
            if t.name.lower() in self.table_back and not t.alias:
                # keep the renamed name as an alias, so `TB_ORD.x` still resolves
                t.set("alias", exp.TableAlias(this=exp.to_identifier(t.name)))
            ref.setdefault(t.name.lower(), t.alias_or_name)
        for c in tree.find_all(exp.Column):
            owner = self.col_table.get(c.name.lower())
            if not c.table and owner in ref:
                c.set("table", exp.to_identifier(ref[owner]))
            elif c.table and c.table.lower() in self.table_back:
                # iceberg.erp.TB_DLV.FROM_SITE: the table keeps its renamed name as alias
                c.set("db", None)
                c.set("catalog", None)
        for t in tree.find_all(exp.Table):
            real = self.table_back.get(t.name.lower())
            if real:
                t.set("this", exp.to_identifier(real))
                t.set("db", exp.to_identifier("default"))
                t.set("catalog", exp.to_identifier("iceberg"))
        for c in tree.find_all(exp.Column):
            real = self.col_back.get(c.name.lower())
            if real:
                c.set("this", exp.to_identifier(real))
        return tree.sql(dialect="trino")

    def schema_text(self, types):
        lines = ["Available tables (catalog: iceberg):"]
        for real, v in self.tables.items():
            cols = ", ".join(f"{oc} ({types.get((real, rc), 'varchar')})" for rc, oc in v["cols"].items())
            lines.append(f"  iceberg.{self.ns}.{v['as']}: {cols}")
        return "\n".join(lines)

    def concepts(self, real_concepts):
        """The deployed bindings under the renamed tables; bindings elsewhere drop out."""
        import sqlglot
        from sqlglot import exp
        out = []
        for c in real_concepts:
            bs = []
            for b in c["bindings"]:
                t = self.tables.get(b["table"])
                if b["catalog"] != "iceberg" or b["namespace"] != "default" or not t or b["column"] not in t["cols"]:
                    continue
                f = b["filter_sql"]
                if f:
                    tree = sqlglot.parse_one(f, read="trino")
                    for col in tree.find_all(exp.Column):
                        if col.name in t["cols"]:
                            col.set("this", exp.to_identifier(t["cols"][col.name]))
                    f = tree.sql(dialect="trino")
                bs.append(dict(b, namespace=self.ns, table=t["as"].lower(),
                               column=t["cols"][b["column"]].lower(), filter_sql=f))
            out.append(dict(c, bindings=bs))
        return out


def column_types():
    from app.api.trino_util import trino_conn
    cur = trino_conn(catalog="iceberg", timeout=60).cursor()
    cur.execute("SELECT table_name, column_name, data_type FROM iceberg.information_schema.columns "
                "WHERE table_schema = 'default'")
    return {(t, c): ty for t, c, ty in cur.fetchall()}


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
    ap.add_argument("--schema", choices=("real", "obf"), default="real")
    ap.add_argument("--rescore", type=str, default="",
                    help="re-execute and re-score the SQL in an earlier output file; no model calls")
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
    if args.rescore:
        await rescore(args, qs, refs, user)
        return

    import httpx
    import app.api.ai_sql as m
    from app.semantic import concept_feedback
    concept_feedback.ENABLED = False      # an evaluation is not use; keep it out of the feedback
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
    obf = None
    if args.schema == "obf":
        obf = Obf(json.load(open(os.path.join(HERE, "obf_schema.json"))))
        text = obf.schema_text(column_types())
        renamed = obf.concepts(await real(user))
        m._get_schema_context = lambda: text
        real_validate = m.validate_sql
        m.validate_sql = lambda sql: real_validate(obf.to_real(sql))

        async def no_metrics(user, catalog=None):
            return []
        context.for_caller = no_metrics

        async def real(user):          # noqa: F811 — the `on` arm gets the renamed bindings
            return renamed
        print(f"CONTEXT schema=obf tables={len(obf.tables)} concepts={len(renamed)} "
              f"bindings={sum(len(c['bindings']) for c in renamed)}", flush=True)
    else:
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
                    question = (obf.questions.get(q["id"], q["q"]) if obf else q["q"])
                    res = await m._generate_sql_impl(m.AskRequest(question=question), user)
                    rec.update(sql=" ".join((res.sql or "").split()),
                               concepts=[c["name"] for c in (res.concepts_provided or [])],
                               warnings=list(res.concept_warnings or []))
                    try:
                        sql = obf.to_real(res.sql) if obf else res.sql
                        rec["ok"] = canon(run_sql(sql)) == refs[q["id"]]
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


async def rescore(args, qs, refs, user):
    """Re-score saved attempts (after a fix to the translation) and, for both arms, count
    statements that join keys of two different concepts — what the join check looks for."""
    from app.semantic import concept_context
    obf = Obf(json.load(open(os.path.join(HERE, "obf_schema.json")))) if args.schema == "obf" else None
    concepts = await concept_context.for_caller(user)
    if obf:
        concepts = obf.concepts(concepts)
    score, mixed, per_q = {"off": 0, "on": 0}, {"off": 0, "on": 0}, {}
    for line in open(args.rescore):
        if not line.startswith("R "):
            continue
        r = json.loads(line[2:])
        if r["id"] not in refs:
            continue
        ok = False
        if r.get("sql"):
            try:
                sql = obf.to_real(r["sql"]) if obf else r["sql"]
                ok = canon(run_sql(sql)) == refs[r["id"]]
            except Exception as e:
                r["err2"] = str(e)[:160]
            bad = concept_context.join_conflicts(r["sql"], concepts, "trino", "iceberg")
            if bad:
                mixed[r["arm"]] += 1
                print(f"MIXED Q{r['id']} {r['arm']} a{r['attempt']}: {bad}")
        if r.get("err2"):
            print(f"ERR Q{r['id']} {r['arm']} a{r['attempt']}: {r['err2']}")
        score[r["arm"]] += ok
        per_q.setdefault(r["id"], {"off": 0, "on": 0})[r["arm"]] += ok
    n = len(per_q) * args.attempts
    print(f"RESCORE off {score['off']}/{n}  on {score['on']}/{n}  mixed-concept joins off {mixed['off']} on {mixed['on']}")
    for qid, s in sorted(per_q.items()):
        print(f"Q{qid:>2} off {s['off']}/{args.attempts} on {s['on']}/{args.attempts}")


if __name__ == "__main__":
    asyncio.run(main())
