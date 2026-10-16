# Agents Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin-only Agents menu: a list of service accounts and one page per agent that shows and edits identity, keys, data access, spend and activity. Service-account management moves there, and the LiteLLM virtual-key card goes away.

**Architecture:** Four small backend additions:
- one account read;
- per-agent catalog access, computed by the enforcement code;
- idempotent per-user catalog grants;
- key-cache drop on disable or role change.

The frontend is a new `/agents` list and `/agents/[id]` page composed of section components. Section components reuse existing routes; pure view logic lives in `lib/agents.ts` with node tests.

**Tech Stack:** FastAPI + asyncpg (backend/app), pytest (backend/.venv); Next.js app router + shadcn/ui (frontend), `node --test` for lib helpers.

**Spec:** `docs/superpowers/specs/2026-10-16-agents-page-design.md`

## Global Constraints

- **Who can use it.** Everything is admin-only. New backend routes use `require_admin`. The menu permission is `user:manage`.
- **Which users.** Service accounts only (`auth_method = 'service'`). Any other user id → 404 `Unknown service account.`
- **Disable copy.** The UI copy says the change "applies within 30 seconds" (`_KEY_CACHE_TTL = 30.0`).
- **Rate limit.**
  - Shown read-only as "<N> requests/min per key, per replica".
  - N comes from `api_key_limiter().per_minute`. Default is 600, env `API_KEY_RATE_LIMIT_PER_MINUTE`.
- **Catalog `via` precedence.** `user` → `role` → `open`. Otherwise `null` (not allowed). `restricted` = the catalog has ≥1 grant row.
- **Knowledge-only installs.** The Catalogs section renders only when the `catalog` capability is true.
- **One edit point per value** (spec table):
  - Caller budgets: service-account rows are read-only and link to `/agents/{id}`.
  - Settings → Service accounts is removed. `/settings?tab=service` → `/agents`.
- **Virtual keys.** Remove the "Virtual Keys & Budgets" card. Keep the `/api/settings/ai/keys` routes (deprecated in UPGRADING).
- **Merge and deploy discipline.**
  - Merge only at 0 failing / 0 pending checks.
  - Deploy only after main CI succeeds on that SHA.

## Review Focus

1. **A deleted or non-service id at `/agents/[id]`.** The page shows "not found" with a link back, not a crash or an empty form. Test: Task 3 `test_get_one_404_for_human_and_missing`; Task 7 renders the 404 branch.
2. **Grants unreadable.**
   - Situation: the grants table is missing or the DB is down while reading per-agent catalogs.
   - Expected: a 503 with a message. The page must not show "open" for everything, which would claim access that enforcement denies.
   - Test: Task 1 `test_catalogs_grants_unavailable_is_503`.
3. **Granting the same user twice, or revoking a grant that doesn't exist.** Expected: idempotent 200, with no duplicate row and no error. Test: Task 2 `test_user_grant_idempotent`.
4. **Partial failure on the list page.** If the audit summary or budgets fail, the list still renders with "—" in those columns. Test: Task 5 `joinAgentRows tolerates missing sources`.
5. **Role change on a key whose identity is cached.** The serving replica applies the change at once. Test: Task 4 `test_patch_role_drops_cached_keys`.

---

### Task 1: Per-agent catalog access (read)

**Files:**
- Modify: `backend/app/catalog_access.py`
  - Add `CatalogAccess.via`.
  - Make `allows` delegate to it, so there is one rule.
- Modify: `backend/app/api/service_account_routes.py`: new route.
- Test: `backend/tests/test_service_account_catalogs.py`

**Interfaces:**
- Produces: `CatalogAccess.via(entry) -> Optional[str]`, returning `"exempt"|"user"|"role"|"open"|None`. `allows(entry)` ≡ `via(entry) is not None`.
- Produces: `GET /api/service-accounts/{id}/catalogs` → `{account_id, catalogs:[{catalog, restricted: bool, allowed: bool, via: "user"|"role"|"open"|null}]}`.
  - Covers every enabled registry entry.
  - 503 when grants are unreadable.

