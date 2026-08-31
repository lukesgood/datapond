"""Connectors and transforms get an owner, and can be shared — before anything reads it.

Measured, not assumed: `ai_collections`, `dashboards`, `query_history` and
`rls_policies` all carry an owner. `connector_connections` and `saved_transforms`
carry none — so the analysis side of this product is per-user and the data-source
side is shared by everyone. Anyone holding `connector:write` can edit or delete a
connector someone else created, because there is no owner column to tell them apart.
This migration adds one, plus the sharing tables A2 (0003_collection_members) already
proved out for collections.

Enforcement is D2, a separate task, and is not this one. Nothing here queries
`owner_id` or the member tables, checks a permission, or changes what any endpoint
does — the columns and tables exist and authorize nobody until D2 reads them.

The nullable rule is the load-bearing part. Every connector and transform that exists
today has no owner. If `owner_id` were NOT NULL, this migration would need to either
fail outright (no value to backfill with) or invent an owner for rows that never had
one — and if it defaulted `owner_id` to some placeholder, the enforcement code in D2
would then treat every existing source as privately owned by that placeholder,
hiding it from everyone else. Nullable, with NULL meaning "visible to everyone" (the
same meaning it has for `ai_collections`), is what keeps every existing deployment's
sources visible after this migration runs. Making `owner_id` NOT NULL, or defaulting
it, is not a stricter version of this migration — it is an outage on every existing
deployment the moment D2 starts reading the column.

There is no database in this test environment, so every assertion here is text/AST
against the `.sql` file and the revision graph in the `.py` file. That proves the
migration *says* nullable, *says* SET NULL, *says* the CASCADE and CHECK — it does
not run the SQL, so it cannot catch a typo Postgres would reject at apply time, or
prove a real backfilled row actually reads back with `owner_id IS NULL`. That gap is
what `tests/acceptance` and a real `alembic upgrade` are for.
"""
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"


def _chain() -> dict:
    """{revision: down_revision} read from every migration in the versions directory."""
    chain = {}
    for py in VERSIONS.glob("*.py"):
        body = py.read_text()
        rev = re.search(r'revision:\s*str\s*=\s*"([^"]+)"', body)
        down = re.search(r'down_revision.*=\s*"([^"]+)"', body)
        if rev:
            chain[rev.group(1)] = down.group(1) if down else None
    return chain


PY = VERSIONS / "0006_resource_ownership.py"
SQL = VERSIONS / "0006_resource_ownership.sql"


def test_the_revision_is_part_of_the_chain_alembic_walks():
    """A migration that names a predecessor which does not exist is not on the tree
    Alembic walks to head — it never runs, and nothing says so.

    Originally written as "chains from whatever is currently head", which was true on
    the day this landed and stopped being true the moment a later migration chained
    onto it. The durable property is membership of the chain, not being its tip; the
    single-head rule belongs to every migration equally and lives in
    tests/test_migrations.py.
    """
    chain = _chain()
    body = PY.read_text()
    assert re.search(r'revision:\s*str\s*=\s*"0006_resource_ownership"', body)
    down = chain.get("0006_resource_ownership")
    assert down in chain, f"down_revision '{down}' names no migration in the directory"


def test_the_sql_file_exists_beside_the_python():
    assert SQL.exists(), "0006_resource_ownership.py has no .sql beside it"
    assert "exec_driver_sql" in PY.read_text()


def test_owner_id_is_nullable_on_connector_connections():
    """NOT NULL here would mean either the migration fails outright (nothing to
    backfill with) or every existing connector gets force-assigned an owner — and once
    D2 enforces ownership, a forced owner is a connector that just went invisible to
    everyone else who used to see it. That is the outage this column must not cause."""
    sql = SQL.read_text()
    m = re.search(
        r"ADD\s+COLUMN[^;]*owner_id\s+uuid([^,\n]*)", sql, re.I)
    assert m, "no owner_id column added to connector_connections"
    assert "NOT NULL" not in m.group(1).upper(), (
        "owner_id on connector_connections is NOT NULL — this would either fail "
        "against existing rows or force an owner onto every connector that exists "
        "today, hiding them from everyone else the moment D2 enforces ownership"
    )


def test_owner_id_is_nullable_on_saved_transforms():
    sql = SQL.read_text()
    statements = sql.split("ALTER TABLE public.saved_transforms", 1)
    assert len(statements) == 2, "no ALTER TABLE on saved_transforms found"
    m = re.search(r"ADD\s+COLUMN[^;]*owner_id\s+uuid([^,\n]*)", statements[1], re.I)
    assert m, "no owner_id column added to saved_transforms"
    assert "NOT NULL" not in m.group(1).upper(), (
        "owner_id on saved_transforms is NOT NULL — same outage as "
        "connector_connections: every existing transform would need a forced owner"
    )


