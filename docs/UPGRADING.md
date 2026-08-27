# Upgrading

Changes that alter behaviour for people already using a deployment. Everything else is
in the commit history; this file exists for the things an operator has to act on.

## 2026-08 — Infrastructure keeps an event history

**What changed.** Infrastructure has a third tab, **Events**, backed by a new
`system_events` table and an in-process collector.

Before this, the only event surface read live Kubernetes Events for pods that
currently exist. That loses everything twice: the apiserver expires Events after an
hour, and a pod that has been replaced cannot be queried at all — which makes the pod
worth asking about the one you cannot ask about. On 2026-08-27 the live node had
rebooted four hours and fifty-two minutes earlier and `kubectl get events` held
twenty-seven minutes of history.

**What it records.** Pod restarts, OOMKills, probe failures, image-pull and mount
failures, crash loops, evictions, and node reboots. Not request logs, not pod stdout,
not authentication, not queries — those have their own homes and stay there.

A condition that repeats is one row with a count and a first/last seen, not one row
per occurrence.

**One limit worth knowing.** Nothing is collected while the backend is down. A node
reboot is therefore detected after the fact, and the reboot row says the cause is not
recorded rather than inferring one. An empty window is not proof that nothing
happened, and the empty state says so.

**Who can see it.** `service:manage`, the same permission as the rest of
Infrastructure. No new permission was added. `auditor` holds `audit:read` but not
`service:manage`, so it cannot reach Infrastructure at all — unchanged by this, and a
separate decision if you want it.

**Tunable** via `backend.systemEvents`: `enabled` (default true), `tickSeconds`
(120), `retentionDays` (30). Retention has a floor of one day rather than an off
switch — unbounded growth is not acceptable on a single node.

## 2026-08 — Two role changes, and where AI Gateway lives now

**`data_scientist` gains `connector:read`.** They could query a table through Catalog
and Analytics but not see Sources, so "how old is this data?" had no answer for the
person analysing it. Read-only: nothing about it lets them run a sync or edit a
connector.

**Curating concepts is `knowledge:write`, no longer admin.** Concept expansion
rewrites a query before retrieval, which makes the term list a retrieval-quality
control — and the role accountable for retrieval quality already creates the
collections, ingests into them, and schedules their re-embedding. Being unable to
say that two words mean the same thing was the wrong line. Reading the list is
`knowledge:read`; it used to require only a login, which put it outside the
permission vocabulary entirely.

If you would rather keep vocabulary changes with administrators, no role other than
`admin`, `ai_engineer` and `data_scientist` holds `knowledge:write` — restricting it
further means moving those roles, not changing this.

**AI Gateway moved from "Build AI" to "Operate".** Nothing on that page builds
anything: it registers providers, issues keys and reports spend. The audience settled
it — every role that can see it holds `spend:read`, so `data_scientist` and
`business_analyst` could not, while `auditor`, who builds nothing, could. The URL is
unchanged.

**New: Build AI → Connect.** How to call the retrieval and cited-answer endpoints
from your own application, with copyable snippets and the scopes to ask an
administrator for. Visible to roles holding `ai:generate`.

**New: your own model spend.** `GET /api/settings/ai/usage/me` returns only the
caller's. The deployment-wide view still needs `spend:read` — which is the permission
to see *everyone's*, an operator's question — but a role trusted to spend can now see
what it spent.

## 2026-08 — Sign-in is rate limited

**What changed.** Login had no rate limit, no lockout, and no backoff. The endpoint
is on the public internet and verifies a bcrypt hash on every attempt, so it was both
a credential-guessing oracle and a way to spend a single-node deployment's CPU from
anywhere.

Failures are now counted two ways. **Per account**, five failures lock that username
for a minute, doubling with each further failure up to fifteen. **Per address**,
twenty failures in five minutes blocks that address — the per-account counter never
fires against a spray that tries one password against each of many accounts.

Both counters forget: failures older than the window no longer count, so a mistyped
password last month cannot combine with today's to lock a real user out. A successful
sign-in clears that account immediately.

**Tunable** if the defaults do not suit you — `LOGIN_MAX_FAILURES`,
`LOGIN_LOCKOUT_SECONDS`, `LOGIN_LOCKOUT_MAX_SECONDS`, `LOGIN_IP_MAX_FAILURES`,
`LOGIN_IP_WINDOW_SECONDS`.

**One thing to check if you do not use our ingress.** The per-address counter is only
correct if the deployment can see the real client address. Helm sets
`LOGIN_TRUST_PROXY` from `ingress.enabled`, which is the right answer for every
profile in this chart. If you front the backend with your own proxy and disable our
ingress, set it yourself — otherwise every request appears to come from the proxy, and
the per-address budget becomes one bucket shared by everyone, which a single attacker
can exhaust to lock out your whole organisation.