- [ ] **Step 1: Failing tests.**
  - `test_via_precedence`: build `CatalogAccess(grants=…, user_id="U", role="ai_engineer")` and check each case:
    - no grants → `"open"`;
    - `("user","u")` ∈ grants → `"user"`;
    - only `("role","ai_engineer")` → `"role"`;
    - user and role both present → `"user"`;
    - other grants only → `None`;
    - `allows` agrees with `via` on all of these.
  - `test_catalogs_listing`: monkeypatch the registry entries and `load_grants`. Asserts the row shapes and `restricted`.
  - `test_catalogs_grants_unavailable_is_503`: `load_grants` raises → 503.
  - `test_catalogs_404_for_non_service`.
  - For the account lookup fakes, follow `tests/test_service_account_collections.py`.
- [ ] **Step 2:** Run `cd backend && .venv/bin/python -m pytest tests/test_service_account_catalogs.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `via` in `CatalogAccess`.
  - Route: load the account (`auth_method='service'` else 404). Call `load_grants()` directly; do not go through `for_caller`, which swallows errors into "nothing allowed". On exception → 503 `Catalog grants are unavailable.` Then build `CatalogAccess(grants=…, user_id=id, role=account.role)` and map each `catalog_registry.entries()` item.
- [ ] **Step 4:** Run the same pytest plus `tests/test_catalog_access.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(agents): per-agent catalog access, computed by the enforcement rule`.

### Task 2: One user-grant at a time

**Files:**
- Modify: `backend/app/api/catalog_admin.py`
- Test: `backend/tests/test_catalog_user_grant.py`

**Interfaces:**
- Produces: `PUT /api/catalogs/{name}/grants/user/{principal}` and `DELETE` (same path).
  - Admin only.
  - Both return `{catalog, restricted, grants}`, the same shape as `PUT /grants`.
  - Both are idempotent (`ON CONFLICT DO NOTHING` / delete-if-present).
  - Both audit the change via `_audit_grants`.
  - Both call `catalog_access.invalidate()`.
  - Unknown catalog → 404. Unknown user → 400 `No user with id …`.

- [ ] **Step 1: Failing tests.** Use the fake-pool style of the existing catalog grant tests (`tests/test_catalog_grants_listing.py`).
  - `test_user_grant_idempotent`: PUT twice → one grant; DELETE twice → 200 both times, no grant left.
  - `test_user_grant_invalidates_cache`.
  - `test_user_grant_unknown_user_400`.
  - `test_user_grant_non_admin_403`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_catalog_user_grant.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the two handlers next to `put_catalog_grants`. Reuse `_catalog_or_404`, `_read_grants`, `_GRANT_INSERT` (add `ON CONFLICT DO NOTHING` in a new constant if `_GRANT_INSERT` lacks it) and `_audit_grants`. Normalise the principal to lower-case.
- [ ] **Step 4:** Run pytest. Expected: PASS.
- [ ] **Step 5:** Commit `feat(agents): add or remove one user's catalog grant`.

### Task 3: Read one service account

**Files:**
- Modify: `backend/app/api/service_account_routes.py`
- Test: `backend/tests/test_service_accounts.py` (extend)

**Interfaces:**
- Produces: `GET /api/service-accounts/{id}`. Admin only.
  - Returns one element in the shape of the `GET /api/service-accounts` list items.
  - Adds `attributes: dict`, plus top-level `assignable_roles`, `grantable_permissions`, `oauth`, `rate_limit_per_minute: int`.
  - Unknown or non-service id → 404 `Unknown service account.`
- Refactor: the list handler and this one share one `_account_rows(conn, where_id: Optional[str])` helper, so the two shapes cannot drift.

