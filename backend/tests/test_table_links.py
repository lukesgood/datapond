"""One writer per table when two catalogs see the same Iceberg table.

A catalog export leaves a table registered in two catalogs (owner + mirror). Iceberg
commits go through one catalog; a write or a DROP through the mirror would fork the
table (or, with Polaris purging on drop, delete the owner's files), and a read of the
mirror sees an old snapshot under the mirror catalog's grants. Inside DataPond: writes
to a mirror are refused, and reads of a mirror are routed to the owner."""
import pytest

from app import table_links as tl

LINKS = tl.Links.from_rows([{
    "mirror_catalog": "polaris_lake", "mirror_schema": "default", "mirror_table": "orders",
    "owner_catalog": "iceberg", "owner_schema": "default", "owner_table": "orders"}])


@pytest.mark.parametrize("sql,expected", [
    ("INSERT INTO polaris_lake.default.orders SELECT * FROM iceberg.default.x", [("polaris_lake", "default", "orders")]),
    ("DELETE FROM polaris_lake.default.orders WHERE id = 1", [("polaris_lake", "default", "orders")]),
    ("UPDATE polaris_lake.default.orders SET status = 'x'", [("polaris_lake", "default", "orders")]),
    ("DROP TABLE polaris_lake.default.orders", [("polaris_lake", "default", "orders")]),
    ("ALTER TABLE polaris_lake.default.orders ADD COLUMN c varchar", [("polaris_lake", "default", "orders")]),
    ("CREATE TABLE polaris_lake.default.orders AS SELECT 1 AS a", [("polaris_lake", "default", "orders")]),
    ("MERGE INTO polaris_lake.default.orders t USING iceberg.default.o s ON t.id = s.id "
     "WHEN MATCHED THEN DELETE", [("polaris_lake", "default", "orders")]),
    ("INSERT INTO default.orders VALUES (1)", [("iceberg", "default", "orders")]),
    ("SELECT * FROM polaris_lake.default.orders", []),
])
def test_write_targets_are_the_tables_a_statement_changes(sql, expected):
    assert tl.write_targets(sql, "trino", "iceberg") == expected


def test_a_write_to_a_mirror_is_refused_and_names_the_owner():
    with pytest.raises(tl.MirrorWriteRefused) as e:
        tl.check_writes("DROP TABLE polaris_lake.default.orders", "trino", LINKS, "iceberg")
    assert "iceberg.default.orders" in str(e.value) and "polaris_lake.default.orders" in str(e.value)
    tl.check_writes("INSERT INTO iceberg.default.orders VALUES (1)", "trino", LINKS, "iceberg")  # owner: fine


def test_reads_of_a_mirror_are_routed_to_the_owner():
    sql = tl.route_reads("SELECT o.id FROM polaris_lake.default.orders o JOIN iceberg.default.users u "
                         "ON o.uid = u.id", "trino", LINKS, "iceberg")
    assert "polaris_lake" not in sql.lower()
    assert sql.lower().count("iceberg.default.orders") == 1 and "iceberg.default.users" in sql.lower()


def test_a_statement_with_no_mirror_is_returned_unchanged():
    sql = "SELECT * FROM iceberg.default.orders   WHERE 1=1"
    assert tl.route_reads(sql, "trino", LINKS, "iceberg") is sql
    assert tl.route_reads(sql, "trino", tl.Links.from_rows([]), "iceberg") is sql


def test_names_compare_case_insensitively():
    with pytest.raises(tl.MirrorWriteRefused):
        tl.check_writes('DELETE FROM "POLARIS_LAKE"."Default".ORDERS', "trino", LINKS, "iceberg")


def test_an_unparseable_statement_is_not_waved_through():
    with pytest.raises(tl.MirrorWriteRefused):
        tl.check_writes("DROP TABLE polaris_lake.default.orders ((( nonsense", "trino", LINKS, "iceberg")
