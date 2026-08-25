# Upgrading

Changes that alter behaviour for people already using a deployment. Everything else is
in the commit history; this file exists for the things an operator has to act on.

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
