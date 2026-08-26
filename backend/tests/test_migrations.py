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


def test_an_empty_database_lets_the_bootstraps_create_it():
    """Fresh installs are still built by the startup bootstraps, unchanged. The
    baseline records that state afterwards rather than duplicating it — two things
    creating the same table is the failure this is meant to end, not start."""
    assert baseline_action(has_tables=False, has_version_table=False) == "stamp"


def test_a_database_already_under_alembic_is_left_alone():
    assert baseline_action(has_tables=True, has_version_table=True) == "upgrade"


def test_the_action_is_never_a_silent_no_op():
    """Every combination resolves to something that leaves the version table correct.
    A fourth outcome would mean a database whose migration state nobody recorded."""
    for tables in (True, False):
        for version in (True, False):
            assert baseline_action(tables, version) in ("stamp", "upgrade")
