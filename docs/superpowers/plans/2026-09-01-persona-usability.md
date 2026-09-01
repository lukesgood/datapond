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

Checked against the code on 2026-09-01, and re-checked after the run finished. This is
half the deliverable: most of what the audit found had been closed before this plan was
written, and a plan that re-litigated those would waste the reader's time. The rows this
run closed name the task and the commit; the remaining "Deferred" row is the only one
still open, and it is out of scope by design (see below).

| Audit finding | Status | Evidence |
|---|---|---|
| P0-1 `viewer` runs arbitrary SQL — `query:run` not split | **Closed** | `/queries/execute` requires `query:run`; `app/sql_kind.py` classifies the statement and a write needs `query:write` (`queries.py:196,231`) |
| P0-3 optional workload mutation with no role check | **Closed** | notebooks 13/13, streaming 11/11, airflow 7/7, transforms and pipelines all carry `require_permission`; the two ungated MLflow routes are `require_admin` |
| P0-4 Search/RAG spend without `ai:generate` | **Closed** | `/ai/search`, `/ai/rag`, `/ai/embed` were already gated; E1 (`b36ea36`) added `ai:generate` to `POST …/ingest`, and the final-review fix (`1ed0c71`) added it to `ingest-source` and `schedule` — every path that reaches `_embed`, or arms `rag_scheduler` to reach it, now carries it |
| P0-5 admin service-account key passes `require_admin` | **Closed** | `require_admin` refuses a service identity; `user:manage` / `settings:write` gate their own routes; creating an admin service account is refused |
| P1-1 auditor's and ai_engineer's declared reads are admin-only | **Closed** | read-only governance and audit routes check the permission; `/audit/export` is `audit:read`; spend routes are `spend:read` and a service account's usage is owner-or-admin |
| Audit log is not append-only, no retention, no SIEM export (§4.5-1) | **Closed** | migration 0005 (trigger + sanctioned prune), `app/audit_retention.py`, `GET /audit/export` |
| Knowledge sharing is owner-or-world, no named people (§4.1) | **Closed** | `ai_collection_members` (0003) + `app/knowledge_access.py` + the Members tab |
| Connectors and transforms have no owner (§6-3) | **Closed** | 0006 + `app/api/source_access.py` + the Access panel |
| `roles` table empty on a migrations-built database | **Closed** | migration 0007 seeds it; `PATCH /auth/users/{id}` can now actually populate `user_roles` |
| P1-4 the console can only assign `admin` or `viewer` | **Closed** (A1, A2) | `frontend/lib/user-roles.ts` renders one option per `assignable_roles`, fed from `/api/me/permissions` through `PermissionState.assignableRoles`; the response now carries `name`/`label`/permissions per role (`55685dc`, `30981f1`, `f5ace13`) |
| P1-2 `ai_engineer` cannot ingest a source or schedule freshness | **Closed** (B1, B2) | both routes are `knowledge:write` + `ai:generate` + `_collection_id(write=True)`, and the X-Internal-Key callback still reaches `ingest-source` (`8b3b6d4`, `1ed0c71`); the console's Ingest/Schedule tabs read the same decision from `frontend/lib/knowledge-actions.ts` (`bf0e74f`) |
| P1-4 page actions ignore the caller's permissions | **Closed** (C1, C2) | no file under `app/` branches on `getUser()?.role` any more, and `frontend/lib/permission-source.test.ts` walks the directory so a ninth page cannot quietly join them; "you may not" and "we could not ask" are now distinct states (`f143a06`, `dbf7178`) |
| P0-2 residual: the compiler imports submitted Python | **Closed** (D1) | `spec.loader.exec_module` is gone; `app/pipelines/ast_reader.py` reads the declaration and `tests/test_pipeline_compiler_safety.py` keeps the marker-file reproduction as a test (`700d05e`, `6eaaa94`) |
| P2 duplicate `POST /mlflow/experiments` | **Closed** (D2) | the second declaration is deleted and `tests/test_route_uniqueness.py` now asserts the whole-application property across every router (`53dfe39`) |
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

### [x] A1 — the console can assign every role the API accepts

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

### [x] A2 — the role list comes from the server, and says what each role can do

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

### [x] B1 — ingesting a source and scheduling it are `knowledge:write`, not admin

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

### [x] B2 — the Ingest tab stops offering what the caller cannot do

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

### [x] C1 — one source of what the caller may do

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

