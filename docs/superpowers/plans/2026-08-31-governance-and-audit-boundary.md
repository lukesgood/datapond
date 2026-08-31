# Governance and audit boundary — implementation plan

Closes items 3, 4 and part of 6 from `docs/UTILIZATION_PERSONA_ASSESSMENT.md` §6.
Item 1 (SQL permission separation) is done — commit `68a44c6`.

Each task is one TDD cycle: a failing test that names the defect, the smallest change
that passes it, the full suite, then the commit message given here. A task that cannot
be finished honestly stops and says why rather than widening its own scope.

## Verified premises

Checked against the code on 2026-08-31, not assumed:

- `governance.py:180` `_require_admin` passes only `role == "admin"`. `auditor` holds
  `audit:read` and `governance:read` and still cannot read what those name.
- `frontend/lib/auth.ts:25` keeps the token in `localStorage`. Any XSS reads it.
- `postgres-statefulset.yaml` has no pod or container security context. It is not an
  optional add-on; it holds the data.
- `RLS_DEFAULT_DENY` is off, and `app/rls/coverage.py` already computes which tables
  would be blocked if it were turned on.

## Out of scope, and why

Naming these matters as much as the list above — an unbounded plan finishes nothing.

- **§6-2 product scope / messaging.** A product decision, not an engineering one.
- **§6-5 RAG quality** (PDF/DOCX loaders, semantic chunking, hybrid retrieval, citation
  validation, a fixed eval set). Weeks of work and it needs real documents to evaluate
  against. Its own plan.
- **IAM/engine bypass paths.** The credential the application queries with is the one
  connector syncs create Iceberg tables through. Read-only IAM breaks ingestion, so
  this needs a second credential — architectural, its own plan.
- **HttpOnly session + CSRF.** A real gap, and an auth refactor across backend,
  middleware and frontend. Its own plan; C2 below covers the part that is a check
  rather than a redesign.
- **§6-7 demand validation.** Not engineering.
- **Deploying any of this to live.** Stays manual, outside the loop.

---

## A. Governance boundary

### [x] A1 — say when default-deny is safe, and warn while it is not

`RLS_DEFAULT_DENY=false` means a table with no policy passes through unfiltered.
`app/rls/coverage.py` already knows which tables those are; nothing surfaces it where
an operator would see it.

Do **not** flip the default. Flipping it on a deployment whose tables have no policies
denies everything, and that is a decision with data behind it, not a default.

- Startup emits one warning naming the count of tables that would be blocked, when RLS
  is enabled and default-deny is off.
- `/health/ready` state reports `rls: "enforcing"` / `"advisory (N tables uncovered)"`
  / `"off"`, so the readout is somewhere other than a log line.
- A test per state, driven by the coverage function, not by mocking the readout.

Commit: `feat(governance): say which tables default-deny would block, where it is read`

### [x] A2 — collection membership: schema

`ai_collections.owner_id` plus "owner NULL means everyone" is the whole access model.
There is no way to share a collection with three named people.

- Migration `0003_collection_members`: `ai_collection_members(collection_id, user_id,
  role, granted_by, granted_at)`, `role` in (`reader`, `editor`), unique per pair.
- Additive only; no `Contract-of:` needed.
- Tests: the migration file naming rule, `.sql` beside `.py`, and the review rules.

Commit: `feat(knowledge): a collection can be shared with named people — schema`

### [x] A3 — collection membership: enforcement

- Pure function `may_read(collection, user, members)` / `may_write(...)` with the
  precedence written down: admin, then owner, then explicit membership, then the
  legacy `owner_id IS NULL` global read.
- Wire into list, read, search, ingest and delete. Every path, or the model is a
  suggestion.
- API: `GET/POST/DELETE /ai/collections/{name}/members`, gated on `knowledge:write`
  plus ownership.
- Tests first, including that a non-member cannot reach a collection through *any* of
  those paths.

Commit: `feat(knowledge): enforce collection membership on every path that reads one`

### [x] A4 — collection membership: UI

- Members section in the collection settings dialog: who has access, add by username,
  remove, and the reader/editor distinction.
- Presentation logic in `frontend/lib/`, tested with `node --test`, as with
  `lib/system-events.ts`.

Commit: `feat(knowledge): manage collection members from the collection dialog`

---

## B. Audit

### [x] B1 — let the auditor read what its permissions name

`_require_admin` guards endpoints whose route dependency already says
`governance:read` or `audit:read`. The permission matrix and the code disagree, and
the code wins.

- Read-only governance and audit endpoints check the permission, not the role.
- Writes keep the admin gate.
- A test walks the governance and audit routes and asserts no read-only route calls
  `_require_admin`.

Commit: `fix(governance): the auditor role could not read what it is defined to read`

### [x] B2 — a security audit log the caller cannot switch off

`query_history` is the closest thing to an audit trail and `save_history=false` turns
it off. Authorization denials are recorded nowhere.