def test_owner_id_references_users_on_delete_set_null():
    """CASCADE here would mean deleting a person deletes every source they created —
    the data source a team depends on must survive the person who happened to
    register it leaving. SET NULL drops the ownership, not the connector, and NULL
    already means "visible to everyone" for this column."""
    sql = SQL.read_text()
    for table in ("connector_connections", "saved_transforms"):
        block = sql.split(f"ALTER TABLE public.{table}", 1)
        assert len(block) == 2, f"no ALTER TABLE for {table}"
        m = re.search(
            r"owner_id\s+uuid\s+REFERENCES\s+public\.users\s*\(id\)([^,\n;]*)",
            block[1], re.I)
        assert m, f"owner_id on {table} has no REFERENCES public.users(id)"
        assert "ON DELETE SET NULL" in m.group(1).upper(), (
            f"owner_id on {table} is not ON DELETE SET NULL — a deleted user must "
            f"not take the data source their team depends on down with them"
        )
        assert "ON DELETE CASCADE" not in m.group(1).upper()


def test_member_tables_cascade_on_the_resource():
    """Mirrors A2's reasoning for ai_collection_members: once the connector or
    transform is gone there is nothing left for a grant on it to mean, so leaving the
    grant behind is a permission pointing at nothing."""
    sql = SQL.read_text()
    resource_fk = {
        "connector_members": ("connection_id", "connector_connections"),
        "transform_members": ("transform_id", "saved_transforms"),
    }
    for member_table, (col, resource_table) in resource_fk.items():
        table_block = re.search(
            rf"CREATE TABLE[^;]*public\.{member_table}\s*\((.*?)\n\);",
            sql, re.I | re.S)
        assert table_block, f"no CREATE TABLE for {member_table}"
        fk = re.search(
            rf"{col}\s+uuid[^,]*REFERENCES\s+public\.{resource_table}\s*\(id\)"
            rf"([^,\n]*)", table_block.group(1), re.I)
        assert fk, f"no FK from {col} to {resource_table}(id) in {member_table}"
        assert "ON DELETE CASCADE" in fk.group(1).upper()


def test_member_tables_cascade_on_the_user():
    sql = SQL.read_text()
    for member_table in ("connector_members", "transform_members"):
        table_block = re.search(
            rf"CREATE TABLE[^;]*public\.{member_table}\s*\((.*?)\n\);",
            sql, re.I | re.S)
        assert table_block, f"no CREATE TABLE for {member_table}"
        fk = re.search(
            r"user_id\s+uuid[^,]*REFERENCES\s+public\.users\s*\(id\)([^,\n]*)",
            table_block.group(1), re.I)
        assert fk, f"no FK from user_id to users(id) in {member_table}"
        assert "ON DELETE CASCADE" in fk.group(1).upper()


def test_member_tables_role_check_names_exactly_reader_and_editor():
    sql = SQL.read_text()
    for member_table in ("connector_members", "transform_members"):
        table_block = re.search(
            rf"CREATE TABLE[^;]*public\.{member_table}\s*\((.*?)\n\);",
            sql, re.I | re.S)
        assert table_block, f"no CREATE TABLE for {member_table}"
        check = re.search(
            r"CHECK\s*\(\s*role\s+IN\s*\(([^)]*)\)\s*\)", table_block.group(1), re.I)
        assert check, f"no CHECK constraint on role in {member_table}"
        values = {v.strip().strip("'") for v in check.group(1).split(",")}
        assert values == {"reader", "editor"}, values


def test_member_tables_have_one_row_per_pair():
    sql = SQL.read_text()
    pairs = {
        "connector_members": "connection_id",
        "transform_members": "transform_id",
    }
    for member_table, resource_col in pairs.items():
        table_block = re.search(
            rf"CREATE TABLE[^;]*public\.{member_table}\s*\((.*?)\n\);",
            sql, re.I | re.S)
        assert table_block, f"no CREATE TABLE for {member_table}"
        has_pk = re.search(
            rf"PRIMARY\s+KEY\s*\(\s*{resource_col}\s*,\s*user_id\s*\)",
            table_block.group(1), re.I)
        has_unique = re.search(
            rf"UNIQUE\s*\(\s*{resource_col}\s*,\s*user_id\s*\)",
            table_block.group(1), re.I)
        assert has_pk or has_unique, (
            f"no composite PRIMARY KEY or UNIQUE on ({resource_col}, user_id) in "
            f"{member_table}"
        )


def test_member_tables_have_an_index_led_by_user_id():
    """The query D2 runs on every list/read/sync/schedule/edit/delete is "which
    sources may this person see" — filtering by user_id. Without an index led by
    user_id that lookup is a sequential scan of every grant ever made, on every
    request that touches a connector or transform."""
    sql = SQL.read_text()
    for member_table in ("connector_members", "transform_members"):
        assert re.search(
            rf"CREATE\s+INDEX[^;]*ON\s+public\.{member_table}[^;]*\(\s*user_id\b",
            sql, re.I), f"no index on {member_table} led by user_id"


def test_migration_rules_finds_no_violations():
    """ADD COLUMN and CREATE TABLE are additive — this migration touches nothing an
    earlier release depends on, so it needs no `Contract-of` line to pass review."""
    from app.migration_rules import review_migration

    violations = review_migration(
        "0006_resource_ownership", SQL.read_text(), docstring=PY.read_text())
    assert not violations, [v.message for v in violations]


def test_downgrade_drops_only_what_this_revision_added():
    body = PY.read_text()
    downgrade = body.split("def downgrade", 1)[1]
    upper = downgrade.upper()
    assert "CONNECTOR_MEMBERS" in upper
    assert "TRANSFORM_MEMBERS" in upper
    assert "OWNER_ID" in upper
