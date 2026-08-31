"""Retrofitting migrations onto a schema that already exists.

44 tables, spread across four SQL files and 34 CREATE/ALTER/INDEX statements that run
at startup and swallow their own errors. Converting all of that at once is how a
migration story breaks a production database; the assessment says as much, and it
stays true.

So the first step is the one that changes nothing: put Alembic in place, record the
current schema as the baseline, and let the existing bootstraps carry on. New schema
changes then have somewhere to go, and each bootstrap can be converted on its own
afterwards instead of in one commit nobody can review.

The part worth testing is the decision that makes it safe: on a database that already
has these tables, the baseline must be *stamped*, never *run*.
"""
import pytest

from app.migrations import baseline_action


def test_a_populated_database_is_stamped_not_migrated():
    """Running the baseline against a live database would try to create tables that
    exist. Alembic's own answer to a legacy schema is to record where it already is."""
    assert baseline_action(has_tables=True, has_version_table=False) == "stamp"


def test_an_empty_database_is_built_by_the_baseline():
    """This flipped when the baseline stopped being a no-op. It used to be stamped
    because the bootstraps created everything a moment later; now the schema has one
    definition that runs first. The bootstraps still run and their
    CREATE TABLE IF NOT EXISTS makes them harmless."""
    assert baseline_action(has_tables=False, has_version_table=False) == "upgrade"


def test_the_baseline_sql_is_present_and_is_the_real_schema():
    """A baseline whose file went missing would exec an empty string and report
    success, leaving a database with no tables and a version stamp saying otherwise."""
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1]
           / "migrations/versions/0001_baseline.sql").read_text()
    assert sql.count("CREATE TABLE") >= 40, sql.count("CREATE TABLE")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "ai_chunks" in sql and "users" in sql


def test_a_database_already_under_alembic_is_left_alone():
    assert baseline_action(has_tables=True, has_version_table=True) == "upgrade"


def test_the_action_is_never_a_silent_no_op():
    """Every combination resolves to something that leaves the version table correct.
    A third outcome would mean a database whose migration state nobody recorded."""
    for tables in (True, False):
        for version in (True, False):
            assert baseline_action(tables, version) in ("stamp", "upgrade")


# ── the split: the Job runs, the application checks ───────────────────────────
#
# Running migrations from the startup hook was a placement, not a design. It runs in
# every replica — two backends starting during a rolling upgrade both call
# `alembic upgrade head`, and Alembic does not lock. Harmless only while the baseline
# is a no-op; live the moment a real migration exists.
#
# It also tied readiness to how long a migration takes. A CREATE INDEX on a large
# table would hold pods NotReady until `helm --wait` gave up and rolled back a release
# for a migration that was working.
#
# So the Job runs them — one pod, before the new image starts — and the application
# only verifies where the database is. It never issues DDL.

from app.migrations import startup_check


def test_a_database_at_head_is_fine():
    assert startup_check(current="0002_x", head="0002_x") == "ok"


def test_a_database_behind_head_refuses_traffic():
    """The failure this catches: the image was upgraded and the migration Job was
    not. Old schema, new code, and nothing else would have noticed."""
    assert startup_check(current="0001_baseline", head="0002_x") == "behind"


def test_a_database_alembic_has_never_seen_is_stamped():
    """A local run, or a first install where the Job has not been through yet. This
    is what happens today, so keeping it means dev is unaffected."""
    assert startup_check(current=None, head="0001_baseline") == "stamp"


def test_a_database_ahead_of_this_image_also_refuses():
    """A rollback that left the schema forward. The app must not assume it can serve
    a schema it does not know — that is the expand/contract mistake, and it should be
    loud rather than a column error at a random endpoint."""
    assert startup_check(current="0009_future", head="0002_x") == "ahead"


def test_the_check_never_issues_ddl():
    """The whole point of the split. If this function could migrate, every replica
    could migrate, which is where this started.

    Reads the body with the docstring removed — the first version of this test failed
    on the word "upgrade" inside the explanation of why it does not upgrade."""
    import ast
    import inspect

    from app import migrations

    tree = ast.parse(inspect.getsource(migrations.startup_check).strip())
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    body = ast.unparse(fn)
    for forbidden in ("upgrade", "stamp(", "CREATE", "ALTER", "command."):
        assert forbidden not in body, f"{forbidden} appears in the body:\n{body}"


