# Upgrading

Changes that alter behaviour for people already using a deployment. Everything else is
in the commit history; this file exists for the things an operator has to act on.

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