### [x] C2 — a refusal reads as a refusal

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

### [x] D1 — the pipeline compiler stops importing what it was sent

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

### [x] D2 — one route, one declaration

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

### [x] E1 — inline ingest spends model tokens under a spending permission

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

### What the finish pass actually found

Eleven commits (`8ac7d5d..53dfe39`) implemented the nine tasks. The review over the
branch then found six things, and the prediction above held: the two that mattered
crossed task boundaries rather than living inside one.

- **The spend permission stopped one route short.** E1 added `ai:generate` to
  `POST …/ingest` because it embeds. B1 had already moved `ingest-source` and
  `schedule` from `require_admin*` to `knowledge:write`, and E1 did not come back to
  them — so B1 opened the door and E1 closed only one of the three behind it. Worse
  for `schedule`, which spends nothing during the request and instead arms
  `rag_scheduler` to spend on every tick, unattended. Fixed in `1ed0c71`, with the
  console's `mayIngest` split against a new `mayWriteCollection` so that the controls
  that embed nothing — delete a collection, cancel a schedule — do not inherit a
  spending permission they never needed.
- **A red test reported as environmental.** C1 replaced the exact line
  `test_operational_flows.py` pinned by string, and the failure was written off as
  local environment noise. It was this branch. Fixed in `bcf461f`.
- **The two permission guards were verbatim copies.** `require_permission_or_internal`
  duplicated the whole of `require_permission` — audit records, refusal wording and
  all — for the sake of three lines of difference. Extracted in `c4eae96`.

## Follow-ups filed by this run

Found while working, real, and out of this plan's scope. Recorded here rather than
fixed, because neither belongs to a persona-usability task and neither should be
discovered a third time.

### [x] F1 — quality checks configured in the pipeline builder have never reached a pipeline

Both pipeline builders in the console emit a decorator the DSL does not define:

```python
@quality(table="bronze_orders")
def check_bronze_orders(): return "id IS NOT NULL"
```

— `frontend/app/pipelines/new/page.tsx:346` and
`frontend/components/pipelines/create-pipeline-modal.tsx:126`. But
`backend/app/pipelines/decorators.py:270` defines `quality` as a *namespace class*
whose members are `quality.expect(name, condition)`, `quality.expect_or_drop(...)` and
so on, applied **below** `@live_table` on the same function. There is no `quality(...)`
call form and no `table=` keyword anywhere in the DSL. So every quality check a user
configures in the builder is dropped, and the compiled pipeline's
`table_def.quality_checks` is empty.

This is pre-existing — it predates this plan — but D1 changed how it fails, which is
why it is worth writing down now. When the compiler imported the submitted module,
`quality(table=...)` raised `TypeError: quality() takes no arguments` and validation
failed loudly. Since D1 the source is parsed rather than executed, so
`app/pipelines/ast_reader.py` records a note — *"'@quality' on 'check_x' is not a
DataPond pipeline decorator and was ignored"* — and validation succeeds. A user who
adds a quality check now gets a green validation and no quality check. Reproduced on
2026-09-01 against `read_pipeline_source`: one table, zero `quality_checks`, one note.

Whoever picks this up has to decide which side is wrong before writing anything:

- If the builder is wrong, it should emit the decorator the DSL actually has —
  `@live_table(...)` above `@quality.expect("name", "condition")` on the same function
  — and `ast_reader` should read `quality.expect` attribute calls into
  `table_def.quality_checks`.
- If the DSL is wrong, `quality(table=...)` should become a real decorator form and
  the namespace class keeps working alongside it.

Either way the acceptance is the same: a check configured in the builder appears in the
compiled pipeline's `quality_checks`, with a test that fails if it does not — and the
`ast_reader` note stops being the only thing standing between a user and a silently
dropped rule. Consider also whether an ignored-decorator note should be surfaced in the
validation response the Pipelines page renders, rather than only in the compiler's
notes: a warning nobody sees is the mechanism that let this survive.

**Done** — commit `34144cc`. Both builders now write the decorator through
`frontend/lib/pipeline-quality.ts`, which emits `@quality.expect_or_fail(name, condition)`
between `@live_table(...)` and the `def`, where the DSL reads it. `expect_or_fail`
because the field's help text says "halts on failure"; `expect` logs and
`expect_or_drop` filters rows, which are different promises.
`backend/tests/test_pipeline_quality_checks.py` runs the emitted string through the real
compiler and asserts the check reaches the table, carries `QualityAction.FAIL` and
appears in the generated DAG — and keeps the old shape as a test that compiles
successfully and produces nothing, which is why nobody noticed it for months.

