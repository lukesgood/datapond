# Agent Onboarding Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin can create an agent identity, issue it a scoped and expiring key, see which collections it can read, and hand a developer a snippet that calls a specific collection — without leaving the product or reading a runbook.

**Architecture:** One new read endpoint (`GET /api/service-accounts/{id}/collections`) and one allowlist change in `api_surface.py` on the backend. On the frontend, pure logic goes into `frontend/lib/*.ts` (tested with `node --test`) and three components consume it: the service-account panel (scopes, expiry, collections), a new "Use from app" tab on a collection, and the dashboard step 04 as a call to action. A help guide page documents the journey.

**Tech Stack:** FastAPI, asyncpg-style SQL, Next.js App Router with shadcn/ui, `node --test` (`frontend/lib/*.test.ts`, import with explicit `.ts`).

**Spec:** `docs/superpowers/specs/2026-09-07-positioning-gap-closure-design.md` §3

## Global Constraints

- Python 3.11+ for backend tests: `cd backend && python3.12 -m pytest tests -q --ignore=tests/acceptance`. No database in tests; fake pools.
- Every mutating route needs a permission dependency (`tests/test_route_authorization_inventory.py`). This plan adds only `GET` routes.
- Service-account routes are `Depends(require_admin)`; keep that for the new one.
- Key scopes never widen: the backend computes `effective_permissions(role, scopes)` and 400s when the intersection is empty (`service_account_routes.py:125-130`). The UI only chooses within `grantable_permissions ∩ account.permissions`.
- Frontend tests: `cd frontend && npm test` runs `node --test lib/**/*.test.ts` only. Pure logic goes in `frontend/lib`.
- Frontend lint and build must stay green: `npm run lint && npm run build`.
- No `Button` inside the journey strip today; it uses `Link`. Step 04 becomes a visibly different CTA but stays a `Link` so the strip's layout code is untouched.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PQW9stoiSQnnohhnBCDEvL
  ```

---

### Task 1: `GET /api/service-accounts/{id}/collections`

**Files:**
- Modify: `backend/app/api/service_account_routes.py` (add one route after the `/usage`-style reads; the file's routes all use `Depends(require_admin)`)
- Test: `backend/tests/test_service_account_collections.py`

**Interfaces:**
- Produces: `GET /api/service-accounts/{account_id}/collections` → `{"account_id": str, "collections": [{"name": str, "access": "owner" | "reader" | "editor" | "global", "chunks": int}]}`. 404 when the account does not exist.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_service_account_collections.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth, service_account_routes as sar

_REAL_REQUIRE_ADMIN = auth.require_admin
ADMIN = {"id": "00000000-0000-0000-0000-000000000001", "username": "root", "role": "admin"}
ACCT = "22222222-2222-2222-2222-222222222222"


def _app():
    app = FastAPI()
    app.include_router(sar.router, prefix="/api")

    async def _override():
        return ADMIN
    app.dependency_overrides[_REAL_REQUIRE_ADMIN] = _override
    return app


class _Conn:
    def __init__(self, account_row, rows):
        self.account_row, self.rows, self.sql = account_row, rows, []

    async def fetchrow(self, sql, *args):
        self.sql.append(sql)
        return self.account_row

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return self.rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _patch(monkeypatch, conn):
    async def _pool():
        return _Pool(conn)
    monkeypatch.setattr(sar, "_get_pool", _pool)   # the module imports _get_pool from app.api.auth


def test_unknown_account_is_404(monkeypatch):
    _patch(monkeypatch, _Conn(None, []))
    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/collections")
    assert r.status_code == 404


def test_lists_owned_member_and_global_collections(monkeypatch):
    conn = _Conn({"id": ACCT, "auth_method": "service"},
                 [{"name": "faq", "access": "reader", "chunks": 12},
                  {"name": "mine", "access": "owner", "chunks": 3},
                  {"name": "public", "access": "global", "chunks": 0}])
    _patch(monkeypatch, conn)
    r = TestClient(_app()).get(f"/api/service-accounts/{ACCT}/collections")
    assert r.status_code == 200
    d = r.json()
    assert d["account_id"] == ACCT
    assert [c["name"] for c in d["collections"]] == ["faq", "mine", "public"]
    assert "ai_collection_members" in conn.sql[-1] and "owner_id IS NULL" in conn.sql[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_service_account_collections.py -q`
