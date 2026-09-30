"""Live rehearsal of docs/DEMO_SCRIPT.md, run INSIDE the backend pod against localhost.

How it was run (2026-10-01): base64 this file into an SSM command on the live node,
`kubectl cp` it into the backend pod, then from the app directory:
    cd $(dirname $(python -c "import main;print(main.__file__)")); PYTHONPATH=. python /tmp/x.py
It mints an admin session in-pod (the same way CI's install jobs do), creates two
service accounts, a collection, a chunk rule and a zero budget, prints each demo step,
and deletes everything it created in `finally`. All names start with demo-rehearsal /
demo_rehearsal. Creates and deletes live data: run only with the owner's approval.
"""

import asyncio, json, time, urllib.request, urllib.error

BASE = "http://localhost:8000"
COLL = "demo_rehearsal_handbook"


def admin_token():
    from app.api.auth import _create_token, _ensure_admin_exists, _get_pool

    async def m():
        await _ensure_admin_exists()
        p = await _get_pool()
        async with p.acquire() as c:
            r = await c.fetchrow("SELECT id, username, role FROM users WHERE role='admin' "
                                 "AND auth_method='local' AND is_active ORDER BY created_at LIMIT 1")
        return _create_token(str(r["id"]), r["username"], r["role"])
    return asyncio.run(m())


ADMIN = admin_token()


def call(method, path, body=None, token=ADMIN, ok=(200, 201, 204)):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = raw[:300].decode(errors="replace")
    if ok and status not in ok:
        raise RuntimeError(f"{method} {path} -> {status}: {str(data)[:300]}")
    return status, data


created = {"accounts": [], "collection": False, "budget_users": []}
report = []
try:
    # 1. two agents
    ids, keys = {}, {}
    for who, dept in (("hr", "hr"), ("sales", "sales")):
        _, acct = call("POST", "/api/service-accounts", {"name": f"demo-rehearsal-{who}"})
        created["accounts"].append(acct["id"])
        ids[who] = acct
        _, k = call("POST", f"/api/service-accounts/{acct['id']}/keys",
                    {"name": "rehearsal", "scopes": ["knowledge:read", "ai:generate"],
                     "expires_in_days": 1})
        keys[who] = k["key"]
        call("PATCH", f"/api/auth/users/{acct['id']}", {"attributes": {"department": dept}})
    report.append("1 accounts+keys: ok")

    # 2. one collection, both departments' documents
    call("POST", "/api/ai/collections", {"name": COLL})
    created["collection"] = True
    call("POST", f"/api/ai/collections/{COLL}/ingest", {"documents": [
        {"source": "hr/leave.md", "metadata": {"dept": "hr"},
         "text": "Parental leave is 16 weeks at full pay. Salary bands are reviewed every March."},
        {"source": "sales/pricing.md", "metadata": {"dept": "sales"},
         "text": "Enterprise discounts above 20 percent need VP approval. Q4 quota is 1.2M per rep."},
        {"source": "all/holidays.md", "metadata": {"dept": "hr"},
         "text": "The office is closed on Chuseok and Seollal."}]})
    for who in ("hr", "sales"):
        call("POST", f"/api/ai/collections/{COLL}/members",
             {"username": ids[who]["username"], "role": "reader"})
    report.append("2 collection+ingest+members: ok")

    # a. no rule: sales sees the HR salary passage
    _, s = call("POST", "/api/ai/search", {"collection": COLL, "query": "salary review", "k": 3},
                token=keys["sales"])
    before = [h["source"] for h in s["results"]]
    report.append(f"a no rule, sales search: {before}")

    # b. the rule
    call("PUT", f"/api/ai/collections/{COLL}/chunk-access",
         {"metadata_key": "dept", "user_attribute": "department"})

    # c. same question, two agents
    for who in ("hr", "sales"):
        _, r = call("POST", "/api/ai/rag", {"collection": COLL,
                                           "question": "When are salaries reviewed?"},
                    token=keys[who])
        cited = [c.get("source") for c in r.get("citations", [])]
        report.append(f"c {who}: cited={cited} answer={str(r.get('answer'))[:110]!r}")

    # d. budget 0 -> 402
    created["budget_users"].append(ids["sales"]["id"])
    call("PUT", f"/api/settings/ai/budgets/{ids['sales']['id']}", {"max_budget": 0})
    time.sleep(3)
    st, body = call("POST", "/api/ai/rag", {"collection": COLL,
                                           "question": "What is the Q4 quota?"},
                    token=keys["sales"], ok=None)
    report.append(f"d sales after cap 0: HTTP {st} {str(body)[:120]}")

    # e. audit
    _, a = call("GET", "/api/audit/tool-calls?limit=12")
    mine = [r for r in a["rows"] if str(r.get("actor_username", "")).startswith("svc-demo-rehearsal")
            or "demo-rehearsal" in str(r.get("actor_username", ""))]
    for r in mine[:6]:
        report.append(f"e audit: {r['actor_username']} {r['tool']} {r['outcome']} "
                      f"hits={r.get('hit_count')} withheld={r.get('chunks_withheld')} "
                      f"cited={r.get('citation_sources')}")
    if not mine:
        report.append(f"e audit: no rehearsal rows among {[r.get('actor_username') for r in a['rows']]}")
finally:
    cleanup = []
    for uid in created["budget_users"]:
        cleanup.append(("budget", call("PUT", f"/api/settings/ai/budgets/{uid}",
                                       {"max_budget": None}, ok=None)[0]))
    if created["collection"]:
        cleanup.append(("collection", call("DELETE", f"/api/ai/collections/{COLL}", ok=None)[0]))
    for aid in created["accounts"]:
        cleanup.append(("account", call("DELETE", f"/api/service-accounts/{aid}", ok=None)[0]))
    report.append(f"cleanup: {cleanup}")
    print("\n".join(report))
