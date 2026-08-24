# DataPond Row-Level Security and Column Masking

## 1. What this covers

A single set of policy rows in PostgreSQL drives row filtering and column masking across
three enforcement points. The policy store is the contract; each enforcement point is an
adapter that renders those rows into whatever the surrounding runtime understands.

This document describes what is implemented. Section 9 states plainly what is not.

**Status:** Layer 1 is enforced on the query path and is the layer that matters on the
current AWS reference profile. Layer 2 requires Trino and is therefore inert wherever
Trino is disabled. Layer 3 ships a soft check endpoint and a deny-prefix generator; the
hard S3 boundary is applied by an operator, not by the product.

## 2. Layers

| Layer | Module | Enforces on | Active when |
|---|---|---|---|
| 1 · Backend engine | `backend/app/rls/engine.py` | `POST /api/queries/execute` and the governance preview endpoint | `RLS_ENABLED=true` |
| 2 · Trino file-based ACL | `backend/app/rls/trino_acl.py` | direct Trino connections (BI, JDBC) that never touch the backend | Trino deployed **and** rules applied |
| 3 · Direct-read guard | `backend/app/rls/duckdb_guard.py` | JupyterLab → DuckDB → object storage reads | Jupyter add-on deployed |

Layer 1 is the only layer that enforces by itself. Layers 2 and 3 exist because a user who
bypasses the backend also bypasses Layer 1 — they close that hole for the runtimes that can
be reached without the API.

## 3. Configuration

| Env | Default | Meaning |
|---|---:|---|
| `RLS_ENABLED` | `false` | Master gate for Layer 1. Off ⇒ `execute_query` never calls `enforce()`. |
| `RLS_DEFAULT_DENY` | `false` | Whether a referenced table with **no** policy is blocked. |
| `RLS_ADMIN_BYPASS` | `false` | Whether admins skip enforcement entirely. |
| `RLS_DEFAULT_CATALOG` | `TRINO_CATALOG` → `iceberg` | Catalog assumed for a table reference that names none. |
| `RLS_DEFAULT_SCHEMA` | `TRINO_SCHEMA` → `default` | Schema assumed for a bare table name. |

Helm derives all five from `governance.rls.*` and `catalog.backend`
(`helm/datapond/templates/backend-deployment.yaml`). `RLS_DEFAULT_CATALOG` and
`RLS_DEFAULT_SCHEMA` are derived from the **same** expression as the query engine's own
`ATHENA_DATABASE`, deliberately: if the schema RLS assumes and the schema the engine
resolves against ever diverge, a policy on `sales.orders` stops matching a query that says
`FROM orders`. See §7.

`RLS_DEFAULT_DENY=false` is what makes `RLS_ENABLED=true` safe to flip on a
policy-empty database. With no policies and no masks, `enforce()` returns the SQL
byte-for-byte and never invokes sqlglot (`engine.py` early return) — so enabling RLS
before writing any policy is a genuine no-op rather than a lockout.

## 4. Data model

`backend/schema/rls_migration.sql`, applied on every startup by
`backend/app/rls/migrate.py`. Every statement is `IF NOT EXISTS` / `ON CONFLICT`, so it is
a no-op on an already-migrated database.

| Table | Holds |
|---|---|
| `rls_policies` | `(catalog_name, schema_name, table_name)` + `filter_expression`, `priority`, `enabled` |
| `rls_policy_roles` | which roles a policy targets, and which are `is_exempt` |
| `column_masking_policies` | as above, plus `column_name`, `masking_type`, `custom_expression` |
| `masking_policy_roles` | role targeting / exemption for masks |
| `roles`, `user_roles` | role catalogue and assignment (seeded with five system roles) |
| `users.attributes` (JSONB) | per-user values available to filter expressions (§6) |
| `auth_audit_log` | denial records (`event_type='permission_denied'`) |

The migration also backfills `user_roles` from a minimal `users.role` column when that
column exists, so a database bootstrapped from either the minimal or the full `auth.sql`
shape converges on the same role model.

## 5. Layer 1 enforcement