- Migration `0004_security_audit_log`.
- A writer called from the authorization layer: every 403, every privileged mutation,
  with actor, permission, route and outcome. No caller-supplied flag reaches it.
- Tests: a denial writes a row; a request cannot suppress it.

Commit: `feat(audit): record authorization decisions where the caller cannot reach them`

### [x] B3 — append-only in the database, not by convention

- Migration `0005`: revoke UPDATE and DELETE on the audit tables from the application
  role; retention deletes run as a separate role or a `SECURITY DEFINER` function.
- A test that proves an UPDATE from the application's connection fails.

Commit: `feat(audit): the application may write the audit log and may not rewrite it`

### [x] B4 — retention, and a way to get it out

- Retention window with a floor, pruned on a schedule, same shape as
  `app/system_events.py`.
- `GET /audit/export` (NDJSON, `audit:read`) so the log can reach a SIEM without
  database access.
- Tests for the cutoff and for the export's shape.

Commit: `feat(audit): retention with a floor, and an export that does not need the DB`

### [x] B5 — two governance endpoints have no authentication at all

Found by B1 while doing something else, and deliberately left alone so that task
stayed one task. It listed them by name in an `OPEN_BY_DESIGN` exemption rather than
quietly widening its own scope, which is why they are here instead of lost.

- `GET /governance/stats` and `GET /governance/pii-report` carry no auth dependency.
  A PII report is exactly the thing that must not be readable by an unauthenticated
  caller. Gate both on `governance:read`.
- `POST /governance/rls/preview` calls `_require_admin` although it only previews a
  rewrite. It should follow the same rule B1 applied to the reads.
- Extend `test_governance_auditor_access.py`'s exemption list: once these are gated,
  the list should shrink, and the test should fail if anything is added back to it
  without a reason written down.

Commit: `fix(governance): the PII report needed no login at all`

---

## C. Runtime boundary

### [x] C1 — pod security for the workload that holds the data

`postgres` has no security context. Neither do the optional add-ons, which matters
less. Apply what each image can take; `valkey` is the precedent — three capabilities,
found one CrashLoop at a time.

- postgres first, then any add-on whose image tolerates it.
- A test listing which templates carry a context and which do not, so the gap is
  recorded rather than rediscovered.

Commit: `fix(helm): the database ran with every Linux capability`

### [x] C2 — prove the recheck covers every high-risk route

`_recheck_user` refreshes the role from the database on every authenticated request,
which is what made a forged role claim harmless. That property is worth a test rather
than a reading.

- A test that a token whose role claim exceeds the database's is refused the
  permission the claim would have granted.
- An inventory test: every route holding a write permission goes through the recheck.

Commit: `test(auth): a role claim cannot exceed what the database says`

---

## D. Isolation — the half that is missing

Measured, not assumed. `ai_collections`, `dashboards`, `query_history` and
`rls_policies` all carry an owner. `connector_connections` and `saved_transforms`
carry none.

So the analysis side of this product is per-user and the **data-source side is
shared by everyone**. If one person connects their S3 bucket and another connects
their Postgres, each sees the other's connector and — holding `connector:write`,
which `data_engineer` does — can edit or delete it. That is what stops several people
running their own scenarios today. Not the single catalog: the missing owner.

The pattern is already built. A2, A3 and A4 did exactly this for collections, and
these three tasks copy it.

### [x] D1 — connectors and transforms get an owner, and can be shared

- Migration `0006_resource_ownership`: `owner_id` on `connector_connections` and
  `saved_transforms`, plus `connector_members` and `transform_members` mirroring
  `ai_collection_members` (0003).
- `owner_id` must be **nullable**, and NULL must keep meaning what it means for
  collections: visible to everyone. Every connector that exists today has no owner,
  and a migration that makes them all invisible is an outage.
- A test that the backfill leaves existing rows readable.

Commit: `feat(connectors): a source can belong to someone, and be shared`

### [x] D2 — enforce it on every path that touches a source

- Reuse `app/knowledge_access.py`'s precedence rather than inventing a second one, or
  extract the shared decision if the shapes differ. Two access models that are nearly
  the same is how one of them ends up wrong.
- Wire into list, read, test-connection, sync, schedule, edit, delete, and the
  transform routes. A loop test over the paths, as A3 wrote.
- Sharing API mirroring `/ai/collections/{name}/members`.

Commit: `feat(connectors): enforce source ownership on every path that touches one`

### [x] D3 — manage it from the UI

- Owner and members in the connector detail view, following what A4 built for
  collections. Presentation logic in `frontend/lib/`, tested with `node --test`.

Commit: `feat(connectors): manage who can reach a source, from the source itself`

---

## Finish

After the last task: `/code-review high` over the whole branch, then a fix pass. The
last time this method ran, every task was individually sound and the batch review
found thirteen defects that crossed task boundaries. The review is not optional.
