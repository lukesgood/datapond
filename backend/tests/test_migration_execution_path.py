"""How a migration's SQL reaches the database, and what happens when it does not.

Both halves of this file come from one live failure. `0005_audit_append_only` ran
fine everywhere it was tested and failed against Aurora the moment it was deployed,
and the Job that failed printed no reason at all.

**The failure.** The version files executed their `.sql` through
`Connection.exec_driver_sql`, which hands psycopg2 a parameter mapping — and psycopg2,
given any parameters, treats `%` in the statement as a placeholder. 0005's trigger
raises `'audit_append_only: % on %.% is not permitted…'`, so the driver tried to
interpolate it and the migration died with
`TypeError: immutabledict is not a sequence`. 0003 and 0004 contain no `%` at all,
which is exactly why they applied and 0005 did not. Nothing local caught it: the tests
read the SQL as text, and the one path that does execute it (asyncpg, in the
application) uses `$1` placeholders and leaves `%` alone.

**The silence.** `env.py` calls `fileConfig()`, whose `disable_existing_loggers`
defaults to True — so it switched off the `[migrate]` logger the entry point had
already created, and `log.error("failed: %s", e)` went nowhere. A Job that exits 1
after two seconds with a clean log is a mystery; the traceback is what turns it back
into a bug.
"""
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations/versions"


def _version_files():
    return sorted(VERSIONS.glob("*.py"))


@pytest.mark.parametrize("path", _version_files(), ids=lambda p: p.stem)
def test_no_migration_executes_sql_through_the_interpolating_path(path):
    """`exec_driver_sql` is the call that broke: it passes parameters, so psycopg2
    reformats the statement. Every migration goes through the shared helper instead,
    which executes on the raw DBAPI cursor with no parameters at all."""
    body = path.read_text()
    assert "exec_driver_sql" not in body, (
        f"{path.name} executes SQL through exec_driver_sql — a '%' anywhere in that "
        "statement (a RAISE format, a LIKE pattern) makes psycopg2 try to interpolate it")


@pytest.mark.parametrize("path", _version_files(), ids=lambda p: p.stem)
def test_every_migration_runs_its_sql_through_the_shared_helper(path):
    body = path.read_text()
    if "def upgrade" not in body:
        return
    assert re.search(r"run_sql(_file)?\(", body), (
        f"{path.name} does not use app.migrations.run_sql_file / run_sql")


def test_the_helper_hands_the_driver_a_statement_and_nothing_else():
    """One argument to `cursor.execute`. Two — even an empty mapping — is what makes
    psycopg2 scan the statement for placeholders."""
    from app.migrations import run_sql

    calls = []

    class _Cursor:
        def execute(self, *args, **kwargs):
            calls.append((args, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Raw:
        def cursor(self):
            return _Cursor()

    class _Bind:
        connection = type("C", (), {"driver_connection": _Raw()})()

    statement = "SELECT 'audit: % on %.% is not permitted'"
    run_sql(_Bind(), statement)
    assert calls == [((statement,), {})], (
        "the helper passed parameters, so psycopg2 will reformat the statement")


def test_the_sql_that_broke_the_deploy_still_carries_its_percent_signs():
    """Not a coincidence to be tidied away: the RAISE message names the operation and
    the table, and that is what makes the refusal readable in a Postgres log. The fix
    is in how it is executed, not in what it says."""
    sql = (VERSIONS / "0005_audit_append_only.sql").read_text()
    assert "%" in sql


def test_a_failed_migration_prints_why():
    """`fileConfig()` disables existing loggers by default, which silenced the entry
    point's own error line. Both halves are pinned: the config call, and that the
    handler reports the traceback rather than one formatted line."""
    env = (BACKEND / "migrations/env.py").read_text()
    assert "disable_existing_loggers=False" in env, (
        "fileConfig() will switch off the logger the entry point already made")

    main_source = (BACKEND / "app/migrations.py").read_text()
    failure = main_source[main_source.index("def main("):]
    assert "exc_info=True" in failure or "traceback" in failure, (
        "a migration failure has to print the traceback, not just its str()")