`enforce(sql, user, policies, masks, *, sensitive_block=False, dialect="trino")` is pure:
the caller pre-fetches policy rows, the function returns rewritten SQL or raises
`RlsDenied`. No I/O, so the whole policy algebra is unit-testable without a cluster.

Per table reference in the parsed statement:

1. **Canonicalise** to `catalog.schema.table`, lowercased (`_qualify`).
2. **No policy for that table** → blocked if `RLS_DEFAULT_DENY`, otherwise skipped.
3. **`sensitive_block=True`** (Layer 3 caller) → any policy-bearing table is denied outright.
4. **Resolve applicable policies** — enabled, targeting one of the user's roles, and *no*
   matching role marked exempt. An exempt role frees the user from that policy entirely.
5. **AND-combine** the surviving filter expressions in `priority` order.
6. **Resolve masks** for the same table by the same role/exemption rule.
7. **Rewrite** the table reference in place:

```sql
FROM cat.sch.orders  -->  FROM (SELECT * EXCEPT (email), <mask_expr> AS email
                                FROM cat.sch.orders
                                WHERE region = 'us-east') AS orders
```

The subquery keeps the original alias, so the rest of the query is untouched. Masked
columns are re-projected under their own names via `SELECT * EXCEPT (...)`, preserving
column naming for the caller.

A user exempt from every policy on a table, with no applicable masks, passes through
unwrapped — the table is registered, so access is allowed and nothing needs rewriting.

**Failure posture.** Unparseable SQL raises `RlsDenied` rather than reaching the engine.
`execute_query` maps `RlsDenied` to 403, and maps *any other* exception from the RLS block
to 403 as well — an enforcement error blocks the query, it never degrades to unfiltered.

## 6. Attribute templating

A `filter_expression` may reference the calling user with
`current_user_attribute('<key>')`. At enforcement time the key is matched against
`^[A-Za-z0-9_]{1,64}$`, looked up in `users.attributes`, and rendered as a SQL literal by
`sql_literal()` (single-quote escaped, typed for bool/int/float).

An unknown or invalid key becomes `NULL`, which makes the predicate fail closed rather
than raise. User-supplied values are never string-interpolated into SQL unescaped.

```sql
-- policy filter_expression
region = current_user_attribute('region') AND clearance >= current_user_attribute('level')
```

## 7. Unqualified table references

A bare `FROM orders` has to be attributed to a schema before policies can be matched, and
the schema the engine will actually use must be the same one. Two mechanisms keep them
aligned:

- `backend/app/api/table_resolver.py` resolves bare names against the catalog **before**
  `enforce()` runs, rewriting `orders` to `sales.orders` when exactly one namespace
  contains it, and rejecting the query when zero or several do. RLS therefore sees a fully
  qualified name in the normal case.
- `_qualify()`'s fallback (`RLS_DEFAULT_CATALOG` / `RLS_DEFAULT_SCHEMA`) covers the RLS
  entry points that do not go through the resolver — Layer 3's direct-read check and the
  governance preview. Helm derives it from the same value as the engine's session database
  so the two cannot drift.

Resolution is fail-closed for exactly this reason: handing an unresolvable bare name to
the engine is what would let a query miss its policy.

## 8. Masking types

`mask_expression()` emits Trino-dialect SQL:

| `masking_type` | Result |
|---|---|
| `full` | `'***'` |
| `null` | `NULL` |
| `hash` | `to_hex(sha256(to_utf8(CAST(col AS VARCHAR))))` |
| `partial_email` | first character + `***` + domain |
| `partial_ssn` | `***-**-` + last 4 |
| `partial_phone` | `***-***-` + last 4 |
| `custom` | the policy's `custom_expression` verbatim |

An unrecognised type falls back to `'***'` rather than passing the value through.

`custom` inserts operator-authored SQL into the query unchanged. Treat write access to
`column_masking_policies` as equivalent to SQL execution rights.

## 9. Limits

- **Layer 1 covers the backend query path only.** `/api/queries/execute` and the
  governance preview. Anything reaching the data another way is Layer 2's or Layer 3's
  problem — or uncovered.
