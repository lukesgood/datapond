"""B3 — the audit tables become append-only in the database, not by convention.

`security_audit_log` (B2) and `auth_audit_log` (baseline) were append-only only in the
sense that nothing in the application *chose* to update or delete them. Nothing in
PostgreSQL stopped it. Migration `0005_audit_append_only` closes that gap for UPDATE
unconditionally, and for DELETE everywhere except one sanctioned retention path.

**What this honestly does and does not prevent — read this before trusting the name
of this test module:**

The backend, in every deployment profile this repo ships (`migrations/env.py` builds
the Alembic URL from the same `app.database.connection.DATABASE_URL` the application
connects with; `helm/datapond/templates/backend-deployment.yaml` wires one
`POSTGRES_USER`/`POSTGRES_PASSWORD` pair to both), runs its own migrations. The role
that creates `security_audit_log` and `auth_audit_log` (via `CREATE TABLE`) is the
same role the application queries through, and on the AWS reference that role is the
Aurora cluster's master user. That role therefore **owns** both tables.

PostgreSQL lets an owner revoke their own ordinary privileges (UPDATE here) — the
`REVOKE` below is real, not a no-op, and a bare `UPDATE security_audit_log ...` from
the application's normal connection will fail with `permission denied` after this
migration runs. But per the PostgreSQL manual, an owner can *always re-grant those
privileges to themselves*, because granting on an object you own needs no privilege
of its own — only ownership. And the right to alter or drop an object (including
`DROP TRIGGER` or `ALTER TABLE ... DISABLE TRIGGER`) is inherent in ownership and
cannot be revoked at all, from anyone, ever. So:

- This protects against the application's *normal code paths*: an ordinary bug, a
  stray endpoint, a future feature that "just" does `UPDATE security_audit_log SET
  ...` — that fails immediately, both on the privilege check and on the trigger.
- This does **not** protect against a caller able to run arbitrary SQL as the same
  connecting role (SQL injection with stacked statements, a compromised maintenance
  shell, an operator at a psql prompt). That caller can `GRANT UPDATE ... TO
  <themselves>` in one statement (ownership needs no permission to do that), or set
  the same escape-hatch GUC this migration reserves for retention and delete rows
  directly, or drop the trigger outright. None of that can be revoked from an owner
  by any migration.
- This is **not WORM**. A real immutability guarantee needs the application to
  connect as a role that does **not** own these tables — a separate, restricted role
  granted only `SELECT, INSERT`, with the tables owned by a distinct administrative
  role it cannot become. That is an architecture change (a second database
  credential), out of scope for this task, and named here so it is not mistaken for
  already done.

There is no database in this test environment, so nothing here proves a live UPDATE
fails — these are text assertions against the migration's SQL and Python, the same
level the rest of `tests/test_migrations.py` operates at. A live proof belongs in an
acceptance/integration run against a real PostgreSQL instance.
"""
import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations/versions"
PY_PATH = VERSIONS_DIR / "0005_audit_append_only.py"
SQL_PATH = VERSIONS_DIR / "0005_audit_append_only.sql"


def _sql_text() -> str:
    return SQL_PATH.read_text()


def _py_text() -> str:
    return PY_PATH.read_text()


def test_the_migration_file_exists_and_is_named_like_a_revision():
    assert PY_PATH.exists(), f"expected {PY_PATH}"
    assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.py", PY_PATH.name)


def test_it_has_the_sql_it_executes_beside_it():
    body = _py_text()
    # run_sql_file since the deploy that found the psycopg2 %-interpolation trap;
    # see tests/test_migration_execution_path.py for why exec_driver_sql is gone.
    assert "op.execute" in body or "run_sql_file" in body
    assert SQL_PATH.exists(), f"expected {SQL_PATH}"


def test_it_chains_from_the_highest_revision_actually_present():
    """0004_security_audit_log (B2) is the latest revision as of this task. If another
    agent has landed a later one by the time this runs, this test — not a human
    reading the directory — is what should catch a broken chain."""
    body = _py_text()
    revisions = sorted(
        p.stem for p in VERSIONS_DIR.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem)
    )
    # 0005 must declare down_revision as whatever 0004 revision id actually is.
    assert 'down_revision: Union[str, None] = "0004_security_audit_log"' in body \
        or "down_revision: Union[str, None] = '0004_security_audit_log'" in body
    assert "0004_security_audit_log" in revisions