- [ ] **Step 1: Failing tests.**
  - `test_get_one_shape`: keys, `attributes`, `rate_limit_per_minute == api_key_limiter().per_minute`.
  - `test_get_one_404_for_human_and_missing`.
  - `test_list_unchanged`: the existing list tests still pass.
- [ ] **Step 2:** Run pytest on the file. Expected: FAIL (new tests).
- [ ] **Step 3: Implement** the route and the helper.
- [ ] **Step 4:** Run pytest. Expected: PASS.
- [ ] **Step 5:** Commit `feat(agents): read one service account`.

### Task 4: Disable and role change take effect on this replica at once

**Files:**
- Modify: `backend/app/api/auth.py`
  - Add `forget_cached_keys_for(user_id: str) -> int`.
  - Call it in the user PATCH when `is_active` or `role` is in the body.
- Test: `backend/tests/test_key_cache_forget.py`

**Interfaces:**
- Produces: `forget_cached_keys_for(user_id) -> int`. It removes every `_KEY_CACHE` entry whose resolved identity's `id` equals `user_id` (case-insensitive) and returns the count.

- [ ] **Step 1: Failing tests.**
  - `test_forget_only_that_user`: seed `_KEY_CACHE` with two users' entries → only one user's entries are removed.
  - `test_patch_role_drops_cached_keys` and `test_patch_is_active_drops_cached_keys`: drive the PATCH handler with a fake pool, as the existing user-PATCH tests do (`grep -l "def test.*patch" tests/test_*user*`).
- [ ] **Step 2:** Run pytest on the file. Expected: FAIL.
- [ ] **Step 3: Implement.** Check how `_KEY_CACHE` stores the resolved identity at `auth.py` ~1296–1345 and match on its id field.
- [ ] **Step 4:** Run the full backend suite: `.venv/bin/python -m pytest tests -q --ignore=tests/acceptance`. Expected: all pass.
- [ ] **Step 5:** Commit `fix(auth): disabling or re-roling a service account drops its cached keys on this replica`.

### Task 5: View helpers

**Files:**
- Create: `frontend/lib/agents.ts`
- Test: `frontend/lib/agents.test.ts`

**Interfaces:**
- Types:
  - `AgentKey = {id; name; key_prefix; status; scopes: string[]; expires_at: string|null; last_used_at: string|null; created_at}`
  - `Agent = {id; username; display_name: string|null; role; is_active: boolean; created_at; keys: AgentKey[]; oauth_client: {client_id; issuer}|null; attributes?: Record<string,string|string[]>}`
- `agentStatus(a: Agent, now: Date): {label: "disabled"|"no active key"|"key expiring"|"active"; tone: "bad"|"warn"|"ok"}`
  - `disabled` when `!is_active`.
  - `no active key` when no key has status `active` and an unexpired `expires_at`.
  - `key expiring` when an active key expires in ≤ 14 days.
  - Otherwise `active`.
- `lastUsed(a: Agent): string|null`: the max `last_used_at` across keys.
- `joinAgentRows(agents: Agent[], summary: ByActor[]|null, budgets: Budget[]|null): AgentRow[]`
  - `ByActor = {actor_id: string|null; calls; refused}`.
  - `Budget = {user_id; spend: number; max_budget: number|null}`.
  - `AgentRow = Agent & {calls24h: number|null; refused24h: number|null; spend: number|null; cap: number|null}`.
  - A `null` source gives `null` columns. An agent missing from a present source gives 0 calls, or `spend` 0 with `cap` null.
- `viaLabel(via: "user"|"role"|"open"|null, role: string): string`:
  - `"granted to this agent"`
  - `"granted to role <role>"`
  - `"open to every caller"`
  - `"not granted"`

