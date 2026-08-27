# Migrations

The schema has one definition: the revisions in `versions/`. It used to have two —
these files and eight startup bootstraps issuing `CREATE TABLE IF NOT EXISTS` — and
nothing compared them. The bootstraps were removed once a database built from
`0001_baseline` proved to differ by zero lines after all eight had run against it.

## How they run

A Helm `pre-install,pre-upgrade` hook Job runs `python -m app.migrations` — one pod,
once, before the new image starts. If it fails the release stops there.

The application **checks and never migrates**. At head it is ready; behind head it
refuses traffic and names the revision it expected, which catches an image upgraded
without the Job having run. It also verifies the core tables are actually present,
because `alembic_version` records a decision — stamping a legacy database asserted it
was at the baseline without inspecting anything.

Running them by hand:

```bash
cd backend && python -m app.migrations
```

## The rule: expand, then contract

`helm --atomic` rolls back the release. **It does not roll back the database.** A
migration that ran before a failed deploy leaves the previous image running against
the new schema. Nothing in the tooling prevents that, so the shape of the change has
to.

Split anything that removes or narrows into two releases:

| Release | Migration | Code |
|---|---|---|
| **N** (expand) | add the column, nullable, with a default | write both old and new; read new, fall back to old |
| **N+1** (contract) | backfill, then drop the old column | read new only |

Between them, either image runs against either schema. That is the whole property, and
it is what makes a rollback something you can do without thinking about it.

### What this means in practice

- **Adding a nullable column** — safe alone. The previous release ignores it.
- **Adding a `NOT NULL` column** — needs a default, and even then the previous release
  is not writing it. Safe only if nothing depends on the value being meaningful.
- **`SET NOT NULL` on an existing column** — its own release, after everything writes
  it. Otherwise inserts from the previous image start failing while the deploy reports
  success.
- **Dropping anything** — one release after the code stopped using it. Never the same
  one.
- **Renaming** — there is no safe single-release rename. Add the new name, backfill,
  switch reads, then drop the old one. A rename is a drop and an add wearing one name.
- **`CREATE INDEX` on a large table** — use `CONCURRENTLY`, outside a transaction. A
  plain `CREATE INDEX` locks writes for its duration, and the Job holds the release
  open the whole time.

### The check

`tests/test_migration_review_rules.py` fails on a migration that drops, renames or
sets `NOT NULL` unless the file's docstring carries a line naming the release that
freed it:

```
Contract-of: 0004_stop_reading_nickname
```

The check cannot tell whether the drop is safe — that depends on which code is still
running, which is not in the file. What it can do is refuse to let the question go
unasked. The line is a claim a reviewer can disagree with; silence is not.

## Adding one

```bash
cd backend && alembic revision -m "add nickname to users"
```

Write the SQL in the generated file, or beside it as `<revision>.sql` and execute it
with `op.get_bind().exec_driver_sql(...)` — as `0001_baseline` does, because 1,189
lines of DDL inside a Python string is unreadable, and unreadable is how a schema
definition goes wrong without anyone noticing.

Only revision files belong in `versions/`. Alembic imports *every* `.py` there, so a
stray one is parsed as Python and takes the whole migration down — which is how an
hour went into `source code string cannot contain null bytes` when a macOS tarball
carried an AppleDouble companion into a container. A test fails on anything in there
that is not named like a revision.

## Downgrades

`0001_baseline` raises rather than dropping 41 tables. Below a baseline is an empty
database, and that is a restore — see `docs/DISASTER_RECOVERY.md`, not a migration.

For later revisions, write `downgrade()` if it is genuinely reversible and leave it
raising if it is not. An untested downgrade that looks plausible is worse than one
that refuses: it offers a way back that nobody has walked.
