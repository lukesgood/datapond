"""End-to-end proof that DataPond handles more than one catalog. Runs INSIDE the backend
pod (piped through `kubectl exec -i deploy/backend -- python - < this file`), against
the chart installed with helm/datapond/ci/values-multicatalog.yaml: two Polaris
catalogs, `iceberg` (the default) and `catb`, both queryable through Trino.

Every check asserts and prints; the first failure exits non-zero with what was seen.
"""
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
DEFAULT, SECOND = "iceberg", "catb"


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log("FAIL: " + msg)
    sys.exit(1)


# ── an admin session, minted the way the other CI jobs do ────────────────────
async def _token():
    from app.api.auth import _create_token, _ensure_admin_exists, _get_pool
    await _ensure_admin_exists()      # the first admin exists only after a first sign-in
    pool = await _get_pool()
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT id,username,role FROM users WHERE role='admin' LIMIT 1")
    return _create_token(str(r["id"]), r["username"], r["role"])


TOKEN = asyncio.run(_token())


def call(method, path, body=None, timeout=120):
    """(status, parsed body) — an HTTP error is a result, not an exception."""
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"detail": raw}


def eventually(what, fn, seconds=180, every=5):
    """Call fn() until it returns a truthy value or `seconds` pass. Caches (the schema
    tree in Valkey, the resolver index) have a 60 s TTL, so a check made right after a
    change may see the old answer once."""
    deadline, last = time.time() + seconds, None
    while True:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:  # noqa: BLE001 - reported below
            last = f"{type(e).__name__}: {e}"
        if time.time() > deadline:
            fail(f"{what} did not hold within {seconds}s; last seen: {last!r}")
        time.sleep(every)


def trino(sql, catalog=DEFAULT):
    from app.api.trino_util import trino_conn
    cur = trino_conn(catalog=catalog, timeout=120).cursor()
    cur.execute(sql)
    return cur.fetchall()


# ── 0. the stack is up, and Trino knows both catalogs ────────────────────────
ready = json.load(urllib.request.urlopen(BASE + "/health/ready", timeout=10))
if ready.get("ready") is not True:
    fail(f"backend not ready: {ready}")
eventually("Trino listing both catalogs",
           lambda: {DEFAULT, SECOND} <= {r[0] for r in trino("SHOW CATALOGS")}, seconds=240)
log(f"trino has catalogs {DEFAULT} and {SECOND}")

# ── 1. register the second catalog through the admin API ─────────────────────
status, body = call("POST", "/api/catalogs", {
    "name": SECOND, "kind": "polaris", "engine_catalog": SECOND,
    "config": {"warehouse": SECOND}, "is_default": False, "enabled": True})
if status != 201:
    fail(f"POST /api/catalogs -> {status} {body}")
log(f"registered {SECOND}: {body}")

# ── 2. one table only in each catalog, and one name in both ──────────────────
for cat, only, rows in ((DEFAULT, "ci_only_a", 2), (SECOND, "ci_only_b", 3)):
    values = ", ".join(f"({i}, '{cat}')" for i in range(1, rows + 1))
    trino(f"CREATE TABLE {cat}.raw.{only} AS SELECT * FROM (VALUES (1, '{cat}')) AS t(id, origin)", cat)
    trino(f"CREATE TABLE {cat}.raw.ci_orders AS "
          f"SELECT * FROM (VALUES {values}) AS t(id, origin)", cat)
log("created ci_only_a + ci_orders in iceberg, ci_only_b + ci_orders in catb")

# ── 3. /api/catalog/schemas: both catalogs, right flags, tables not merged ───
def tree():
    st, b = call("GET", "/api/catalog/schemas")
    if st != 200:
        return None
    nodes = {c["name"]: c for c in b.get("catalogs", [])}
    if not {DEFAULT, SECOND} <= set(nodes):
        return None

    def tables(node):
        return {t["name"] for s in node["schemas"] if s["name"] == "raw" for t in s["tables"]}
    a, b_ = tables(nodes[DEFAULT]), tables(nodes[SECOND])
    if not ({"ci_only_a", "ci_orders"} <= a and {"ci_only_b", "ci_orders"} <= b_):
        return None
    return nodes, a, b_


nodes, a_tables, b_tables = eventually("schema tree listing each catalog's tables", tree)
if nodes[DEFAULT].get("is_default") is not True or nodes[SECOND].get("is_default") is not False:
    fail(f"is_default flags wrong: {[(n, c.get('is_default')) for n, c in nodes.items()]}")
if "ci_only_b" in a_tables or "ci_only_a" in b_tables:
    fail(f"tables leaked across catalogs: {DEFAULT}={sorted(a_tables)} {SECOND}={sorted(b_tables)}")
log(f"tree ok: {DEFAULT} (default) {sorted(a_tables)}; {SECOND} {sorted(b_tables)}")

# ── 4. a bare name in both catalogs is ambiguous, and says where ─────────────
def ambiguity():
    st, b = call("POST", "/api/queries/execute",
                 {"query": "SELECT * FROM ci_orders", "save_history": False})
    detail = str(b.get("detail", ""))
    if st == 400 and "ambiguous" in detail:
        return detail
    return None


detail = eventually("ambiguity error for a bare name present in both catalogs", ambiguity)
for cand in (f"{DEFAULT}.raw.ci_orders", f"{SECOND}.raw.ci_orders"):
    if cand not in detail:
        fail(f"ambiguity error does not name {cand}: {detail}")
log("ambiguity error names both candidates: " + detail)

# a bare name that exists in one catalog only resolves to that catalog
st, b = call("POST", "/api/queries/execute",
             {"query": "SELECT origin FROM ci_only_b", "save_history": False})
if st != 200 or {r[0] for r in b["rows"]} != {SECOND}:
    fail(f"bare ci_only_b should resolve to {SECOND}: {st} {b}")
log(f"bare ci_only_b resolved to {SECOND}")

# ── 5. three-part names go to the catalog they name ──────────────────────────
for cat, want in ((SECOND, 3), (DEFAULT, 2)):
    st, b = call("POST", "/api/queries/execute",
                 {"query": f"SELECT id, origin FROM {cat}.raw.ci_orders ORDER BY id",
                  "save_history": False})
    if st != 200:
        fail(f"{cat}.raw.ci_orders -> {st} {b}")
    origins = {r[1] for r in b["rows"]}
    if len(b["rows"]) != want or origins != {cat}:
        fail(f"{cat}.raw.ci_orders returned {b['rows']}, want {want} rows all from {cat}")
    log(f"{cat}.raw.ci_orders -> {want} rows from {cat}")

# ── 6. the admin Test button answers for both ────────────────────────────────
for cat in (DEFAULT, SECOND):
    st, b = call("POST", f"/api/catalogs/{cat}/test")
    if st != 200 or b.get("ok") is not True or "raw" not in b.get("namespaces", []):
        fail(f"/api/catalogs/{cat}/test -> {st} {b}")
    log(f"{cat} reachable: {b['namespace_count']} namespace(s)")

st, b = call("GET", "/api/catalogs")
flags = {c["name"]: c["is_default"] for c in b.get("catalogs", [])}
if flags.get(DEFAULT) is not True or flags.get(SECOND) is not False:
    fail(f"registry flags wrong: {flags}")

log("PASS: two catalogs listed, kept apart, resolved, queried and tested")
