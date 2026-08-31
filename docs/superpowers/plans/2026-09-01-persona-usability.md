# Persona usability — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> or `superpowers:executing-plans` to implement this task-by-task. Steps use `- [ ]`.

**Goal:** make the six non-admin personas the product declares actually usable by the
people who hold those roles.

**Spec:** `docs/PERSONA_WORKFLOW_AUDIT.md` (2026-08-25) and
`docs/UTILIZATION_PERSONA_ASSESSMENT.md` §4 (2026-08-31). Both are read as the source
of findings; §"Where the audit stands today" below records which of those findings are
already closed, verified against the code on **2026-09-01**, not assumed.

**Architecture:** no new subsystem. Every task either connects an existing permission to
the route or the control that should have used it, or removes a capability that cannot
be made safe. The one shared idea: *the console must offer exactly what the API will
allow, and the API must allow what the role matrix promises.*

**Tech stack:** FastAPI + `app/permissions.py` role matrix, Next.js with
`lib/permissions.tsx` (`/api/me/permissions`), pytest, `node --test`.

## Global constraints

- The role vocabulary is `app/permissions.py`. No task adds a permission name without a
  route that enforces it — "a permission nothing enforces is a lie" is that file's own
  rule and this plan does not break it.
- Hiding a control is never the access control. Every task that changes the UI has a
  backend test for the same boundary.
- Enforcement lives in the API; the console reads `/api/me/permissions`, never the JWT
  in `localStorage`, for what the caller may do.
- Each task is one TDD cycle: a failing test that names the defect, the smallest change
  that passes it, the full backend suite plus `npm test`, then the commit message given.

---

## Where the audit stands today

Checked against the code on 2026-09-01. This is half the deliverable: most of what the
audit found has been closed since it was written, and a plan that re-litigated those
would waste the reader's time.

| Audit finding | Status | Evidence |
|---|---|---|
| P0-1 `viewer` runs arbitrary SQL — `query:run` not split | **Closed** | `/queries/execute` requires `query:run`; `app/sql_kind.py` classifies the statement and a write needs `query:write` (`queries.py:196,231`) |
| P0-3 optional workload mutation with no role check | **Closed** | notebooks 13/13, streaming 11/11, airflow 7/7, transforms and pipelines all carry `require_permission`; the two ungated MLflow routes are `require_admin` |
| P0-4 Search/RAG spend without `ai:generate` | **Closed** | `/ai/search`, `/ai/rag`, `/ai/embed` all gated (`ai_vectors.py:1244,1264,343`) — except inline ingest, see Task 6 |
| P0-5 admin service-account key passes `require_admin` | **Closed** | `require_admin` refuses a service identity; `user:manage` / `settings:write` gate their own routes; creating an admin service account is refused |
| P1-1 auditor's and ai_engineer's declared reads are admin-only | **Closed** | read-only governance and audit routes check the permission; `/audit/export` is `audit:read`; spend routes are `spend:read` and a service account's usage is owner-or-admin |
| Audit log is not append-only, no retention, no SIEM export (§4.5-1) | **Closed** | migration 0005 (trigger + sanctioned prune), `app/audit_retention.py`, `GET /audit/export` |
| Knowledge sharing is owner-or-world, no named people (§4.1) | **Closed** | `ai_collection_members` (0003) + `app/knowledge_access.py` + the Members tab |
| Connectors and transforms have no owner (§6-3) | **Closed** | 0006 + `app/api/source_access.py` + the Access panel |
| `roles` table empty on a migrations-built database | **Closed** | migration 0007 seeds it; `PATCH /auth/users/{id}` can now actually populate `user_roles` |
| **P1-4 the console can only assign `admin` or `viewer`** | **Open** | `frontend/app/settings/page.tsx:477,493,805` — five of seven roles cannot be given to anyone |
| **P1-2 `ai_engineer` cannot ingest a source or schedule freshness** | **Open** | `ingest_source` is `require_admin_or_internal`, `schedule_ingest` is `require_admin` (`ai_vectors.py:920,962`) |
| **P1-4 page actions ignore the caller's permissions** | **Open** | eight pages branch on `getUser()?.role` from the token; `useHasPermission` is used in seven files and not on the pages that mutate |
| **P0-2 residual: the compiler imports submitted Python** | **Open** | `pipeline:write` now gates it, but `app/pipelines/compiler.py:134` still runs `spec.loader.exec_module` in the backend process |
| **P2 duplicate `POST /mlflow/experiments`** | **Open** | declared at `mlflow_integration.py:251` and again at `:904`; the second is unreachable |
| RAG quality — PDF/DOCX, semantic chunking, hybrid retrieval, citation validation (§4.1, §6-5) | **Deferred** | its own plan; weeks of work and it needs real documents to evaluate against |