Expected: FAIL — 404 for the second test (the route does not exist yet).

- [ ] **Step 3: Implement the route**

In `backend/app/api/service_account_routes.py` the pool comes from `_get_pool` (imported at `:16` from `app.api.auth`, used at `:44,:92,:117`). Add:

```python
_ACCOUNT_COLLECTIONS_SQL = """
SELECT col.name,
       CASE WHEN col.owner_id = $1::uuid THEN 'owner'
            WHEN m.role IS NOT NULL THEN m.role
            ELSE 'global' END AS access,
       (SELECT count(*) FROM ai_chunks ch WHERE ch.collection_id = col.id) AS chunks
  FROM ai_collections col
  LEFT JOIN ai_collection_members m ON m.collection_id = col.id AND m.user_id = $1::uuid
 WHERE col.owner_id = $1::uuid OR m.user_id IS NOT NULL OR col.owner_id IS NULL
 ORDER BY col.name
"""


@router.get("/service-accounts/{account_id}/collections", dependencies=[Depends(require_admin)])
async def account_collections(account_id: str):
    """Knowledge collections this service account can read, and why.

    'owner' and 'reader'/'editor' come from ai_collections.owner_id and
    ai_collection_members; 'global' is the legacy owner_id IS NULL rule that
    knowledge:read holders can read. Grants themselves stay on the collection
    (Knowledge → Members); this is the account-side view of the same rows.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        acct = await conn.fetchrow(
            "SELECT id, auth_method FROM users WHERE id = $1::uuid AND auth_method = 'service'",
            account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Service account not found")
        rows = await conn.fetch(_ACCOUNT_COLLECTIONS_SQL, account_id)
    return {"account_id": account_id,
            "collections": [{"name": r["name"], "access": r["access"],
                             "chunks": int(r["chunks"] or 0)} for r in rows]}
```

The file's other routes declare `Depends(require_admin)` the same way (`:42,:78,:115`); keep it identical.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_service_account_collections.py tests/test_service_accounts.py tests/test_route_authorization_inventory.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/service_account_routes.py backend/tests/test_service_account_collections.py
git commit -m "feat(service-accounts): list the collections an account can read, and why"
```

---

### Task 2: Key issuance logic in `frontend/lib/service-account-keys.ts`

**Files:**
- Create: `frontend/lib/service-account-keys.ts`
- Test: `frontend/lib/service-account-keys.test.ts`

**Interfaces:**
- Produces:
  - `choosableScopes(grantable: string[], accountPermissions: string[]) -> string[]` — sorted intersection.
  - `defaultScopes(choosable: string[]) -> string[]` — `["knowledge:read","ai:generate"]` filtered to what is choosable; if that leaves nothing, the full choosable list.
  - `EXPIRY_OPTIONS: {label: string; days: number | null}[]` — 30, 90 (default), 365, null.
  - `DEFAULT_EXPIRY_DAYS = 90`
  - `keyRequestBody(name: string, scopes: string[], expiryDays: number | null) -> {name, scopes, expires_in_days?}`
  - `describeKey(k: {scopes: string[]; expires_at: string | null}) -> string` — e.g. `"knowledge:read, ai:generate · expires 2026-12-06"` or `"all role permissions · no expiry"`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/service-account-keys.test.ts
import assert from "node:assert/strict"
import { test } from "node:test"
import {
  DEFAULT_EXPIRY_DAYS, EXPIRY_OPTIONS, choosableScopes, defaultScopes, describeKey,
  keyRequestBody,
} from "./service-account-keys.ts"

test("choosable scopes are the intersection, sorted", () => {
  assert.deepEqual(
    choosableScopes(["ai:generate", "knowledge:read", "query:run", "audit:read"],
                    ["knowledge:read", "query:run", "ai:generate", "catalog:read"]),
    ["ai:generate", "knowledge:read", "query:run"],
  )
})

test("default scopes are knowledge:read + ai:generate when available", () => {
  assert.deepEqual(defaultScopes(["ai:generate", "knowledge:read", "query:run"]),
                   ["knowledge:read", "ai:generate"])
  assert.deepEqual(defaultScopes(["query:run"]), ["query:run"])
})

test("expiry defaults to 90 days and the body omits it for no-expiry", () => {
  assert.equal(DEFAULT_EXPIRY_DAYS, 90)
  assert.ok(EXPIRY_OPTIONS.some(o => o.days === 90))
  assert.deepEqual(keyRequestBody("bot key", ["ai:generate"], 90),
                   { name: "bot key", scopes: ["ai:generate"], expires_in_days: 90 })
  assert.deepEqual(keyRequestBody("bot key", [], null), { name: "bot key", scopes: [] })
})

test("describeKey names scopes and expiry, or says so when absent", () => {
  assert.equal(describeKey({ scopes: ["knowledge:read", "ai:generate"], expires_at: "2026-12-06T00:00:00Z" }),
               "knowledge:read, ai:generate · expires 2026-12-06")
  assert.equal(describeKey({ scopes: [], expires_at: null }), "all role permissions · no expiry")
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot find `./service-account-keys.ts`.

- [ ] **Step 3: Implement**

```ts
// frontend/lib/service-account-keys.ts
// Pure logic for issuing a service-account key. The panel renders these; this file
// is what node --test can reach (same split as collection-members.ts).

