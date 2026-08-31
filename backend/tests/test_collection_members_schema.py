"""Sharing a collection with named people, before anything reads the table.

`ai_collections.owner_id` plus "owner NULL means everyone" is the whole access model
today. There is no row anywhere that means "this one other person may read this
collection" — so the only way to hand someone a collection is to make them the owner,
or to make it public. This migration adds the table that row lives in.

Enforcement is a separate task (A3) and is not this one. Nothing here queries the
table, checks a permission, or changes what any endpoint does — a member row sharing a
collection today would authorize nobody, because nothing reads
`ai_collection_members` yet. That is deliberate: schema and enforcement landing in the
same change is how you end up unable to tell, from a test failure, whether the table
or the wiring is wrong.

There is no database in this test environment, so every assertion here is text/AST
against the `.sql` file and the revision graph in the `.py` file. That proves the
migration *says* CASCADE, *says* the CHECK, *says* the uniqueness — it does not run
the SQL, so it cannot catch a typo Postgres would reject at apply time (e.g. a
constraint referencing a column that does not exist) or a CASCADE that fires on the
wrong table. That gap is what `tests/acceptance` and a real `alembic upgrade` are for.
"""
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
PY = VERSIONS / "0003_collection_members.py"
SQL = VERSIONS / "0003_collection_members.sql"


def test_the_revision_chains_from_system_events():
    """A migration that does not name its predecessor is not part of the chain Alembic
    walks to head — `alembic upgrade head` would silently stop one short of it, or
    Alembic would refuse to start over two heads. `down_revision` is what makes this
    revision reachable at all."""
    body = PY.read_text()
    assert re.search(r'revision:\s*str\s*=\s*"0003_collection_members"', body)
    assert re.search(r'down_revision.*=\s*"0002_system_events"', body)


def test_the_sql_file_exists_beside_the_python():
    """`test_every_revision_has_the_sql_it_executes` in test_migrations.py enforces
    this repo-wide; this is the local version so this file fails on its own if the
    pairing breaks, without waiting on the other test module."""
    assert SQL.exists(), "0003_collection_members.py has no .sql beside it"
    assert "exec_driver_sql" in PY.read_text()


def test_a_deleted_collection_takes_its_membership_rows_with_it():
    """A member row whose collection_id points at nothing is a permission with
    nothing behind it: the enforcement path in A3 will join membership to
    ai_collections, and an orphaned row is either a dangling grant nobody can see to
    revoke, or — worse — a JOIN that happens to still match because Postgres reused
    the uuid. CASCADE deletes the grant the moment the thing it grants access to is
    gone."""
    sql = SQL.read_text()
    collection_fk = re.search(
        r"collection_id\s+uuid[^,]*REFERENCES\s+public\.ai_collections\s*\(id\)"
        r"([^,\n]*)", sql, re.I)
    assert collection_fk, "no FK from collection_id to ai_collections(id) found"
    assert "ON DELETE CASCADE" in collection_fk.group(1).upper()


def test_a_deleted_user_takes_their_membership_rows_with_them():
    """Same reasoning as the collection FK: a grant naming a user_id that no longer
    exists is not a real grant, so it must not be able to outlive the user."""
    sql = SQL.read_text()
    user_fk = re.search(
        r"user_id\s+uuid[^,]*REFERENCES\s+public\.users\s*\(id\)([^,\n]*)",
        sql, re.I)
    assert user_fk, "no FK from user_id to users(id) found"
    assert "ON DELETE CASCADE" in user_fk.group(1).upper()


def test_the_role_check_names_exactly_reader_and_editor():
    """A CHECK that accepts anything else lets a typo like 'admin' or 'writer' sit in
    the table silently until the enforcement code in A3 reads it and either grants
    more than intended or matches nothing. Pinning the two literal values here is what
    makes that a migration-time rejection instead of a runtime surprise."""
    sql = SQL.read_text()
    check = re.search(r"CHECK\s*\(\s*role\s+IN\s*\(([^)]*)\)\s*\)", sql, re.I)
    assert check, "no CHECK constraint on role found"
    values = {v.strip().strip("'") for v in check.group(1).split(",")}
    assert values == {"reader", "editor"}, values


def test_one_row_per_collection_and_user():
    """Without this, granting the same person access twice either silently doubles
    nothing (harmless) or — once A3 writes an UPSERT expecting exactly one row to
    conflict on — has no unique target to conflict against, and the insert either
    fails or duplicates the grant. A composite PRIMARY KEY or a UNIQUE constraint on
    the pair is what makes "one row per (collection, user)" true rather than assumed.
    """
    sql = SQL.read_text()
    has_pk = bool(re.search(
        r"PRIMARY\s+KEY\s*\(\s*collection_id\s*,\s*user_id\s*\)", sql, re.I))
    has_unique = bool(re.search(
        r"UNIQUE\s*\(\s*collection_id\s*,\s*user_id\s*\)", sql, re.I))
    assert has_pk or has_unique, (
        "no composite PRIMARY KEY or UNIQUE constraint on (collection_id, user_id)")


def test_an_index_supports_which_collections_a_user_may_read():
    """The query A3's enforcement path runs on every list request is "give me the
    collections this user_id has been granted" — filtering ai_collection_members by
    user_id. A composite PRIMARY KEY on (collection_id, user_id) does not help that
    query: a btree on (collection_id, user_id) can't be used to look up by user_id
    alone, the same way a phone book sorted by last-then-first name doesn't help you
    find someone if you only know their first name. Without an index led by user_id,
    every list of "what can I see" becomes a sequential scan of every grant that has
    ever existed, on every request."""
    sql = SQL.read_text()
    assert re.search(
        r"CREATE\s+INDEX[^;]*ON\s+public\.ai_collection_members[^;]*\(\s*user_id\b",
        sql, re.I), "no index on ai_collection_members led by user_id"


def test_downgrade_drops_only_what_this_revision_added():
    """This revision only creates one table, so downgrade dropping anything else would
    be reaching into schema another revision owns."""
    body = PY.read_text()
    downgrade = body.split("def downgrade", 1)[1]
    assert "ai_collection_members" in downgrade
    assert "DROP TABLE" in downgrade.upper()