def test_revision_id_matches_the_filename():
    body = _py_text()
    assert 'revision: str = "0005_audit_append_only"' in body


def test_update_is_revoked_from_the_connecting_role_on_both_audit_tables():
    """REVOKE ... FROM CURRENT_USER, not a hardcoded role name — the connecting role
    is configured per deployment (POSTGRES_USER, default "datapond"; the Aurora master
    user on the AWS reference), and CURRENT_USER is whichever role actually runs this
    migration, which env.py confirms is the same role the application connects as."""
    sql = _sql_text()
    assert re.search(r"REVOKE\s+UPDATE\s+ON\s+TABLE\b.*CURRENT_USER", sql, re.I | re.S)
    assert "security_audit_log" in sql
    assert "auth_audit_log" in sql


def test_a_trigger_named_explicitly_blocks_mutation_on_both_tables():
    """Named explicitly, per the task: a reviewer or a future migration must be able
    to find 'the append-only trigger' by name, not infer it from a generic-sounding
    function."""
    sql = _sql_text()
    assert "reject_audit_log_mutation" in sql
    assert re.search(r"CREATE\s+TRIGGER\s+security_audit_log_append_only", sql, re.I)
    assert re.search(r"CREATE\s+TRIGGER\s+auth_audit_log_append_only", sql, re.I)
    assert re.search(r"BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+public\.security_audit_log",
                      sql, re.I)
    assert re.search(r"BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+public\.auth_audit_log",
                      sql, re.I)


def test_the_trigger_function_raises_rather_than_silently_allowing():
    sql = _sql_text()
    match = re.search(
        r"CREATE (?:OR REPLACE )?FUNCTION public\.reject_audit_log_mutation\(\).*?\$\$;",
        sql, re.I | re.S,
    )
    assert match, "reject_audit_log_mutation() body not found"
    body = match.group(0)
    assert "RAISE EXCEPTION" in body.upper()


def test_the_deletion_path_b4_will_need_is_present_and_named():
    """B4 (retention) needs a sanctioned way to delete old rows despite the trigger.
    This is that path: a SECURITY DEFINER function per table that sets the escape-hatch
    GUC the trigger checks, deletes, and clears it again — the only place in this
    migration that ever turns the GUC on."""
    sql = _sql_text()
    for fn in ("prune_security_audit_log", "prune_auth_audit_log"):
        assert fn in sql, f"{fn} missing — B4 has no sanctioned deletion path"
        match = re.search(
            rf"CREATE (?:OR REPLACE )?FUNCTION public\.{fn}\(.*?\$\$;",
            sql, re.I | re.S,
        )
        assert match, f"{fn} body not found"
        body = match.group(0)
        assert "SECURITY DEFINER" in body.upper()
        assert "DELETE FROM" in body.upper()

    # Both functions gate their DELETE through the same GUC the trigger inspects, and
    # the GUC name must actually match between the trigger and the retention path —
    # a typo here would make the "sanctioned path" unable to delete anything.
    trigger_match = re.search(
        r"CREATE (?:OR REPLACE )?FUNCTION public\.reject_audit_log_mutation\(\).*?\$\$;",
        sql, re.I | re.S,
    )
    guc = re.search(r"current_setting\('([^']+)'", trigger_match.group(0))
    assert guc, "trigger does not read any escape-hatch setting"
    guc_name = guc.group(1)
    assert sql.count(f"set_config('{guc_name}'") >= 2, (
        f"expected both prune functions to set {guc_name!r} on then off"
    )


def test_downgrade_restores_update_and_removes_the_added_objects():
    body = _py_text()
    assert "def downgrade" in body
    downgrade_src = body.split("def downgrade", 1)[1]
    assert "DROP TRIGGER" in downgrade_src
    assert "DROP FUNCTION" in downgrade_src
    assert re.search(r"GRANT\s+UPDATE\s+ON\s+TABLE\b.*CURRENT_USER", downgrade_src, re.I | re.S)


def test_migration_rules_does_not_flag_this_migration():
    """REVOKE/GRANT are not in migration_rules.py's violation list (verified by
    reading the module before writing this migration), so no `Contract-of:` marker is
    required. This test pins that: if someone later adds REVOKE/GRANT/TRIGGER rules to
    migration_rules.py, this migration should be re-reviewed rather than silently pass."""
    from app.migration_rules import review_migration

    violations = review_migration("0005_audit_append_only", _sql_text(), docstring=_py_text())
    assert violations == [], violations