## Out of scope, and why

- **RAG quality (§6-5).** Named above. It is the largest remaining item for the
  ai_engineer persona and it is not a usability fix; it is a product-quality programme.
- **SELECT-only at the engine and IAM (§6-1 second half).** The application now refuses a
  write statement without `query:write`, but Athena/Trino credentials are still one
  credential for read and write. Splitting them needs a second IAM principal and a
  second engine connection — architectural, and it belongs with the connector-credential
  work, not here.
- **PII beyond Korean structured patterns (§4.5-4).** Names, addresses, free text, NER.
  A different discipline from access control.
- **HA, EKS, signing, weekend uptime (§4.6).** Infrastructure, not persona usability.
- **Enterprise packaging, SLA, contracts (§4.7) and demand validation (§4.8).** Not
  engineering.
- **`business_analyst` cannot use Search/RAG.** Deliberate: that role has no
  `ai:generate` because spend is the thing it must not incur unattended. The audit calls
  it a UX mismatch rather than a defect, and changing it is a product decision about who
  pays for tokens — noted, not scheduled.

---

## A. The roles have to be reachable

### [ ] A1 — the console can assign every role the API accepts

`app/permissions.py` defines seven roles and `PATCH /auth/users/{id}` accepts all of
them. The console offers two. So `data_engineer`, `ai_engineer`, `data_scientist`,
`business_analyst` and `auditor` exist in the matrix, in the tests, and in this plan's
other tasks — and cannot be given to a single person through the product. Every other
persona improvement is invisible until this one lands.

The role list is served, not hard-coded: `/api/me/permissions` already returns
`assignable_roles`, and `service_account_routes` already renders a role list from it. A
second copy in the settings page is a copy that goes stale the next time the matrix
changes.

**Files**
- Modify: `frontend/app/settings/page.tsx` (the `role` type at :477, `newRole` state at
  :493, the toggle at :595, the `Select` at :805)
- Create: `frontend/lib/user-roles.ts` — the presentation logic
- Test: `frontend/lib/user-roles.test.ts` (`node --test`)
- Test: `backend/tests/test_auth.py` — the API half

Steps:

- [ ] Write `frontend/lib/user-roles.test.ts`: `roleOptions(assignable)` returns one
      option per assignable role, each with a one-line description; it preserves the
      server's order; an unknown role coming back from the server still renders rather
      than disappearing; and `nextRoleAfterToggle` is gone — a seven-role product has no
      meaningful "toggle".
- [ ] Run `npm test` — fails, module missing.
- [ ] Write `frontend/lib/user-roles.ts` with `roleOptions()` and `ROLE_DESCRIPTIONS`
      keyed by the seven names, each sentence taken from the role's comment in
      `app/permissions.py` so the two cannot drift silently.
- [ ] Run `npm test` — passes.
- [ ] Carry the list into the context: `PermissionState` in `frontend/lib/permissions.tsx`
      is `{ role, permissions, loaded }` today and the provider already drops
      `assignable_roles` from the same `/api/me/permissions` response on the floor. Add
      `assignableRoles: string[]` to the type and set it there — one fetch, one source.
- [ ] Replace the `"admin" | "viewer"` union in `settings/page.tsx` with `string`, feed
      the `Select` from `usePermissions().assignableRoles` through `roleOptions()`, and
      replace the admin/viewer toggle with the same select on each row.