Still true after the fix, and out of its scope: `dag_generator._generate_quality_task`
binds `_not_implemented` and lists the checks as comments, and `/pipelines/deploy`
refuses with 501. The check reaches the compiled artifact; nothing executes it yet.

### [x] F2 — `business_analyst` and the Search/Ask tabs — decided: no change

Not a defect, and already argued in "Out of scope" above: the role has no `ai:generate`
because unattended spend is the thing it must not incur. C2 and B2 mean that persona
now gets an honest "your role does not include ai:generate" instead of a dead control,
which is the whole of what this plan owed it. Whether the role should hold the
permission at all is a product decision about who pays for tokens — it needs an owner,
not an implementation.

**Decided 2026-09-01: `business_analyst` does not get `ai:generate`, and the answer for
an analyst who needs to ask documents is a different role, not a wider one.**

The argument turns on what the product can and cannot enforce. It attributes spend per
user, reports it, and raises budget alerts — all after the money is spent. There is no
per-role or per-user cap that refuses a request at the gateway. Granting the permission
to the broadest non-viewer role therefore hands unattended spend to the largest group of
accounts in a typical deployment, with detection rather than prevention behind it.

The escape hatch already exists and, as of this run, is actually reachable:
`data_scientist` holds `catalog:read`, `knowledge:read`, `knowledge:write`, `query:run`,
`ai:generate`, `dashboard:write`, `connector:read` and the workbench pair — an analyst
who must ask questions of documents is given that role instead. Until A1 landed, an
administrator could not assign it at all (the console offered `admin` and `viewer`),
which is a large part of why this looked like a matrix problem rather than an
assignment problem. A2 then made the difference visible at the moment of choosing: the
role picker lists each role's permissions, so `ai:generate` is the line that separates
the two.

Revisit this if a per-user spend cap that refuses at the gateway is ever implemented —
at that point the objection above is gone, and granting the permission becomes cheap to
reverse. Recorded here rather than closed silently, because "no change" is a decision
and the next person deserves the reasoning rather than the absence of a task.

### [x] F3 — nothing asserts that a route which spends is gated on spending

The final review of this run turned on one question — which routes reach `_embed` — and
the answer was found by reading, not by a test. `tests/test_security_boundaries.py`
pins `/ai/search`, `/ai/rag` and `/ai/embed` by name, and `tests/test_rag_ingest.py`
now pins the three ingest routes the same way. A fourth path to `_embed`, or to the
LiteLLM chat call, carries no permission until someone notices — which is exactly how
`ingest-source` and `schedule` shipped this run requiring `knowledge:write` and nothing
else, six commits after the sibling route was fixed for that precise reason.

The property is structural and testable the way `tests/test_route_uniqueness.py` and
`test_every_permission_marked_write_shaped_reaches_require_user` already are: walk
`main.app.routes`, find every handler whose call graph reaches `_embed`, `_rerank` or
the chat completion, and assert each declares `ai:generate`. The call-graph half is the
work — an import-time walk of the module's AST, or a runtime probe that patches the
spend functions and drives each route, both have precedent in this repo.

Filed by the re-review of the final fix wave, which judged it a coverage gap rather
than a live defect: every spend route carries the permission today.

**Done** — commit `5d09bef`, `backend/tests/test_spend_routes_declare_ai_generate.py`.
It seeds on the three gateway endpoints that bill (`/v1/embeddings`, `/v1/rerank`,
`/v1/chat/completions`), walks the call graph backwards across modules, and requires
every route whose handler reaches one to declare `ai:generate`. Two guard tests keep it
from passing vacuously.

It found two routes on its first run, and the first was a live hole of the same shape as
the one that prompted this item: `POST /connectors/sample-db/activate` required
`connector:write` and embedded the entire sample corpus into Knowledge collections — a
`data_engineer` holds that permission and not `ai:generate`, and the spend is two calls
away through an in-process handler call, which is why nobody had connected the two.
`POST /settings/ai/backends/{model_name}/test` sends a real completion under
`require_admin`, which already implies the permission; it now says so.

Its blind spots are in the module docstring: a call through a variable, a registry
lookup, `getattr`, or a task with no direct call edge.
