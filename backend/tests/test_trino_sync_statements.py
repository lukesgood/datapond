"""The statements a Trino-backed sync runs, built from the source's columns (Phase 2
plan, Task 6; Review Focus 3: types Iceberg cannot hold)."""
import pytest

from app.catalog_registry import TableRef
from app.connectors import trino_sync as s

T = TableRef("iceberg", "default", "orders")
S = TableRef("src_crm", "public", "orders")
COLS = [("id", "integer"), ("email", "varchar(255)"), ("flag", "tinyint"), ("ts", "timestamp(3)"),
        ("doc", "json"), ("amt", "decimal(10,2)"), ("oid", "ObjectId")]


@pytest.mark.parametrize("src,dst", [
    ("tinyint", "integer"), ("smallint", "integer"), ("char(3)", "varchar"),
    ("varchar(255)", "varchar"), ("varchar", "varchar"), ("timestamp(0)", "timestamp(6)"),
    ("timestamp", "timestamp(6)"), ("timestamp(3) with time zone", "timestamp(6) with time zone"),
    ("time(3)", "time(6)"), ("time(3) with time zone", "varchar"), ("json", "varchar"),
    ("interval day to second", "varchar"), ("decimal(40,2)", "decimal(38,2)"),
    ("decimal(10,2)", "decimal(10,2)"), ("ObjectId", "varchar"), ("array(varchar)", "array(varchar)"),
    ("row(a integer)", "row(a integer)"), ("bigint", "bigint"), ("uuid", "uuid"), ("TINYINT", "integer"),
])
def test_types_iceberg_cannot_hold_are_mapped(src, dst):
    assert s.iceberg_type(src) == dst


def test_create_statement_quotes_names_and_renders_partitioning():
    sql = s.build_create(T, COLS, [
        {"column": "ts", "transform": "day"}, {"column": "id", "transform": "bucket", "buckets": 8},
        {"column": "flag", "transform": "identity"}, {"column": "x", "transform": "weird"}])
    assert sql.startswith(
        'CREATE TABLE IF NOT EXISTS "iceberg"."default"."orders" ("id" integer, "email" varchar, '
        '"flag" integer, "ts" timestamp(6), "doc" varchar, "amt" decimal(10,2), "oid" varchar)')
    assert sql.endswith("""WITH (partitioning = ARRAY['day("ts")', 'bucket("id", 8)', '"flag"'])""")
    assert s.partition_clause(None) == "" and s.partition_clause([]) == ""
    assert "truncate(\"email\", 4)" in s.partition_clause([{"column": "email", "transform": "truncate", "width": 4}])


def test_full_sync_is_delete_then_insert_select_with_casts_and_masks():
    delete, insert = s.build_full(T, S, COLS, pii_columns=["email"])
    assert delete == 'DELETE FROM "iceberg"."default"."orders"'
    assert insert.startswith('INSERT INTO "iceberg"."default"."orders" SELECT "id" AS "id", regexp_replace(')
    assert 'CAST("flag" AS integer) AS "flag"' in insert
    assert 'json_format(CAST("doc" AS JSON)) AS "doc"' in insert
    assert 'CAST("ts" AS timestamp(6)) AS "ts"' in insert and '"amt" AS "amt"' in insert
    assert insert.endswith('FROM "src_crm"."public"."orders"')


def test_star_masks_every_varchar_column_only():
    assert s.pii_set(COLS, ["*"]) == {"email", "doc", "oid"}
    assert s.pii_set(COLS, ["email", "nope"]) == {"email"}
    assert s.pii_set(COLS, ["id"]) == set(), "an integer column carries no text to mask"
    assert s.pii_set(COLS, None) == set() and s.pii_set(COLS, []) == set()


def test_incremental_without_keys_binds_the_watermark_as_a_parameter():
    stmts, watermark = s.build_incremental(T, S, COLS, None, "ts", "2026-01-01 00:00:00", key_columns=None)
    (sql, params), = stmts
    assert sql.endswith('FROM "src_crm"."public"."orders" WHERE "ts" > ?')
    assert params == ["2026-01-01 00:00:00"] and "2026-01-01" not in sql
    assert watermark == 'SELECT max("ts") FROM "src_crm"."public"."orders"'


def test_a_first_incremental_run_has_no_predicate():
    (sql, params), = s.build_incremental(T, S, COLS, None, "ts", None, key_columns=None)[0]
    assert "WHERE" not in sql and params == []


def test_incremental_with_keys_is_a_merge():
    (sql, params), = s.build_incremental(T, S, COLS, None, "ts", None, key_columns=["id"])[0]
    assert sql.startswith('MERGE INTO "iceberg"."default"."orders" t USING (SELECT ') and params == []
    assert 'ON t."id" = s."id"' in sql
    assert "WHEN MATCHED THEN UPDATE SET" in sql and "WHEN NOT MATCHED THEN INSERT" in sql
    update = sql.split("UPDATE SET")[1].split("WHEN NOT")[0]
    assert '"id" = s."id"' not in update and '"email" = s."email"' in update
    assert sql.endswith('VALUES (s."id", s."email", s."flag", s."ts", s."doc", s."amt", s."oid")')


def test_a_merge_whose_every_column_is_a_key_only_inserts():
    (sql, _), = s.build_incremental(T, S, [("id", "integer")], None, "id", 5, key_columns=["id"])[0]
    assert "WHEN MATCHED" not in sql and "WHEN NOT MATCHED THEN INSERT" in sql


def test_evolve_adds_new_columns_and_refuses_a_type_change():
    assert s.build_evolve(T, [("id", "integer")], [("id", "integer"), ("email", "varchar(10)")]) == \
        ['ALTER TABLE "iceberg"."default"."orders" ADD COLUMN "email" varchar']
    assert s.build_evolve(T, [("ts", "timestamp(6)")], [("ts", "timestamp(3)")]) == []
    with pytest.raises(s.SchemaChanged) as e:
        s.build_evolve(T, [("id", "integer")], [("id", "varchar(10)")])
    assert e.value.column == "id" and "integer" in str(e.value) and "varchar" in str(e.value)


def test_identifiers_with_quotes_cannot_break_out():
    assert s.quote('a"b') == '"a""b"'
    assert s.qualified(TableRef('x"y', "s", "t")) == '"x""y"."s"."t"'
    with pytest.raises(ValueError):
        s.quote("")


def test_target_ref_strips_the_source_from_the_route_target_and_normalises_the_name():
    assert s.target_ref("public.Orders-2026", None).sql() == "iceberg.default.orders_2026"
    assert s.target_ref("public.orders", "raw.orders").sql() == "iceberg.raw.orders"
    assert s.target_ref("public.orders", "datapond.default.public.orders").sql() == "iceberg.default.orders"
    assert s.target_ref("orders", "datapond.default.orders").sql() == "iceberg.default.orders"
    assert s.target_ref("public.orders", "datapond.sales.orders").sql() == "iceberg.sales.orders"