- [ ] Add to `backend/tests/test_auth.py`: `PATCH /auth/users/{id}` accepts each of the
      seven and refuses a role outside `ASSIGNABLE_ROLES`; and the accepted role lands
      in `user_roles` (0007 made that insert able to find a row).
- [ ] `npx tsc --noEmit && npm run lint && npm test` and the backend suite.

Commit: `feat(settings): a person can be given any role the product defines`

### [ ] A2 — the role list comes from the server, and says what each role can do

An administrator choosing between `data_scientist` and `ai_engineer` from two words is
guessing. `/api/me/permissions` returns `assignable_roles` as bare strings today.

**Files**
- Modify: `backend/app/api/auth.py` (`/me/permissions` response)
- Modify: `frontend/lib/permissions.tsx` (carry the descriptions through)
- Test: `backend/tests/test_service_accounts.py::test_me_permissions_*` neighbours

Steps:

- [ ] Write the failing test: `/me/permissions` returns `assignable_roles` as objects
      carrying `name`, `label` and the permissions each role holds, and the set of names
      still equals `ASSIGNABLE_ROLES` — so a client that only reads names is unaffected.
- [ ] Run it — fails on the current bare-string shape.
- [ ] Build the response from `ROLE_PERMISSIONS`; no second list.
- [ ] Run it — passes.
- [ ] Show the permission count and the two or three headline permissions under each
      option in the settings select.
- [ ] Full suites.

Commit: `feat(auth): the role picker can say what each role is for`

---

## B. The AI engineer's own loop

### [ ] B1 — ingesting a source and scheduling it are `knowledge:write`, not admin

`ai_engineer` is, in the product's own words, the target user. It holds
`knowledge:write` and `ai:generate`, can create a collection, ingest text into it,
search it and ask questions of it — and cannot point it at an S3 prefix or a table,
which is the only ingestion path that scales past pasting text. `POST
/ai/collections/{name}/ingest-source` requires `require_admin_or_internal` and
`POST …/schedule` requires `require_admin`.

The gate that belongs there already exists and is already used by every neighbouring
route: `knowledge:write` on the route, `_collection_id(..., write=True)` for this
collection. The internal automation principal keeps its access — `ingest-source` is on
the `_INTERNAL_AUTOMATION_ROUTES` allowlist and the scheduler calls it — so the
dependency becomes "permission or internal", not "admin or internal".

**Files**
- Modify: `backend/app/api/ai_vectors.py:919-978` (`ingest_source`, `schedule_ingest`)
- Test: `backend/tests/test_knowledge_membership_enforcement.py` (both are already in
  its `_paths()` loop — the loop keeps proving a non-member is refused)
- Test: `backend/tests/test_rag_ingest.py` or a new
  `backend/tests/test_knowledge_lifecycle_roles.py`

Steps:

- [ ] Write the failing test: an `ai_engineer` who owns a collection can call
      `ingest_source` and `schedule_ingest` on it; a `viewer` cannot; a caller holding
      `knowledge:write` who is neither owner nor member is refused by `_collection_id`,
      not by the role.
- [ ] Write the second failing test: the internal automation principal
      (`{"id": None, "role": "admin", "internal": True}`) still reaches `ingest-source`,
      because the freshness scheduler is that caller and a regression there stops every
      scheduled re-embed silently.
- [ ] Run both — the first fails with 403 today.
- [ ] Change `ingest_source` to `require_user_or_internal` plus a
      `require_permission("knowledge:write")` route dependency, and `schedule_ingest` to
      `require_permission("knowledge:write")` + `require_user`; both already call
      `_collection_id(write=True)` inside, which stays.
- [ ] Run the knowledge suites — all pass, including the membership loop.
- [ ] Full backend suite.

Commit: `feat(knowledge): the role that builds collections can also feed them`

### [ ] B2 — the Ingest tab stops offering what the caller cannot do

