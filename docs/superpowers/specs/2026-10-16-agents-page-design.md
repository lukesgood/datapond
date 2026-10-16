# Agents page — one view per agent

Date: 2026-10-16. Status: draft for review.

## Why

DataPond's value is governance per caller: which agent reads which collection,
table and row, what it was shown and masked, and what it spent. The caller is a
service account. The console has no page for that caller. One agent's state is
spread over five menus:

| What | Where today |
|---|---|
| Identity, role, keys, scopes, OAuth client | Settings → Service accounts (admin) |
| Collections it reads | each collection's Members tab in Knowledge (granted per collection, by username) |
| Catalogs it may use | Settings → Data catalogs → each catalog's access dialog |
| Attributes for chunk rules (e.g. `department`) | no UI; only `PATCH /api/auth/users/{id}` |
| Spend cap | AI Gateway → Caller budgets |
| Spend | AI Gateway usage; one figure on its Service accounts row |
| What it called | Governance → Audit Log (all callers mixed together) |
| Disable without deleting | no UI; only `PATCH /api/auth/users/{id}` `{is_active:false}` |
| Delete | no UI; `DELETE /api/service-accounts/{id}` exists |

Three operator questions have no single place to go:
- "Connect a new agent": create it, issue a key, grant data, cap spend.
- "Why did this agent do that": its recent calls, refusals, what it read.
- "Shut it off": disable it or revoke its key, now.

A second key system adds to the confusion. AI Gateway → "Virtual Keys & Budgets"
issues LiteLLM keys with their own model list, budget and rate limits. They are not
service-account keys and appear nowhere in governance.

## Goals

1. An **Agents** menu: a list of agents, and one page per agent that shows and edits
   everything above.
2. Service-account management moves there. Settings → Service accounts goes away.
3. One key system in the console: service-account keys.

## Non-goals

- Human users. People stay in Settings → Users. The page is for service accounts
  (`auth_method = 'service'`) only.
- Per-agent rate limits. The limit stays one deployment-wide value per key
  (`API_KEY_RATE_LIMIT_PER_MINUTE`, default 600/min, per replica,
  `app/rate_limit.py:194`). The page shows it; it does not set it.
- Per-agent model allow-lists.
- Read-only access for auditors. The source APIs are admin-only today; widening
  them is a separate decision.
- New governance mechanisms. Every control on the page already exists as an API.
  The page gathers them; it does not add a new policy kind.

## Anti-goals (failure even if it works)

- A second place where the same thing is edited, with a different result.
  Each value has exactly one edit point (table below).
- A disable that looks immediate but isn't. The UI says when it takes effect.
- A page that needs every add-on. Knowledge-only installs (no catalog/query) must
  render it, with the catalog section hidden by capability.

## Who and where

- **Who:** administrators only, like the service-account API today
  (`require_admin`). Menu permission `user:manage`, which only admin holds.
- **Where:** `Operate` group, first item, `/agents`. Operate is "govern and run",
  and an agent is the unit being governed. It is not under Build AI: an agent may
  use metrics and SQL, not only knowledge.

## The list — `/agents`

One row per service account:

| Column | Source |
|---|---|
| Name (`display_name`, `svc-…` username) | `GET /api/service-accounts` |
| Role | same |
| Status: active / disabled / no active key / key expiring in ≤ 14 days | `is_active`, `keys[].status`, `keys[].expires_at` |
| Last used | max of `keys[].last_used_at` (accurate to ~30 s) |
| Calls in 24 h, refused in 24 h | `GET /api/audit/tool-calls/summary?since=<24h>` → `by_actor` |
| Spend / cap | `GET /api/settings/ai/budgets` (`spend`, `max_budget`) |

- "New agent" creates an account (name, role, description) and opens its page.
- The three sources load independently. If one fails, its columns show "—" and the
  rest still render.

## The agent page — `/agents/[id]`

One scrolling page, sections in this order (question order: who → can it get in →
what may it read → what does it cost → what did it do):

1. **Identity.** Display name, `svc-` username, role (select, from
   `assignable_roles`), created, status.
   - Role change: `PATCH /api/auth/users/{id}` `{role}`.
   - Changing the role widens or narrows every key at once (scopes intersect the
     role). Confirm before saving and say so in the confirm.
