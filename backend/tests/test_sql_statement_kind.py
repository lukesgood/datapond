"""Which statements read, and which change something.

`query:run` meant "execute SQL", and every role that could query could also
`DROP TABLE` — `viewer` included. Nothing in the execute path looked at what the
statement was; the only hint it was ever considered is a comment in queries.py saying
"Don't add LIMIT to DDL or SHOW commands", written on the assumption that DDL flows
through.

This is the classifier the gate is built on. It fails closed: anything it cannot parse
or does not recognise counts as a write, because the cost of being wrong in the other
direction is a dropped table.
"""
import pytest

from app.sql_kind import statement_kind


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from orders where id = 3",
    "WITH t AS (SELECT 1 AS a) SELECT a FROM t",
    "SHOW TABLES",
    "DESCRIBE orders",
    "EXPLAIN SELECT * FROM orders",
    "SELECT count(*) FROM orders -- a comment",
    "  \n SELECT 1 \n ",
    "SELECT * FROM orders ORDER BY id LIMIT 10;",
])
def test_reads_are_reads(sql):
    assert statement_kind(sql) == "read", sql


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "drop table if exists orders",
    "CREATE TABLE t (a int)",
    "CREATE TABLE AS SELECT * FROM orders",
    "ALTER TABLE orders ADD COLUMN x int",
    "TRUNCATE TABLE orders",
    "INSERT INTO orders VALUES (1)",
    "UPDATE orders SET status = 'x'",
    "DELETE FROM orders",
    "MERGE INTO orders USING s ON orders.id = s.id WHEN MATCHED THEN UPDATE SET status = 'x'",
    "GRANT SELECT ON orders TO someone",
    "CREATE VIEW v AS SELECT 1",
    "DROP SCHEMA sales",
])
def test_writes_are_writes(sql):
    assert statement_kind(sql) == "write", sql


def test_a_read_hidden_behind_a_write_is_a_write():
    """A batch is as privileged as its most privileged statement."""
    assert statement_kind("SELECT 1; DROP TABLE orders") == "write"
    assert statement_kind("DROP TABLE orders; SELECT 1") == "write"


def test_unparseable_sql_counts_as_a_write():
    """Fail closed. Being wrong the other way drops a table.

    Engines accept syntax sqlglot does not, and a parser that returns "probably a
    read" for what it could not read is the one bug this must not have.
    """
    assert statement_kind("NOT ACTUALLY SQL AT ALL {{{") == "write"
    assert statement_kind("") == "write"
    assert statement_kind(None) == "write"


def test_a_statement_shaped_like_a_read_but_named_like_a_write_is_a_write():
    """`CREATE TABLE ... AS SELECT` reads and writes. It writes."""
    assert statement_kind("CREATE TABLE t AS SELECT * FROM orders") == "write"


def test_comments_cannot_disguise_a_write():
    assert statement_kind("-- SELECT 1\nDROP TABLE orders") == "write"
    assert statement_kind("/* SELECT 1 */ DROP TABLE orders") == "write"


def test_a_trailing_semicolon_and_whitespace_do_not_change_the_verdict():
    assert statement_kind("SELECT 1;") == "read"
    assert statement_kind("DROP TABLE orders;  ") == "write"


# ── the generic Command node ──────────────────────────────────────────────────
# sqlglot parses SHOW and EXPLAIN into `Command`, its fallback for syntax the dialect
# does not model — and unsupported DDL lands there too. Treating Command as a read
# would wave through exactly what this exists to stop, so the leading keyword decides.

def test_an_unsupported_statement_that_falls_back_to_command_is_a_write():
    assert statement_kind("VACUUM orders") == "write"
    assert statement_kind("CALL system.rollback_to_snapshot('t', 1)") == "write"
    assert statement_kind("OPTIMIZE orders") == "write"


def test_explain_analyze_is_a_write_because_it_runs_the_statement():
    """EXPLAIN describes; EXPLAIN ANALYZE executes. A plan for a DELETE is a read; an
    analyzed plan for a DELETE has deleted the rows."""
    assert statement_kind("EXPLAIN ANALYZE SELECT * FROM orders") == "write"
    assert statement_kind("explain  analyze delete from orders") == "write"


def test_a_plain_explain_of_a_write_still_only_describes_it():
    assert statement_kind("EXPLAIN DELETE FROM orders") == "read"
