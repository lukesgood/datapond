"""Rules a migration has to satisfy before anyone reviews it.

`helm --atomic` rolls back the *release*, not the database. If a migration ran and
the deploy then failed, the pods go back and the schema does not: old code, new
schema. Nothing in the tooling prevents that — expand/contract does, and it is a
discipline, not a feature.

What a check can do is stop the discipline from being invisible. It cannot know
whether dropping a column is safe. It can require the migration to say which earlier
release stopped using it, which turns "someone should have thought about this" into a
sentence a reviewer can agree or disagree with.
"""
import pytest

from app.migration_rules import Violation, review_migration


def test_creating_things_is_always_fine():
    assert review_migration("0002_x", "CREATE TABLE foo (id int);", docstring="") == []


def test_adding_a_nullable_column_is_the_expand_half():
    sql = "ALTER TABLE users ADD COLUMN nickname text;"
    assert review_migration("0002_x", sql, docstring="") == []


def test_dropping_a_column_must_name_the_release_that_freed_it():
    sql = "ALTER TABLE users DROP COLUMN nickname;"
    out = review_migration("0003_x", sql, docstring="")
    assert out and "Contract-of" in out[0].message


def test_a_named_contract_is_accepted():
    sql = "ALTER TABLE users DROP COLUMN nickname;"
    doc = "Contract-of: 0002_stop_reading_nickname"
    assert review_migration("0003_x", sql, docstring=doc) == []


def test_dropping_a_table_needs_the_same_statement():
    out = review_migration("0003_x", "DROP TABLE old_thing;", docstring="")
    assert out and "DROP TABLE" in out[0].statement.upper()


def test_renaming_is_a_drop_and_an_add_wearing_one_name():
    """Old code looks for the old name and finds nothing. There is no version of a
    rename that is safe in one release."""
    out = review_migration("0003_x", "ALTER TABLE users RENAME TO people;", docstring="")
    assert out


def test_making_an_existing_column_required_breaks_the_running_code():
    """The previous release inserts rows without it. NOT NULL lands, those inserts
    start failing, and the deploy looks fine."""
    sql = "ALTER TABLE users ALTER COLUMN nickname SET NOT NULL;"
    out = review_migration("0003_x", sql, docstring="")
    assert out and "NOT NULL" in out[0].message


def test_a_default_does_not_excuse_it():
    """A default fills new rows. It does not fix the ones already there, and the
    check is about the code that is still running, not the rows."""
    sql = "ALTER TABLE users ALTER COLUMN nickname SET NOT NULL;"
    doc = "Contract-of: 0002_backfill_nickname"
    assert review_migration("0003_x", sql, docstring=doc) == []


def test_the_baseline_is_exempt():
    """It creates a schema from nothing; there is no previous release to be
    compatible with."""
    assert review_migration("0001_baseline", "DROP TABLE anything;", docstring="") == []


def test_comments_do_not_trigger_it():
    sql = "-- we used to DROP TABLE here\nCREATE TABLE foo (id int);"
    assert review_migration("0002_x", sql, docstring="") == []


def test_every_violation_quotes_the_statement_it_found():
    """A reviewer should not have to search the file for what the check meant."""
    out = review_migration("0003_x", "DROP TABLE old_thing;", docstring="")
    assert out[0].statement.strip()


# ── the rule applied to what is actually in the repository ───────────────────

def test_the_migrations_in_this_repository_pass():
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations/versions"
    problems = []
    for py in sorted(versions.glob("*.py")):
        sql_file = py.with_suffix(".sql")
        sql = sql_file.read_text() if sql_file.exists() else py.read_text()
        doc = py.read_text()
        problems += [f"{py.name}: {v.message}"
                     for v in review_migration(py.stem, sql, docstring=doc)]
    assert not problems, problems