2. **Access keys.** Today's key table, moved as-is: issue (scopes, expiry), rotate
   (grace hours), revoke, last used. Plus the OAuth client row.
   - Shows the deployment rate limit per key ("600 requests/min per key, per
     replica").
3. **Data access.**
   - **Collections:** `GET /api/service-accounts/{id}/collections`. Add reader or
     editor with a collection picker; remove.
     - Both go through the existing per-collection member routes
       (`POST/DELETE /api/ai/collections/{name}/members`, by username).
     - Collections with `access: global` are listed as "open to every caller" and
       cannot be removed here.
   - **Catalogs** (only when the catalog capability is on): every catalog with
     whether this agent may use it, and why — open (no grants), granted to this
     agent, granted to its role, or not granted. Grant/revoke this agent's
     user-grant.
   - **Attributes:** key/value list from `users.attributes`, used by chunk rules
     ("this agent's `department`"). Edit = `PATCH /api/auth/users/{id}`
     `{attributes}` (whole-object replace, as today). Shows which collections have
     a chunk rule and on which attribute, so an empty attribute that will withhold
     everything is visible.
4. **Spend.**
   - Spend and requests: `GET /api/service-accounts/{id}/usage`.
   - Cap: `GET`/`PUT /api/settings/ai/budgets/{id}`. A call over the cap gets 402.
     Since #235, a change applies on every replica at once.
5. **Activity.** The last 50 tool calls:
   - Source: `GET /api/audit/tool-calls?actor_id={id}`.
   - Columns: time, tool, outcome, resource, hits, withheld, PII masked.
   - "Last 24 h / 7 d" toggle.
   - Refusals are highlighted, because "why was it refused" is the usual reason to
     open this page.
6. **Danger zone.**
   - **Disable / enable:** `PATCH /api/auth/users/{id}` `{is_active}`. The UI states
     "applies within 30 seconds" (key cache TTL, per replica).
   - **Delete:** `DELETE /api/service-accounts/{id}`. Type-the-name confirm. Keys
     cascade, the gateway customer and cap are removed, and audit rows keep the
     name (0022).

## One edit point per value

| Value | Edited on | Shown read-only elsewhere |
|---|---|---|
| Keys, scopes, OAuth client | Agent page | — |
| Agent's collection membership | Agent page *and* the collection's Members tab | — (see note) |
| Agent's catalog grant | Agent page | Settings → Data catalogs dialog lists it; editing there remains for role grants and people |
| Agent's spend cap | Agent page | AI Gateway → Caller budgets: agent rows read-only, linking to the agent page; people stay editable there |
| Attributes | Agent page (service accounts); Settings → Users (people, unchanged) | — |

**Note on membership.** Membership is one row in `ai_collection_members`, edited
through one API, from two directions: "who reads this collection" and "what does
this agent read". Both views call the same route and both reload from it. That is
one value with two entry points, not two values, so it is allowed.

## Backend work (small)

The page needs two things the API does not have yet:

1. `GET /api/service-accounts/{id}`. One account in the list's shape plus
   `attributes`, so the page does not fetch every account and every user. Admin.
2. Per-agent catalog access.
   - `GET /api/service-accounts/{id}/catalogs` → for each catalog:
     `{catalog, restricted, allowed, via: "open"|"user"|"role"|null}`.
     Computed with the same rule as `app/catalog_access.py`, so the page and
     enforcement cannot disagree.
   - `PUT` and `DELETE /api/catalogs/{name}/grants/user/{principal}`: add or remove
     one user-grant. Idempotent, so the page never does read-modify-write on the
     whole grant list (`PUT /grants` replaces it). Both invalidate the catalog
     access cache as the existing PUT does. Admin.

3. On `PATCH /api/auth/users/{id}`, when the patch changes `is_active` or `role` for a
   service account, drop that user's entries from this replica's `_KEY_CACHE`. Today
   a key is resolved from the database (which checks `users.is_active` and the key's
   status, `app/api/auth.py` ~1320–1345) and then cached for 30 s per replica
   (`_KEY_CACHE_TTL`). With this change, the replica that served the change applies
   it at once and other replicas within 30 s. The UI says "within 30 seconds".

Nothing else is new. Role, attributes, members, budgets, usage and audit all use
existing routes.

### Facts the design relies on (checked in code, 2026-10-16)

- **Members.** `POST /api/ai/collections/{name}/members` takes `{username, role:
  "reader"|"editor"}` and upserts. `DELETE` takes `?username=`. Both need
  `knowledge:write` plus write access to the collection, which an administrator
  always has (`app/knowledge_access.may_write`). A `svc-…` username resolves like
  any user.
- **Collections read.** `GET /api/service-accounts/{id}/collections` returns
  `{collections:[{name, access: owner|reader|editor|global, chunks}]}`.
- **Budgets.** `GET /api/settings/ai/budgets` is the gateway's `/customer/list`.
  - Rows are keyed by `user_id`, the DataPond user id, since every model call
    carries it as the OpenAI `user`.
  - An agent appears once it has called a model or had a cap set. No row means no
    spend and no cap.
  - The list is not paginated.
- **Refusals in the audit.**
  - A 402 (cap), a 403 (permission or ACL) and a refused PII block are written with
    the caller's `actor_id` (`refuse_over_budget` records the actor). Activity
    filtered by `actor_id` shows them.
  - A request with a disabled or revoked key is refused at authentication (401)
    before an actor exists, so it is not in that agent's Activity. The page says
    so under the Danger zone.
- **Role change.** `PATCH /api/auth/users/{id}` accepts a service account. It refuses
  `role: "admin"` for one (`app/api/auth.py` ~1150–1157). The role select offers
  `assignable_roles`, which excludes admin.
- **Telling agents apart in Caller budgets.** `components/settings/caller-budgets.tsx`
  already loads `/api/service-accounts` to name callers. An agent row is a row whose
  id is in that list. No payload change.
- **Catalog `via`.** Computed by reusing `app/catalog_access` (the enforcement code),
  not by a second implementation. Precedence when several apply:
  user grant → role grant → open. `restricted` means the catalog has at least one
  grant row; a catalog with none is open.
- **Permissions of the new routes.** `require_admin`, the same as the existing
  `PUT /api/catalogs/{name}/grants` and every service-account route.

## The second key system — LiteLLM virtual keys

Facts (inventory 2026-10-16):
- No DataPond code path uses a virtual key. The backend calls LiteLLM with the
  master key and attributes spend by the OpenAI `user` field (= the DataPond user
  id).
- LiteLLM is not exposed by the ingress: ClusterIP only, and the NetworkPolicy
  allows only the backend. A virtual key is usable only in-cluster or through a
  port-forward.
- A virtual key calls models directly. Nothing it does reaches the tool-call log,
  collection ACLs, RLS/masking or per-caller caps.

On the live reference deployment there are no virtual keys (`GET /api/settings/ai/keys`
→ `[]`, 2026-10-16), so removing the card strands nothing there. Another
installation that has some can still list and delete them through the routes during
the deprecation release, and UPGRADING says how.

**Decision (my call, for review):**
- Remove the "Virtual Keys & Budgets" card from AI Gateway.
- Keep the `/api/settings/ai/keys` routes for one release, marked deprecated in
  UPGRADING. Remove them in the next.

A deployment that wants direct model access for another app can still use LiteLLM
itself. DataPond's console offers one key system, and it is the governed one.

## Other moves

- Settings → Service accounts tab is removed. `/settings?tab=service` redirects to
  `/agents`.
- Links that point there are updated:
  - the integration guide's step 1;
  - the Knowledge Members hint;
  - `AccountCollections` links.
- The guide's step 1 becomes "Agents → New agent".
- `docs/UPGRADING.md`: the move, the virtual-key deprecation, and that disabling is
  now a button.

## Errors and edge cases

- A source API fails: that section shows its error and a retry. Other sections still
  render.
- The gateway is unreachable: the Spend section says spend is unavailable. The cap
  editor stays usable: the DB row is written and the gateway write reports its own
  error, as `PUT /budgets` does today.
- The agent was deleted in another tab: `GET /api/service-accounts/{id}` returns
  404, and the page says so with a link back to the list.
- An agent with no keys: the list status reads "no active key", and the page leads
  with "Issue a key".
- A Knowledge-only install: the Catalogs section and any metrics/SQL wording are
  hidden by capability.

## Testing

- Backend:
  - the new routes (shape, admin-only, 404 for a non-service user);
  - `via` computed identically to `catalog_access` for open, user, role and
    not-granted cases;
  - the user-grant routes are idempotent and invalidate the cache.
- Frontend (node tests on pure helpers, as elsewhere):
  - list status from keys and expiry;
  - joining the three list sources with partial failure;
  - the `via` labels.
- Live check after deploy, in a browser with the operator signed in:
  - create an agent, issue a key, grant a collection, cap spend at 0;
  - call it → 402 shows in Activity as refused;
  - disable → calls fail within 30 s;
  - delete.

## Left to the builder

Component split, file names, table styling, and whether the list is a table or cards
on narrow screens.