**Known limit.** The counters are per backend replica. With the one or two replicas
this product runs, that costs at most a factor of two on the thresholds. A shared
store is the fix at higher replica counts.

## 2026-08 — Every mutating route is authorized

**What changed.** The previous entry enforced roles on the routes the core UI calls.
It did not cover the rest: an inventory of the running application found **67 mutating
endpoints that required only a login**. Among them, any authenticated user could
create and delete RLS and column-masking policies — the governance system could be
switched off by the people it governs — trigger and delete Airflow DAG runs, drop
streaming sources and sinks, delete pipelines and transforms, and run notebooks.

Every one of them now carries a permission. A test walks the application's own route
graph and fails the build if a mutating endpoint has no authorization dependency, so
this cannot reopen quietly; the exceptions are thirteen routes listed by name with a
reason: four that precede identity (login, logout, and password recovery), two more for
passwordless login, five that act only on the caller's own account, and the two chat
approvals, which authorize against the specific invocation rather than the role.

**Who is affected.** Anyone who was using these endpoints with a role that does not
carry the matching permission — most often `viewer`.

**Two new permissions.** Notebooks and experiment tracking had no permission that
could describe them. A notebook runs arbitrary code against the cluster, so `query:run`
does not cover it.

| Permission | Covers | Held by |
|---|---|---|
| `workbench:read` | browsing notebooks and tracked experiments | every role except `viewer` |
| `workbench:write` | running notebooks, kernels, experiment changes | `admin`, `data_engineer`, `ai_engineer`, `data_scientist` |

**One narrowing worth calling out.** `POST /api/ai/search` now requires `ai:generate`,
not `knowledge:read`. Searching a collection embeds the query, which spends model
tokens — the same reason `ai:generate` exists at all. A `viewer` and a
`business_analyst` can still read collections and open cited answers others produced,
but can no longer run a search themselves. Give them `ai_engineer` or `data_scientist`
if they should.

**What to do.** Nothing, unless someone reports a 403. The refusal names the permission
they need, so they can tell you what to grant.

## 2026-08 — Roles are enforced

**What changed.** Five roles were seeded into the database from the start, but nothing
outside the RLS engine ever read them: the application layer enforced a single
distinction, admin or not. A "viewer" could create, edit, and delete connectors and
knowledge collections, run syncs, and spend model tokens without limit. Three of the
five roles could not even be assigned — the user API allowlisted `admin` and `viewer`
and rejected the rest.

Permissions are now enforced per role. See `app/permissions.py` for the matrix and
`docs/RLS_DESIGN.md` for the separate question of which *rows* a role may read.

**Who is affected.** Every non-admin account. They are all `viewer` today, because
that was the only other assignable role.

**What a viewer keeps:** reading the catalog and knowledge collections, and running
queries. The work people do all day is unchanged.

**What a viewer loses:**

| Capability | Permission now required |
|---|---|
| Create, edit, delete connectors; run a sync | `connector:write` |
| Create, ingest into, delete knowledge collections | `knowledge:write` |
| Save or delete dashboards | `dashboard:write` |
| Ask AI, RAG answers, embedding — anything spending model tokens | `ai:generate` |

This is the removal of access that was granted by accident, not a new restriction. But
it is a behaviour change, and someone relying on it will notice.

**What to do.** Decide which of your users are actually operators and give them a role
that says so:

| Role | For |
|---|---|
| `data_engineer` | brings data in — sources, catalog, transforms |
| `ai_engineer` | builds on it — knowledge collections, RAG, model usage |
| `data_scientist` | queries, collections, dashboards |
| `business_analyst` | queries and dashboards |
| `auditor` | reads governance, the audit log, and spend; writes nothing |
| `viewer` | reads and queries |

Settings → Users, or `PATCH /api/users/{id}` with `{"role": "..."}`. All six are
assignable now.

**If you would rather not decide yet:** promoting existing accounts to `data_engineer`
restores everything they could do before except `ai:generate`. That one is deliberately
separate — per-user model spend is a governance claim this product makes, and an
unbounded ability to spend for anyone who can log in contradicts it.

**Menus follow permissions.** A page appears when the deployment has the feature *and*
the role may use it, so people will see fewer items. The API enforces the same rule;
the menu is not the control.

## 2026-08 — `ADMIN_PASSWORD` is bootstrap-only

Not a change, but a recurring surprise worth stating. The `ADMIN_PASSWORD` value in
`datapond-secrets` seeds the admin hash **once**, on first run. After anyone changes
the admin password — Settings → Reset Password, or the change-password flow — the
database holds a different hash and the secret no longer opens the account. That is
deliberate: the bootstrap must never silently revert an operator's password change.

If the documented `kubectl get secret … ADMIN_PASSWORD` value returns a 401, that is
the expected result of a password change, not a broken secret. Recover through the
password-reset flow.