With B1 landed the API allows it; the console still decides what to show from
`getUser()?.role`. A `viewer` is offered an Ingest tab whose every button 403s, and an
`ai_engineer` was — until B1 — shown one that 403'd for the opposite reason.

**Files**
- Modify: `frontend/app/knowledge/page.tsx` (the tab list and `IngestPanel`)
- Test: `frontend/lib/collection-members.test.ts` neighbour — a new
  `frontend/lib/knowledge-actions.ts` + `.test.ts` for the decision

Steps:

- [ ] Write `frontend/lib/knowledge-actions.test.ts`: `mayIngest(collection, viewer)` is
      true for an admin, the owner, an `editor` member, and false for a reader or a
      caller without `knowledge:write`; `mayAskQuestions(viewer)` follows `ai:generate`,
      which is what makes the Search and Ask tabs honest for a `business_analyst`.
- [ ] Run `npm test` — fails, module missing.
- [ ] Write `frontend/lib/knowledge-actions.ts` in terms of the permission set from
      `usePermissions()` and the collection's ownership — the same shape
      `lib/source-members.ts` uses, and for the same reason.
- [ ] Run `npm test` — passes.
- [ ] Use it in `knowledge/page.tsx` for the Ingest and Schedule tabs, and to render a
      short "you can read this collection but not change it" line instead of a dead
      control.
- [ ] `npx tsc --noEmit && npm run lint && npm test`.

Commit: `feat(knowledge): the tabs match what this person may actually do`

---

## C. The console tells the truth

### [ ] C1 — one source of what the caller may do

Eight pages read `getUser()?.role` out of the token in `localStorage`. That is a value
the browser owns, it carries a role and no permissions, and it cannot express a service
account's narrowed scopes. `lib/permissions.tsx` already fetches `/api/me/permissions`
from the server for exactly this reason and the sidebar already uses it.

**Files**
- Modify: `frontend/app/{settings,experiments,catalog,storage,knowledge,ai,connect}/page.tsx`,
  `frontend/app/services/[id]/page.tsx`
- Modify: `frontend/lib/auth.ts` — leave `getUser()` for identity (name, id) and
  document that role decisions do not come from it
- Test: `frontend/lib/permission-source.test.ts`

Steps:

- [ ] Write the failing test: a repository-wide scan asserting no file under `app/`
      branches on `getUser()?.role` — the same shape as the backend's route-inventory
      tests, so a new page that reaches for the token fails rather than quietly joining
      the other eight.
- [ ] Run `npm test` — fails, listing the eight.
- [ ] Replace each with `useHasPermission("<the permission the route requires>")`,
      taking the permission name from the route's own dependency so the two agree.
- [ ] Run `npm test` — passes.
- [ ] `npx tsc --noEmit && npm run lint`.

Commit: `fix(ui): what you may do comes from the server, not from your token`

### [ ] C2 — a refusal reads as a refusal

`usePermissions()` leaves `loaded` false when its fetch fails, and gated items stay
hidden — correct, and indistinguishable from "you do not have this". A person who
cannot tell the difference between "you may not" and "we could not ask" files the wrong
support ticket, and an auditor cannot record which one happened.

**Files**
- Modify: `frontend/lib/permissions.tsx` (add an `error` state)
- Create: `frontend/components/ui/permission-state.tsx`
- Test: `frontend/lib/permission-state.test.ts`

Steps:

- [ ] Write the failing test: `permissionState({loaded, error, allowed})` returns
      `"allowed" | "denied" | "unknown"`, and `"unknown"` when the fetch failed even if
      `allowed` is false — the case the current boolean cannot express.
- [ ] Run `npm test` — fails.
- [ ] Implement the function and a small component that renders the three states: the
      control, a one-line "your role does not include X — ask an administrator", and a
      "could not check your permissions" with a retry.
- [ ] Run `npm test` — passes.
- [ ] Use it on the pages C1 touched.

Commit: `feat(ui): "you may not" and "we could not ask" stop looking the same`

---

## D. Remove what cannot be made safe

### [ ] D1 — the pipeline compiler stops importing what it was sent