export const PREFERRED_DEFAULT_SCOPES = ["knowledge:read", "ai:generate"]
export const DEFAULT_EXPIRY_DAYS = 90
export const EXPIRY_OPTIONS: { label: string; days: number | null }[] = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "1 year", days: 365 },
  { label: "No expiry", days: null },
]

export function choosableScopes(grantable: string[], accountPermissions: string[]): string[] {
  const held = new Set(accountPermissions)
  return [...new Set(grantable.filter(s => held.has(s)))].sort()
}

export function defaultScopes(choosable: string[]): string[] {
  const set = new Set(choosable)
  const preferred = PREFERRED_DEFAULT_SCOPES.filter(s => set.has(s))
  return preferred.length > 0 ? preferred : [...choosable]
}

export function keyRequestBody(name: string, scopes: string[], expiryDays: number | null) {
  const body: { name: string; scopes: string[]; expires_in_days?: number } = { name, scopes }
  if (expiryDays !== null) body.expires_in_days = expiryDays
  return body
}

export function describeKey(k: { scopes: string[]; expires_at: string | null }): string {
  const scopes = k.scopes.length > 0 ? k.scopes.join(", ") : "all role permissions"
  const expiry = k.expires_at ? `expires ${k.expires_at.slice(0, 10)}` : "no expiry"
  return `${scopes} · ${expiry}`
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/service-account-keys.ts frontend/lib/service-account-keys.test.ts
git commit -m "feat(service-accounts): key issuance logic — scopes, expiry, description"
```

---

### Task 3: Service-account panel — scoped, expiring keys and the account's collections

**Files:**
- Modify: `frontend/components/settings/service-accounts.tsx` (types `:10-18`, state `:27-33`, `issueKey` `:65-80`, key rows `:214-237`, account card `:179-200`)

**Interfaces:**
- Consumes: Task 1 endpoint; Task 2 helpers; `GET /api/service-accounts` already returns `grantable_permissions` and per-account `permissions`.

- [ ] **Step 1: Extend the types and state**

In `service-accounts.tsx`:

```tsx
type Payload = { accounts: Account[]; assignable_roles: string[]; grantable_permissions: string[] }
type AccountCollection = { name: string; access: "owner" | "reader" | "editor" | "global"; chunks: number }
```

Add state:

```tsx
  const [issuing, setIssuing] = useState<Account | null>(null)   // which account's issue form is open
  const [keyName, setKeyName] = useState("")
  const [keyScopes, setKeyScopes] = useState<string[]>([])
  const [keyExpiry, setKeyExpiry] = useState<number | null>(DEFAULT_EXPIRY_DAYS)
```

and import `{ DEFAULT_EXPIRY_DAYS, EXPIRY_OPTIONS, choosableScopes, defaultScopes, describeKey, keyRequestBody } from "@/lib/service-account-keys"`.

- [ ] **Step 2: Replace `issueKey` with an open-form + submit pair**

```tsx
  const openIssue = (account: Account) => {
    const choosable = choosableScopes(data?.grantable_permissions ?? [], account.permissions)
    setIssuing(account)
    setKeyName(`${account.username} key`)
    setKeyScopes(defaultScopes(choosable))
    setKeyExpiry(DEFAULT_EXPIRY_DAYS)
  }

  const submitIssue = async () => {
    if (!issuing || busy) return
    setBusy(true)
    try {
      const res = await fetch(`/api/service-accounts/${issuing.id}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(keyRequestBody(keyName.trim() || `${issuing.username} key`, keyScopes, keyExpiry)),
      })
      if (res.ok) {
        const d = await res.json()
        setIssued({ key: d.key, account: issuing.username })
        setCopied(false)
        setIssuing(null)
        await load()
      } else {
        const d = await res.json().catch(() => ({}))
        toast(d.detail ?? `Could not issue key (HTTP ${res.status})`, "error")
      }
    } finally { setBusy(false) }
  }
```

Use the panel's existing toast hook; if none is imported, import `useToast` the way `members-panel.tsx` does.

- [ ] **Step 3: Render the issue form inside the account card**

Replace the "Issue key" button's `onClick={() => issueKey(a)}` with `onClick={() => openIssue(a)}`. Below the card header, when `issuing?.id === a.id`, render:

```tsx
{issuing?.id === a.id && (
  <div className="rounded-md border p-3 space-y-3 text-sm">
    <div className="space-y-1">
      <Label htmlFor={`key-name-${a.id}`} className="text-xs">Key name</Label>
      <Input id={`key-name-${a.id}`} value={keyName} onChange={e => setKeyName(e.target.value)} />
    </div>
    <div className="space-y-1">
      <p className="text-xs font-medium">Scopes — the key can never do more than the account's role</p>
      {choosableScopes(data?.grantable_permissions ?? [], a.permissions).map(scope => (
        <label key={scope} className="flex items-center gap-2 text-xs">
          <Checkbox
            checked={keyScopes.includes(scope)}
            onCheckedChange={v => setKeyScopes(prev => v ? [...prev, scope] : prev.filter(s => s !== scope))}
          />
          <code className="font-mono">{scope}</code>
        </label>
      ))}
      {keyScopes.length === 0 && (
        <p className="text-xs text-amber-600">No scopes selected: the key gets every permission of the role.</p>
      )}
    </div>
    <div className="space-y-1">
      <Label htmlFor={`key-expiry-${a.id}`} className="text-xs">Expires</Label>
      <select id={`key-expiry-${a.id}`} className="rounded-md border bg-background px-2 py-1 text-xs"
              value={keyExpiry === null ? "never" : String(keyExpiry)}
              onChange={e => setKeyExpiry(e.target.value === "never" ? null : Number(e.target.value))}>
        {EXPIRY_OPTIONS.map(o => (
          <option key={o.label} value={o.days === null ? "never" : String(o.days)}>{o.label}</option>
        ))}
      </select>
    </div>
    <div className="flex gap-2">
      <Button size="sm" onClick={submitIssue} disabled={busy}>Issue key</Button>
      <Button size="sm" variant="ghost" onClick={() => setIssuing(null)} disabled={busy}>Cancel</Button>
    </div>
  </div>
)}
```

`Checkbox`, `Label`, `Input`, `Button` come from `@/components/ui/*` (already used elsewhere in the settings components).

- [ ] **Step 4: Show scopes and expiry on each key row**

In the key row (`:214-237`), under the `k.name` span add:

```tsx
<span className="block text-[10.5px] text-muted-foreground">{describeKey(k)}</span>
```

- [ ] **Step 5: Show the account's collections**

Add a subcomponent at the bottom of the file and render `<AccountCollections accountId={a.id} />` inside each account card, under `AccountSpend`:

```tsx
function AccountCollections({ accountId }: { accountId: string }) {
  const [rows, setRows] = useState<AccountCollection[] | null>(null)
  useEffect(() => {
    let cancelled = false
    fetch(`/api/service-accounts/${accountId}/collections`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled && d) setRows(d.collections) })
      .catch(() => { if (!cancelled) setRows([]) })
    return () => { cancelled = true }
  }, [accountId])
  if (rows === null) return <span className="text-xs text-muted-foreground">Collections: …</span>
  if (rows.length === 0) {
    return (
      <span className="text-xs text-muted-foreground">
        Reads no collection yet — grant one under <Link href="/knowledge" className="underline">Knowledge → Members</Link>.
      </span>
    )
  }
  return (
    <span className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      Reads:
      {rows.map(c => (
        <Badge key={c.name} variant="outline" className="text-[10px]" title={`${c.access} · ${c.chunks} chunks`}>
          {c.name} · {c.access}
        </Badge>
      ))}
    </span>
  )
}
```

Import `Link` from `next/link` if not already imported.

- [ ] **Step 6: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors; build succeeds. If `react-hooks/set-state-in-effect` complains about the fetch-on-mount pattern, add the same eslint-disable comment the file already uses at `:49` with the same justification.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/settings/service-accounts.tsx
git commit -m "feat(service-accounts): issue keys with scopes and expiry; show what each account reads"
```

---

### Task 4: Snippet builders in `frontend/lib/app-snippets.ts`

**Files:**
- Create: `frontend/lib/app-snippets.ts`
- Test: `frontend/lib/app-snippets.test.ts`

**Interfaces:**
- Produces: `curlSearch(base, collection)`, `curlRag(base, collection)`, `pythonRag(base, collection)` → `string`; `snippetBase(origin: string) -> string` (`origin || "https://your-deployment"`).

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/app-snippets.test.ts
import assert from "node:assert/strict"
import { test } from "node:test"
import { curlRag, curlSearch, pythonRag, snippetBase } from "./app-snippets.ts"

test("base falls back to a placeholder when origin is unknown", () => {
  assert.equal(snippetBase(""), "https://your-deployment")
  assert.equal(snippetBase("https://dp.example.com"), "https://dp.example.com")
})

test("curl snippets carry the collection, the key header and the right path", () => {
  const s = curlSearch("https://dp", "faq")
  assert.match(s, /\/api\/ai\/search/)
  assert.match(s, /"collection": "faq"/)
  assert.match(s, /Authorization: Bearer \$DATAPOND_KEY/)
  assert.match(curlRag("https://dp", "faq"), /\/api\/ai\/rag/)
})

test("python snippet uses requests and the collection name", () => {
  const p = pythonRag("https://dp", "faq")
  assert.match(p, /import requests/)
  assert.match(p, /"collection": "faq"/)
  assert.match(p, /citations/)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot find `./app-snippets.ts`.

- [ ] **Step 3: Implement**

```ts
// frontend/lib/app-snippets.ts
// Snippets shown on a collection's "Use from app" tab. Pure strings, tested here.

export function snippetBase(origin: string): string {
  return origin || "https://your-deployment"
}

export function curlSearch(base: string, collection: string): string {
  return `curl -sX POST ${base}/api/ai/search \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "${collection}", "query": "your question", "k": 5}'`
}

export function curlRag(base: string, collection: string): string {
  return `curl -sX POST ${base}/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type": "application/json" \\
  -d '{"collection": "${collection}", "question": "your question", "k": 5}'`
}

export function pythonRag(base: string, collection: string): string {
  return `import os, requests

r = requests.post(
    "${base}/api/ai/rag",
    headers={"Authorization": f"Bearer {os.environ['DATAPOND_KEY']}"},
    json={"collection": "${collection}", "question": "your question", "k": 5},
    timeout=60,
)
r.raise_for_status()
body = r.json()
print(body["answer"])
for i, c in enumerate(body["citations"], 1):
    print(f"[{i}] {c['source']} (chunk {c['chunk_index']})")`
}
```

Fix the typo risk before running: the `curlRag` header line must read `-H "Content-Type: application/json" \\` exactly like `curlSearch`.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/app-snippets.ts frontend/lib/app-snippets.test.ts
git commit -m "feat(knowledge): curl and python snippets for calling a collection"
```

---

### Task 5: "Use from app" tab on a collection

**Files:**
- Create: `frontend/components/knowledge/use-from-app-panel.tsx`
- Modify: `frontend/app/knowledge/page.tsx:13-19` (imports), `:347-368` (Tabs in `Workspace`)

**Interfaces:**
- Consumes: Task 4 builders; `useHasPermission` from the permissions hook the page already uses; `usePermissions().role`.

- [ ] **Step 1: Write the panel**

```tsx
// frontend/components/knowledge/use-from-app-panel.tsx
"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { curlRag, curlSearch, pythonRag, snippetBase } from "@/lib/app-snippets"
import { usePermissions } from "@/lib/permissions"

/** How an application or agent calls this collection. The key comes from
 *  Settings → Service accounts; this tab never shows a key, only where to get one. */
export function UseFromAppPanel({ name }: { name: string }) {
  const { role } = usePermissions()
  const [base, setBase] = useState("https://your-deployment")
  const [copied, setCopied] = useState<string | null>(null)
  useEffect(() => { setBase(snippetBase(window.location.origin)) }, [])

  const copy = async (label: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(label) } catch { setCopied(null) }
  }

  const blocks: [string, string][] = [
    ["Search (curl)", curlSearch(base, name)],
    ["Cited answer (curl)", curlRag(base, name)],
    ["Cited answer (Python)", pythonRag(base, name)],
  ]

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-base">1. Get a key for your agent</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>
            Each agent or application gets its own service account and key, so its reads, citations
            and spend are attributed to it and not to a person.
          </p>
          <p>
            {role === "admin"
              ? <>Issue one under <Link href="/connect" className="underline">API → Service accounts</Link> with scopes <code className="font-mono">knowledge:read</code> and <code className="font-mono">ai:generate</code>, then grant it this collection under the <b>Members</b> tab.</>
              : <>Ask an administrator for a service account with <code className="font-mono">knowledge:read</code> and <code className="font-mono">ai:generate</code>, granted this collection under the <b>Members</b> tab.</>}
          </p>
        </CardContent>
      </Card>
      {blocks.map(([label, text]) => (
        <Card key={label}>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">{label}</CardTitle>
            <Button size="sm" variant="outline" onClick={() => copy(label, text)}>
              {copied === label ? "Copied" : "Copy"}
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs"><code>{text}</code></pre>
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground">
        Every call is logged against the key's service account and appears in Governance → Reports.
      </p>
    </div>
  )
}
```

`usePermissions` is exported from `@/lib/permissions` (see `frontend/app/connect/page.tsx:6`).

- [ ] **Step 2: Register the tab**

In `frontend/app/knowledge/page.tsx`: add `import { UseFromAppPanel } from "@/components/knowledge/use-from-app-panel"` beside the other panel imports (`:17-19`). In `Workspace`'s `TabsList` (`:348-358`) add, after the `members` trigger:

```tsx
<TabsTrigger value="app">Use from app</TabsTrigger>
```

and after the `members` content (`:359-367`):

```tsx
<TabsContent value="app" className="mt-4"><UseFromAppPanel name={name} /></TabsContent>
```

- [ ] **Step 3: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/knowledge/use-from-app-panel.tsx frontend/app/knowledge/page.tsx
git commit -m "feat(knowledge): a collection tells you how to call it from an app"
```

---

### Task 6: `/connect` shows governed SQL

**Files:**
- Modify: `backend/app/api/api_surface.py:19,81-100`
- Test: `backend/tests/test_api_surface.py` (extend)

**Interfaces:**
- Produces: `EXTRA_ROUTES = {("/api/queries/execute", "POST")}`; `build_api_surface(app)` includes any route whose `(path, method)` is in `EXTRA_ROUTES` in addition to the `/api/ai/` prefix.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api_surface.py` (follow the file's existing way of building a FastAPI app for `build_api_surface`):

```python
def test_surface_includes_governed_sql_execute():
    from fastapi import FastAPI
    from app.api import queries
    from app.api.api_surface import build_api_surface
    app = FastAPI()
    app.include_router(queries.router, prefix="/api")
    entries = {(e["path"], e["method"]) for e in build_api_surface(app)}
    assert ("/api/queries/execute", "POST") in entries
    assert ("/api/queries/history", "GET") not in entries   # only the tool, not the rest of the router
```

`GET /api/queries/history` is a real route (`backend/app/api/queries.py:367`), so the negative assertion is meaningful.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3.12 -m pytest tests/test_api_surface.py -q`
Expected: the new test FAILS on the first assertion.

- [ ] **Step 3: Implement**

In `api_surface.py`, below `PREFIX`:

```python
# Tools an application integrates against that do not live under /api/ai/. Listed one
# by one so the operational routes of the same routers stay out of the surface.
EXTRA_ROUTES = frozenset({("/api/queries/execute", "POST")})
```

and in `build_api_surface`, replace the prefix check:

```python
    for route in app.routes:
        path = getattr(route, "path", "")
        if not hasattr(route, "dependant"):
            continue
        methods = sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
        for method in methods:
            if not (path.startswith(PREFIX) or (path, method) in EXTRA_ROUTES):
                continue
            doc = (getattr(route, "endpoint", None).__doc__ or "").strip()
            out.append({...})   # unchanged body
```

Update the module docstring line 13-15 so it no longer says the surface is scoped to `/api/ai/*` only.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3.12 -m pytest tests/test_api_surface.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/api_surface.py backend/tests/test_api_surface.py
git commit -m "feat(api): governed SQL execution is part of the application surface"
```

---

### Task 7: Dashboard step 04 becomes "Connect your agent"

**Files:**
- Modify: `frontend/components/dashboard/journey-strip.tsx:56-61,77-101`

- [ ] **Step 1: Change the step**

Replace the step 04 object:

```tsx
    {
      n: "04",
      title: "Connect your agent",
      sub: "Issue a key, call this deployment",
      href: "/connect",
      icon: Plug,
      color: "var(--chart-2)",
      cta: true,
    },
```

Add `cta?: boolean` to the `Step` type (`:8-15`).

- [ ] **Step 2: Render a CTA step differently, same `Link`**

In the render (`:80-96`), change the `Link` className to:

```tsx
<Link
  href={step.href}
  className={
    step.cta
      ? "group flex items-center gap-3 rounded-lg border border-primary/40 bg-primary/5 px-2 py-1 -mx-2"
      : "group flex items-center gap-3"
  }
>
```

Everything else in the strip stays as it is. Also change the strip's section label at `:77` from `Portable core workflow` to `Core workflow`.

- [ ] **Step 3: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/dashboard/journey-strip.tsx
git commit -m "feat(dashboard): step 04 is the call to action — connect your agent"
```

---

### Task 8: Help guide "Integrate an application or agent"

**Files:**
- Create: `frontend/app/help/integrate/page.tsx`
- Modify: `frontend/app/help/page.tsx:32-78` (add a guide entry)

- [ ] **Step 1: Add the guide entry**

Insert after the "Knowledge & RAG" guide:

```tsx
  {
    title: "Integrate an application or agent",
    description: "Create an agent identity, issue a scoped key, call search and cited answers",
    icon: Plug,
    href: "/help/integrate",
    topics: ["Service accounts", "Scoped keys", "Search and RAG calls", "Governed SQL", "Audit"],
  },
```

Import `Plug` from `lucide-react` alongside the other icons.

- [ ] **Step 2: Write the page**

Model it on `frontend/app/help/connectors/page.tsx` (same Breadcrumb, `HelpTabs`, Card layout). Content, as four numbered sections:

```tsx
// frontend/app/help/integrate/page.tsx — structure mirrors help/connectors/page.tsx
export default function IntegrateHelpPage() {
  return (
    <HelpLayout title="Integrate an application or agent">
      <Section n="1" title="Create a service account">
        Settings → Service accounts (or API → Service accounts). One account per agent or
        application. Pick the role that holds only what it needs; ai_engineer is the usual choice.
      </Section>
      <Section n="2" title="Issue a scoped, expiring key">
        Issue key → tick knowledge:read and ai:generate (add query:run for governed SQL) → choose
        an expiry (90 days by default). The key is shown once; store it as DATAPOND_KEY.
      </Section>
      <Section n="3" title="Grant collections">
        Knowledge → the collection → Members → add the account's username (svc-…) as reader.
        Tables follow the account's role and any row filters or masks under Governance.
      </Section>
      <Section n="4" title="Call it">
        <pre>{`curl -sX POST https://your-deployment/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "faq", "question": "your question"}'`}</pre>
        Every call is logged against the account and appears in Governance → Reports as agent tool calls.
      </Section>
    </HelpLayout>
  )
}
```

Replace `HelpLayout`/`Section` with whatever the connectors help page actually composes (Breadcrumb + `HelpTabs` + `Card`s); the text above is the content to carry over verbatim.

- [ ] **Step 3: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: green; the new route builds as a static page.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/help/integrate/page.tsx frontend/app/help/page.tsx
git commit -m "docs(help): integrate an application or agent — identity, key, grant, call"
```

---

### Task 9: Documents

**Files:**
- Modify: `docs/UPGRADING.md`, `docs/AWS_MVP_RUNBOOK.md:114-146` (service-key curl), `docs/POSITIONING_FIT_AUDIT.md` §7.1 axis A rows

- [ ] **Step 1: Upgrade note**

Add at the top of `docs/UPGRADING.md`:

```markdown
### Service-account keys issued from the UI now carry scopes and an expiry

Keys issued from Settings → Service accounts default to `knowledge:read` + `ai:generate`
and 90 days. Keys issued before this change keep their previous (role-wide, non-expiring)
grants; revoke and reissue them to narrow. `GET /api/service-accounts/{id}/collections`
lists what an account can read. `/api/api-surface` (the API page) now includes
`POST /api/queries/execute`.
```

- [ ] **Step 2: Runbook curl uses a service key**

In `docs/AWS_MVP_RUNBOOK.md:114-146`, replace `-H "Authorization: Bearer $TOKEN"` with `-H "Authorization: Bearer $DATAPOND_KEY"` in the search/rag examples and add one sentence above them: "Issue `DATAPOND_KEY` as a service-account key (Settings → Service accounts) rather than using a person's login token."

- [ ] **Step 3: Flip the audit rows**

In `docs/POSITIONING_FIT_AUDIT.md` §7.1 축 A, set ○ for: 키 발급 시 스코프 선택, 키 발급 시 만료 선택, 서비스 계정에 컬렉션 부여(방향 둘 다), `/connect`가 `/queries/execute` 포함, 컬렉션 페이지 "앱에서 쓰기" 스니펫, 통합 도움말. Cite the files from this plan.

- [ ] **Step 4: Full check and commit**

Run: `cd backend && python3.12 -m pytest tests -q --ignore=tests/acceptance && cd ../frontend && npm test && npm run lint && npm run build`

```bash
git add docs/UPGRADING.md docs/AWS_MVP_RUNBOOK.md docs/POSITIONING_FIT_AUDIT.md
git commit -m "docs: agent onboarding journey — upgrade note, runbook key, fit audit rows"
```