- **Layer 2 needs Trino.** `generate_rules()` emits a Trino file-based access-control
  `rules.json` and `POST /api/governance/rls/trino-rules/apply` patches it into the
  `trino-access-control` ConfigMap. On profiles where Trino is disabled — including the
  current AWS single-node reference, which queries through Athena — there is nothing to
  apply it to. **A BI tool connecting straight to Athena is not covered by any layer.**
  Lake Formation is the AWS-native equivalent and is roadmap, not implemented.
- **Layer 3's hard boundary is manual.** `check_direct_read()` is a soft, sanctioned-path
  check a notebook helper calls; `seaweedfs_deny_prefixes()` only *computes* the S3
  prefixes to deny. Applying them to the shared Jupyter identity is an operator action.
- **Layer 3's two endpoints are unauthenticated by design**, because the notebook helper
  that calls them carries no token. `GET /governance/rls/sensitive-tables` therefore
  discloses which tables carry policies and the S3 prefixes behind them to any caller that
  can reach the API. That is a deliberate trade for the soft-guard UX, not an oversight —
  but it means the sensitive-table list is not itself a secret, and the Jupyter add-on
  should not be exposed on an untrusted network without fronting these routes.
- **Default-deny defaults disagree between layers.** `_default_deny_enabled()` defaults to
  `false`; the Trino-rules endpoints (`governance.py`) read the same variable with a
  default of `true`. Any Helm deploy sets the variable explicitly, so they agree in
  practice — but an environment with it unset would filter differently at Layer 1 than the
  generated `rules.json` does at Layer 2.
- **Masking SQL is Trino-dialect.** The rewrite is emitted through sqlglot's `athena`
  dialect and covered by unit tests (`test_enforce_mask_survives_athena_dialect`), and
  Athena engine v3 is Trino-derived, but the masking path has not yet been run against
  live Athena. Unit coverage of the emitted string is not proof the service accepts it.
- **Rewriting, not database-native RLS.** Enforcement is SQL rewriting in the application
  layer. It is not PostgreSQL `CREATE POLICY`, and collection access control
  (`ai_collections.owner_id`) is a separate application-level ACL — not this engine.

## 10. API surface

All under `/api`. See `backend/app/api/governance.py`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET`/`POST`/`PATCH`/`DELETE` | `/governance/rls/policies[/{id}]` | admin | Row-filter policy CRUD |
| `GET`/`POST`/`DELETE` | `/governance/masking/policies[/{id}]` | admin | Column-mask policy CRUD |
| `POST` | `/governance/rls/preview` | admin | Show the rewritten SQL for a given user without running it |
| `GET` | `/governance/rls/trino-rules` | admin | Preview the generated `rules.json` |
| `POST` | `/governance/rls/trino-rules/apply` | admin | Write it into the Trino ConfigMap |
| `GET` | `/governance/rls/sensitive-tables` | **none** | Policy-bearing tables + computed S3 deny prefixes |
| `POST` | `/governance/rls/check-direct-read` | **none** | Layer 3 soft check |

The last two are deliberately unauthenticated: the JupyterLab DuckDB helper calls them
before a direct read, and it holds no user token. The consequence is stated in §9 — treat
the sensitive-table list as readable by anything that can reach the API.

`rls` in `GET /api/capabilities` reflects `FEATURE_RLS`, which Helm derives from
`governance.rls.enabled` — the same source as `RLS_ENABLED`, so the UI gate and the
enforcement gate cannot disagree.

## 11. Tests

| File | Covers |
|---|---|
| `backend/tests/test_rls_engine.py` | policy resolution, exemption, attribute binding, masking, default-deny, qualification defaults |
| `backend/tests/test_trino_acl.py` | `rules.json` generation |
| `backend/tests/test_duckdb_guard.py` | sensitive-table detection, deny-prefix computation |
| `backend/tests/test_table_resolver.py` | qualification before enforcement (§7) |
| `backend/tests/test_query_engine.py` | RLS receives the qualified table name |

The engine's purity is the point: all of the above run without PostgreSQL, Trino, or a
cluster.