- [ ] **Step 1:** Write tests covering every branch above, including `joinAgentRows tolerates missing sources` (summary `null`, budgets `null`).
- [ ] **Step 2:** Run `cd frontend && npm test`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`. Expected: all pass.
- [ ] **Step 5:** Commit `feat(agents): list status and row join helpers`.

### Task 6: `/agents` list and menu

**Files:**
- Create: `frontend/app/agents/page.tsx`
- Modify: `frontend/lib/nav-items.ts`
  - Operate group, first item `{ title: "Agents", url: "/agents", permission: "user:manage" }`.
  - Add a comment giving the why (spec "Who and where").
- Modify: `frontend/components/app-sidebar.tsx`: icon map `"/agents": Cpu` (lucide).
- Test: `frontend/lib/core-workflow.test.ts` stays green (no change needed).

**Interfaces:**
- Consumes: Task 5 helpers.
- Consumes these routes, each loaded independently:
  - `GET /api/service-accounts`
  - `GET /api/audit/tool-calls/summary?since=<ISO now-24h with Z>`
  - `GET /api/settings/ai/budgets`
- Produces: a table with columns Name (`display_name` + `svc-` username) · Role · Status badge · Last used · Calls 24h · Refused 24h · Spend / cap.
  - A row links to `/agents/{id}`.
  - "New agent" dialog: name, role (`assignable_roles`), description → `POST /api/service-accounts` → `router.push('/agents/'+id)`.
  - A non-admin sees the existing "Not available for your role" pattern (see `app/connect` history / `permissionState`).

- [ ] **Step 1:** Build the page. The table vs cards layout on narrow screens is the builder's choice.
- [ ] **Step 2:** Run `npx tsc --noEmit -p .`, `npx eslint app/agents lib components/app-sidebar.tsx` and `npm test`. Expected: 0 errors, tests pass.
- [ ] **Step 3:** Commit `feat(agents): agents list and menu item`.

### Task 7: `/agents/[id]` page

**Files:**
- Create: `frontend/app/agents/[id]/page.tsx`
- Create: `frontend/components/agents/identity-section.tsx`, `keys-section.tsx`, `access-section.tsx`, `spend-section.tsx`, `activity-section.tsx`, `danger-section.tsx`
- Modify: `frontend/components/settings/service-accounts.tsx`
  - Move the key table, issue, rotate and revoke dialogs, and `OAuthClientRow` into `keys-section.tsx`.
  - Move `AccountSpend` into `spend-section.tsx`.
  - Move `AccountCollections` into `access-section.tsx`.
  - Delete what is left of the file once Task 8 removes its last import.

**Interfaces:**
- Consumes: `GET /api/service-accounts/{id}` (Task 3). It is the page's source of truth. 404 → "This agent no longer exists" + a link to `/agents`.
- **Identity:**
  - Role select → `PATCH /api/auth/users/{id}` `{role}`. Confirm text: "Changing the role changes what every key of this agent can do."
  - Display name → the same PATCH `{display_name}`.
- **Keys:**
  - The moved UI.
  - Rate limit line: `${rate_limit_per_minute} requests/min per key, per replica`.
  - With no keys, lead with an "Issue a key" button.
- **Access:**
  - Collections:
    - `GET /api/service-accounts/{id}/collections`.
    - Add: a picker from `GET /api/ai/collections`, role reader or editor → `POST /api/ai/collections/{name}/members {username, role}`.
    - Remove: `DELETE /api/ai/collections/{name}/members?username=`.
    - `global` rows show "open to every caller" with no remove.
  - Catalogs (only when `useCapability("catalog")`):
    - `GET /api/service-accounts/{id}/catalogs`.
    - Per row: `viaLabel`, plus Grant (`PUT .../grants/user/{id}`) or Revoke (`DELETE`).
    - Revoke is shown only when `via === "user"`.
    - On 503, show the message; no rows.
  - Attributes:
    - A key/value editor → `PATCH /api/auth/users/{id} {attributes}` (whole object).
    - Lists collections whose chunk rule uses an attribute, as "used by: <collection> (<attr>)".
    - Source: `GET /api/ai/collections` items' chunk-access fields if present. Otherwise omit that line; do not add a backend route for it.
- **Spend:**
  - `GET /api/service-accounts/{id}/usage` (spend, requests).
  - Cap: `GET` / `PUT /api/settings/ai/budgets/{id}` `{max_budget}`. An empty input means `null`.
  - Text: "A call over the cap is refused (402)."
- **Activity:**
  - `GET /api/audit/tool-calls?actor_id={id}&since=<24h|7d ISO Z>&limit=50`.
  - Columns: time, tool, outcome (refused/error highlighted), resource, hits, withheld, pii_masked.
  - Note: "Calls with a disabled or revoked key are refused before the caller is known and do not appear here."
- **Danger:**
  - Disable/Enable → `PATCH {is_active}`, with the text "Applies within 30 seconds."
  - Delete → type the `svc-` username to confirm → `DELETE /api/service-accounts/{id}` → `/agents`.
- Each section loads and fails independently (its own error + retry).

- [ ] **Step 1:** Build the sections and the page.
- [ ] **Step 2:** Run `tsc`, `eslint app/agents components/agents components/settings` and `npm test`. Expected: 0 errors, pass.
- [ ] **Step 3:** Commit `feat(agents): one page per agent`.

### Task 8: Remove the duplicates, relink, document

**Files:**
- Modify: `frontend/app/settings/page.tsx`
  - Remove the Service accounts tab and its import.
  - `TABS` drops `"service"`.
  - When `?tab=service`, `router.replace("/agents")`.
- Modify: `frontend/components/settings/caller-budgets.tsx`: rows whose id is in the `/api/service-accounts` list are read-only, with a link "Set on the agent's page" → `/agents/{id}`. People stay editable.
- Modify: `frontend/components/settings/ai-backends.tsx`: stop rendering the `VirtualKeys` card. Delete the component if nothing else imports it.
- Modify: `frontend/app/help/integrate/page.tsx`
  - Step 1 becomes "Agents → New agent" linking `/agents`.
  - The scopes table stays.
- Modify: other `"/settings?tab=service"` links found by grep → `/agents`.
- Modify: `docs/UPGRADING.md`: a new entry covering:
  - the Agents menu;
  - Settings → Service accounts moved;
  - Disable is now a button;
  - virtual-key card removed, with routes `/api/settings/ai/keys` deprecated and to be removed next release. Include a `curl` to list and delete keys via the routes.
- Modify: `CLAUDE.md` "Core navigation" line: add Agents.

- [ ] **Step 1:** Run `grep -rn "tab=service\|ServiceAccounts\|VirtualKeys" frontend/app frontend/components`. Expected: only intended hits remain after the edits.
- [ ] **Step 2:** Run `tsc`, `eslint app components lib`, `npm test` and the backend suite. Expected: green.
- [ ] **Step 3:** Commit `refactor(ui): service accounts live on Agents; virtual-key card removed`.

### Task 9: Ship and verify live

- [ ] **Step 1:** Push the branch and open the PR. Merge only at 0 failing / 0 pending checks.
- [ ] **Step 2:** Deploy (`gh workflow run deploy-aws.yml --ref main`) after main CI succeeds. Expected: smoke `health: healthy`.
- [ ] **Step 3: API verification in-pod** (scratchpad harness, one at a time).
  1. Create `demo-rehearsal-agentpage`.
  2. `GET /service-accounts/{id}` shape.
  3. `/catalogs` lists AwsDataCatalog `via:"open"`. Then user-grant PUT → `via:"user"`, then DELETE → `"open"`.
  4. PATCH `is_active:false`, then a key call on the same replica → 401.
  5. Cleanup: delete the account and restore any grants.
- [ ] **Step 4: Browser check** (operator signed in): `/agents` list renders; open an agent; the sections load; `/settings?tab=service` redirects.