`/pipelines/validate` and `/pipelines/compile` now require `pipeline:write`, which
closed the audit's "every authenticated role" finding. What is left is narrower and
still wrong: `app/pipelines/compiler.py:134` runs `spec.loader.exec_module(module)` on
submitted Python, so a `data_engineer` — a role about connecting sources, not about
running code as the backend — gets the backend pod's files, network and credentials.

`/pipelines/deploy` already refuses with 501 and a written reason. A validate endpoint
that executes the code for a deploy that cannot happen is all cost and no product.

- Parse rather than import: read the submitted module with `ast` and report the pipeline
  definition it declares. A definition this product cannot deploy is a definition it
  does not need to execute to describe.
- If the AST route cannot express what validation needs, the honest alternative is to
  refuse validate/compile with the same 501 and the same sentence as deploy, and say so
  in the UI. Both are acceptable outcomes of this task; silently keeping `exec_module`
  is not.

**Files**
- Modify: `backend/app/pipelines/compiler.py:110-150`
- Modify: `backend/app/api/pipelines.py:149-278` if the refusal path is taken
- Test: `backend/tests/test_pipeline_compiler_safety.py`

Steps:

- [ ] Write the failing test: compiling a module whose top level writes a marker file
      leaves no marker — the audit's own reproduction, kept as a test.
- [ ] Run it — fails; the marker exists.
- [ ] Replace the import with an `ast` walk that collects the declared pipeline, or make
      both routes refuse with 501; either way the marker test passes.
- [ ] Run it and the pipeline suites.
- [ ] If the refusal path was taken, make the Pipelines page say the builder is not
      available in this deployment, in the same words the API returns.

Commit: `fix(pipelines): validating a pipeline stops running it`

### [ ] D2 — one route, one declaration

`POST /mlflow/experiments` is declared twice (`mlflow_integration.py:251` and `:904`).
FastAPI serves the first; the second is dead code that a reader will nonetheless edit.

**Files**
- Modify: `backend/app/api/mlflow_integration.py`
- Test: `backend/tests/test_route_uniqueness.py`

Steps:

- [ ] Write the failing test: no (method, path) pair is declared twice across
      `main.app.routes`. It is a whole-application property, so it belongs in its own
      file and covers every router, not just this one.
- [ ] Run it — fails, naming the MLflow route.
- [ ] Delete the later declaration after checking the two bodies for any difference
      worth keeping; if they differ, keep the behaviour the first one has, because that
      is what has been running.
- [ ] Run it — passes.

Commit: `fix(mlflow): the same route was declared twice`

---

## E. Small, and paid for by the same reasoning

### [ ] E1 — inline ingest spends model tokens under a spending permission

`POST /ai/collections/{name}/ingest` requires `knowledge:write` and calls `_embed`,
which spends. Search, RAG and embed all carry `ai:generate`; this one path does not, so
a role granted `knowledge:write` without `ai:generate` can still run up an embedding
bill. `data_engineer` is exactly that role.

**Files**
- Modify: `backend/app/api/ai_vectors.py:780`
- Test: `backend/tests/test_rag_ingest.py`

Steps:

- [ ] Write the failing test: a caller holding `knowledge:write` and not `ai:generate`
      is refused before `_embed` is called — asserted by a fake `_embed` that fails the
      test if it runs at all, the same shape the egress tests use.
- [ ] Run it — fails; the ingest proceeds.
- [ ] Add `ai:generate` beside `knowledge:write` on the route.
- [ ] Run the knowledge suites; check no fixture relied on ingesting without it.

Commit: `fix(knowledge): pasting text into a collection spends tokens, and says so`

---

## Finish

After the last task: `/code-review high` over the branch, then a fix pass. The previous
run of this method found thirteen defects that crossed task boundaries and the run
before it found fifteen; each task being individually sound is not evidence about the
batch.

Then re-check this plan's own status table against the code and update
`docs/PERSONA_WORKFLOW_AUDIT.md` §5 with what is closed — an audit whose findings are
fixed but still written as open is a document that costs its next reader an afternoon.