def test_only_real_revisions_are_in_the_versions_directory():
    """Alembic loads every .py under versions/ as a revision, so anything else there
    is parsed as Python and fails the whole migration.

    Found the hard way: a macOS tarball carried AppleDouble companions (`._name.py`)
    into a container, and Alembic tried to import 163 bytes of binary — "source code
    string cannot contain null bytes", with nothing in the message to suggest where
    it came from.
    """
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations/versions"
    stray = [f.name for f in versions.glob("*.py")
             if not re.fullmatch(r"\d{4}_[a-z0-9_]+\.py", f.name)]
    assert not stray, f"not revision files: {stray}"


def test_every_revision_has_the_sql_it_executes():
    """A revision whose .sql went missing would exec an empty string and report
    success, leaving a stamped version number on a database with no tables."""
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations/versions"
    for py in versions.glob("*.py"):
        if "op.execute" in py.read_text() or "exec_driver_sql" in py.read_text():
            assert py.with_suffix(".sql").exists(), f"{py.name} has no .sql beside it"


# ── waiting, which is not the same as retrying ────────────────────────────────
# The migration Job stopped being a pre-install hook: with an in-cluster database the
# database does not exist yet when pre-install hooks run, and the Secret the Job reads
# its credentials from is a main-phase resource too. Both were found by the ephemeral
# install job, one after the other.
#
# As an ordinary manifest resource the Job starts alongside Postgres rather than
# before it, so it has to wait for the database to accept connections. That is not a
# retry of the migration - backoffLimit stays 0, one attempt, then a human reads the
# log. Waiting for a socket and retrying DDL are different things and only one of them
# is dangerous.

def test_waiting_continues_while_the_database_is_unreachable():
    from app.migrations import should_keep_waiting

    assert should_keep_waiting(reachable=False, elapsed=5, timeout=300)


def test_waiting_stops_the_moment_it_is_reachable():
    from app.migrations import should_keep_waiting

    assert not should_keep_waiting(reachable=True, elapsed=5, timeout=300)


def test_waiting_gives_up_rather_than_hanging_a_release_forever():
    """A Job that never exits is worse than one that fails: nothing reports it, and
    `helm --wait` sits there until its own timeout with no reason recorded."""
    from app.migrations import should_keep_waiting

    assert not should_keep_waiting(reachable=False, elapsed=301, timeout=300)


def test_the_boundary_belongs_to_waiting_not_to_giving_up():
    from app.migrations import should_keep_waiting

    assert should_keep_waiting(reachable=False, elapsed=300, timeout=300)


# ── the backend waits for the schema, it does not create it ───────────────────

def test_the_schema_is_ready_when_no_core_table_is_missing():
    from app.migrations import CORE_TABLES, schema_ready

    assert schema_ready(set(CORE_TABLES))
    assert schema_ready(set(CORE_TABLES) | {"anything_else"})


def test_the_schema_is_not_ready_while_a_core_table_is_absent():
    from app.migrations import CORE_TABLES, schema_ready

    assert not schema_ready(set(CORE_TABLES) - {"users"})
    assert not schema_ready(set())


def test_the_wait_entry_point_never_applies_a_migration():
    """The backend's init container waits; it must not migrate. Every replica runs it,
    Alembic does not lock, and that is the whole reason the Job exists."""
    import inspect

    from app import migrations

    body = inspect.getsource(migrations.wait_for_schema)
    for forbidden in ("apply(", "command.upgrade", "stamp"):
        assert forbidden not in body, f"{forbidden} appears in wait_for_schema"


def test_nothing_is_defined_after_the_script_entry_point():
    """`if __name__ == "__main__"` has to be the last thing in the module.

    It was in the middle. Run as `python -m app.migrations`, execution reaches that
    guard and calls main() before the names below it exist — so present_tables and
    missing_tables were simply undefined, and only for the script path. Importing the
    module normally ran the whole file and looked fine, which is why nothing caught it
    until an init container waited ten minutes for a schema that was already there.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/migrations.py").read_text()
    body = ast.parse(source).body
    guards = [i for i, node in enumerate(body)
              if isinstance(node, ast.If) and "__main__" in ast.dump(node.test)]
    assert guards, "no __main__ guard"
    assert guards[-1] == len(body) - 1, (
        "definitions follow the __main__ guard; they do not exist when run as a script")


def test_waiting_says_why_it_is_still_waiting():
    """The loop swallowed a NameError into `ready = False` and waited in silence.

    That is the same failure this codebase has now hit three times: an exception
    turned into an empty result, and an empty result read as "not yet". A wait that
    cannot say what it is waiting for is indistinguishable from a hang.
    """
    import inspect

    from app import migrations

    body = inspect.getsource(migrations.wait_for_schema)
    assert "except Exception" not in body or "log" in body, "the reason is swallowed"
    assert "logger" in body or "log." in body
