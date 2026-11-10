"""End-to-end proof that a database source is a Trino catalog (Phase 2). Runs INSIDE the
backend pod (`kubectl exec -i deploy/backend -- python - < this file`) against the chart
installed with helm/datapond/ci/values-multicatalog.yaml: in-cluster PostgreSQL, Trino,
Polaris and MinIO.

Seven checks, in order, each printing what it saw; the first failure exits non-zero:
  1. the e-commerce sample is created as a PostgreSQL source and becomes a catalog
  2. the engine restarts to load it, and comes back
  3. the registry lists it as trino_source; the connection lists its tables
  4. a sync of public.orders runs as Trino SQL and lands every row in Iceberg
  5. the lake copy and the live source agree (federation)
  6. a grant hides the catalog from an ungranted viewer; removing it reopens it
  7. deleting the connection removes the catalog and the engine comes back again
"""
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"
CATALOG = "src_sample_e_commerce_db"
TABLE = "public.orders"


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log("FAIL: " + msg)
    sys.exit(1)


# ── two sessions: an admin, minted the way the other CI jobs do, and a viewer ───
async def _tokens():
    from app.api.auth import _create_token, _ensure_admin_exists, _get_pool, _hash_password
    await _ensure_admin_exists()
    pool = await _get_pool()
    async with pool.acquire() as c:
        admin = await c.fetchrow("SELECT id,username,role FROM users WHERE role='admin' LIMIT 1")
        viewer_id = str(uuid.uuid4())
        await c.execute(
            "INSERT INTO users (id, email, username, password_hash, display_name, role, is_active) "
            "VALUES ($1::uuid, $2, $3, $4, 'CI viewer', 'viewer', true) "
            "ON CONFLICT (username) DO UPDATE SET role='viewer', is_active=true",
            viewer_id, "ci-viewer@example.invalid", "ci-viewer", _hash_password(uuid.uuid4().hex))
        viewer = await c.fetchrow("SELECT id,username,role FROM users WHERE username='ci-viewer'")
    return (str(admin["id"]), admin["username"],
            _create_token(str(admin["id"]), admin["username"], admin["role"]),
            _create_token(str(viewer["id"]), viewer["username"], viewer["role"]))


ADMIN_ID, ADMIN_USER, ADMIN, VIEWER = asyncio.run(_tokens())


def call(method, path, body=None, timeout=600, token=None):
    """(status, parsed body) — an HTTP error is a result, not an exception."""
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + (token or ADMIN), "Content-Type": "application/json"})
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


def engine():
    st, b = call("GET", "/api/connectors/engine", timeout=30)
    return b if st == 200 else None


def wait_engine_ready(seconds=240):
    eventually("engine restarting", lambda: (engine() or {}).get("restarting") is True, seconds=30, every=2)
    log("engine: restarting")
    eventually("engine ready again",
               lambda: (lambda s: s and s.get("ready") is True and not s.get("restarting"))(engine()),
               seconds=seconds)
    log("engine: ready")


def count(sql, token=None):
    st, b = call("POST", "/api/queries/execute", {"query": sql, "save_history": False}, token=token)
    return st, b


# ── 0. the stack is up ────────────────────────────────────────────────────────
ready = json.load(urllib.request.urlopen(BASE + "/health/ready", timeout=10))
if ready.get("ready") is not True:
    fail(f"backend not ready: {ready}")
eng = engine()
if not eng or eng.get("engine") != "trino":
    fail(f"GET /api/connectors/engine -> {eng}")
log(f"engine status before: {eng}")

# ── 1. the SQL sample is a PostgreSQL source and a Trino catalog ─────────────
st, b = call("POST", "/api/connectors/sample-sources", {"kinds": ["postgresql"]})
if st != 200:
    fail(f"POST /api/connectors/sample-sources -> {st} {b}")
result = next((r for r in b.get("results", []) if r["kind"] == "postgresql"), None)
if not result or result.get("status") not in ("active", "created", "updated"):
    fail(f"sample result: {result}")
if result.get("catalog") != CATALOG:
    fail(f"sample catalog is {result.get('catalog')!r}, want {CATALOG!r}: {result}")
if result.get("engine_restarting") is not True:
    fail(f"sample did not report engine_restarting: {result}")
CONN = result["id"]
log(f"sample source {CONN}: status={result['status']} catalog={CATALOG} engine_restarting=True")

# ── 2. the engine restarts to load the catalog, and comes back ───────────────
wait_engine_ready()

# ── 3. the registry lists it; the connection lists the sample's tables ────────
st, b = call("GET", "/api/catalogs")
entry = next((c for c in b.get("catalogs", []) if c["name"] == CATALOG), None)
if st != 200 or not entry or entry.get("kind") != "trino_source":
    fail(f"GET /api/catalogs -> {st}; {CATALOG} entry: {entry}")
log(f"registry: {CATALOG} kind={entry['kind']} enabled={entry.get('enabled')}")


def tables():
    st, b = call("GET", f"/api/connectors/{CONN}/tables")
    names = {t["name"] if isinstance(t, dict) else t for t in b.get("tables", [])} if st == 200 else set()
    return names if TABLE in names else None


names = eventually("connection listing public.orders through Trino", tables, seconds=120)
log(f"tables through the catalog: {len(names)} incl. {TABLE}")

# ── 4. sync public.orders: Trino writes Iceberg; every row lands ─────────────
from app.sample_data import ORDERS  # noqa: E402
WANT = len(ORDERS)
st, b = call("POST", f"/api/connectors/{CONN}/sync", {"source_table": TABLE, "sync_mode": "full"})
if st != 200 or str(b.get("status", "")).lower() not in ("success", "completed"):
    fail(f"sync -> {st} {b}")
rows = int(b.get("rows_processed") or 0)
if rows < WANT:
    fail(f"sync processed {rows} rows, the sample has {WANT}: {b}")
log(f"sync: {rows} rows (sample has {WANT})")

st, b = count("SELECT count(*) FROM iceberg.default.orders")
if st != 200 or int(b["rows"][0][0]) != WANT:
    fail(f"iceberg.default.orders count -> {st} {b}")
log(f"iceberg.default.orders has {WANT} rows")

# ── 4b. incremental on a timestamptz watermark: the second run binds the stored
#        watermark CAST to the column's type (text would fail: no varchar → timestamp) ──
INC = {"source_table": TABLE, "sync_mode": "incremental", "incremental_column": "ordered_at"}
st, b = call("POST", f"/api/connectors/{CONN}/sync", INC)
if st != 200 or str(b.get("status", "")).lower() not in ("success", "completed"):
    fail(f"incremental sync (first run) -> {st} {b}")
if int(b.get("rows_processed") or 0) != WANT:
    fail(f"incremental first run processed {b.get('rows_processed')} rows, expected every one ({WANT}): {b}")
st, b = call("POST", f"/api/connectors/{CONN}/sync", INC)
if st != 200 or str(b.get("status", "")).lower() not in ("success", "completed"):
    fail(f"incremental sync (second run, watermark bound) -> {st} {b}")
if int(b.get("rows_processed") or 0) != 0:
    fail(f"incremental second run processed {b.get('rows_processed')} rows; nothing is newer than the watermark: {b}")
log("incremental: first run appended every row, second run (watermark cast to timestamp) found none newer")
st, b = count("SELECT count(*) FROM iceberg.default.orders")
if st != 200 or int(b["rows"][0][0]) != 2 * WANT:
    fail(f"iceberg.default.orders after full + incremental append -> {st} {b}")

# ── 5. federation: the live source answers through its catalog ───────────────
FED = f"SELECT count(*) FROM {CATALOG}.public.orders"
st, b = count(FED)
if st != 200 or int(b["rows"][0][0]) != WANT:
    fail(f"{FED} -> {st} {b}")
log(f"federated count from {CATALOG} = {WANT}")

# ── 6. sharing the source hides its catalog from an ungranted viewer ─────────
# The catalog's grants are the connection's share list: editing them directly is
# refused, sharing the source writes them.
st, b = call("PUT", f"/api/catalogs/{CATALOG}/grants",
             {"grants": [{"kind": "user", "principal": ADMIN_ID}]})
if st != 409:
    fail(f"PUT grants on a source catalog should be refused (409), got {st} {b}")
st, b = call("POST", f"/api/connectors/{CONN}/members", {"username": ADMIN_USER, "role": "reader"})
if st != 200:
    fail(f"POST members -> {st} {b}")
st, b = call("GET", f"/api/catalogs/{CATALOG}/grants")
if st != 200 or b.get("restricted") is not True:
    fail(f"grants after sharing -> {st} {b}")


def refused():
    st, b = count(FED, token=VIEWER)
    return (st, str(b.get("detail", ""))) if 400 <= st < 500 else None


st, detail = eventually("viewer refused on the granted catalog", refused, seconds=90)
if "src_sample" in detail:
    fail(f"the refusal names the hidden catalog: {detail}")
log(f"viewer refused ({st}) without the catalog name: {detail[:120]}")

st, b = call("DELETE", f"/api/connectors/{CONN}/members?username={ADMIN_USER}")
if st != 200:
    fail(f"DELETE members -> {st} {b}")
st, b = call("GET", f"/api/catalogs/{CATALOG}/grants")
if st != 200 or b.get("restricted") is not False:
    fail(f"grants after unsharing -> {st} {b}")


def allowed():
    st, b = count(FED, token=VIEWER)
    return b if st == 200 and int(b["rows"][0][0]) == WANT else None


eventually("viewer allowed once the catalog is open again", allowed, seconds=90)
log("viewer allowed after the source was unshared")

# ── 7. deleting the connection removes the catalog; the engine comes back ────
st, b = call("DELETE", f"/api/connectors/{CONN}")
if st != 200:
    fail(f"DELETE connection -> {st} {b}")
log(f"deleted connection: catalog={b.get('catalog')} engine_restarting={b.get('engine_restarting')}")
st, b = call("GET", "/api/catalogs")
if any(c["name"] == CATALOG for c in b.get("catalogs", [])):
    fail(f"{CATALOG} still in the registry after delete")
wait_engine_ready()

log("PASS: a Trino-backed source registered, restarted the engine, synced, federated, governed and removed")
