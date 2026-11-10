"""The executor runs the builders' statements in order against a recorded cursor and
reports rows, steps and the watermark the way /sync and /sync/stream consume them
(Phase 2 plan, Task 6; replaces the pandas-path tests)."""
import asyncio
import re

from app.connectors.base import ConnectorType as T, SyncMode, SyncStatus
from app.connectors.trino_source import TrinoSourceConfig, TrinoSourceConnector


class Cursor:
    """Answers keyed by what a statement is: the source's columns, the target's
    columns, the load (INSERT/MERGE count row), the watermark."""

    def __init__(self, answers):
        self.answers, self.executed, self.params, self._rows = answers, [], [], []
        self.description = [("n",)]

    def execute(self, sql, params=None):
        self.executed.append(sql)
        self.params.append(params)
        s = " ".join(sql.split())
        if "src_crm.information_schema.columns" in s:
            self._rows = self.answers.get("source_columns", [])
        elif "iceberg.information_schema.columns" in s:
            self._rows = self.answers.get("target_columns", [])
        elif s.startswith(("INSERT INTO", "MERGE INTO", "CREATE OR REPLACE TABLE")):
            if "boom" in self.answers:
                raise RuntimeError(self.answers["boom"])
            self._rows = self.answers.get("load", [])
        elif s.startswith("SELECT max("):
            self._rows = self.answers.get("watermark", [])
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


def _connector(answers, password="p"):
    c = TrinoSourceConnector(TrinoSourceConfig(name="crm", connector_type=T.POSTGRESQL, host="h",
                                               port=5432, database="d", username="u",
                                               password=password, catalog="src_crm"))
    c.cur = Cursor(answers)
    c._connect = lambda **kw: Conn(c.cur)
    return c


def test_full_sync_runs_introspect_create_replace_and_counts_rows():
    c = _connector({"source_columns": [("id", "integer", "NO"), ("email", "varchar(255)", "YES")],
                    "target_columns": [], "load": [(42,)]})
    steps = []
    st = asyncio.run(c.sync_to_iceberg("public.orders", "datapond.default.public.orders", SyncMode.FULL,
                                       on_step=lambda n, m, e: steps.append(n), pii_columns=["email"]))
    assert st.status == SyncStatus.SUCCESS, st.error_message
    assert st.rows_processed == 42
    assert steps == ["connect", "introspect", "create", "evolve", "load"]
    ex = [" ".join(x.split()) for x in c._last_cursor.executed]
    assert ex[0].startswith("SELECT column_name, data_type, is_nullable FROM src_crm.information_schema.columns")
    assert ex[1].startswith("SELECT column_name, data_type FROM iceberg.information_schema.columns")
    assert ex[2] == 'CREATE SCHEMA IF NOT EXISTS "iceberg"."default"'
    assert ex[3].startswith('CREATE TABLE IF NOT EXISTS "iceberg"."default"."orders" ("id" integer, "email" varchar)')
    assert ex[4].startswith('CREATE OR REPLACE TABLE "iceberg"."default"."orders" AS SELECT "id" AS "id", regexp_replace(')
    assert len(ex) == 5, "one load statement: the replace is the only commit"
    assert not any(x.startswith(("ALTER", "DELETE")) for x in ex), "a fresh table has nothing to evolve"
    assert st.metadata["iceberg_table"] == "iceberg.default.orders" and st.metadata["max_value"] is None


def test_target_namespace_defaults_and_is_normalised():
    c = _connector({})
    assert c._target("public.Orders-2026", None).sql() == "iceberg.default.orders_2026"
    assert c._target("public.orders", "raw.orders").sql() == "iceberg.raw.orders"


def test_incremental_sync_merges_evolves_and_advances_the_watermark():
    c = _connector({"source_columns": [("id", "integer", "NO"), ("ts", "timestamp(3)", "YES"),
                                       ("note", "varchar", "YES")],
                    "target_columns": [("id", "integer"), ("ts", "timestamp(6)")],
                    "load": [(5,)], "watermark": [("2026-02-02 00:00:00",)]})
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.INCREMENTAL,
                                       incremental_column="ts", last_value="2026-01-01 00:00:00",
                                       key_columns=["id"]))
    assert st.status == SyncStatus.SUCCESS, st.error_message
    assert st.rows_processed == 5 and st.metadata["max_value"] == "2026-02-02 00:00:00"
    ex = [" ".join(x.split()) for x in c._last_cursor.executed]
    assert any(x == 'ALTER TABLE "iceberg"."default"."orders" ADD COLUMN "note" varchar' for x in ex)
    merge = next(i for i, x in enumerate(ex) if x.startswith("MERGE INTO"))
    assert c._last_cursor.params[merge] == ["2026-01-01 00:00:00"]
    assert "2026-01-01" not in ex[merge] and 'WHERE "ts" > CAST(? AS timestamp(3))' in ex[merge]
    assert ex[-1] == 'SELECT max("ts") FROM "src_crm"."public"."orders"'


def test_an_empty_incremental_run_keeps_the_old_watermark():
    c = _connector({"source_columns": [("id", "integer", "NO"), ("ts", "timestamp(3)", "YES")],
                    "target_columns": [("id", "integer"), ("ts", "timestamp(6)")],
                    "load": [(0,)], "watermark": [(None,)]})
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.INCREMENTAL,
                                       incremental_column="ts", last_value="2026-01-01 00:00:00"))
    assert st.status == SyncStatus.SUCCESS and st.rows_processed == 0
    assert st.metadata["max_value"] == "2026-01-01 00:00:00"


def test_a_changed_column_type_fails_the_job_with_a_readable_message():
    c = _connector({"source_columns": [("id", "varchar(10)", "NO")],
                    "target_columns": [("id", "integer")]})
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.FULL))
    assert st.status == SyncStatus.FAILED
    assert "id" in st.error_message and "integer" in st.error_message and "varchar" in st.error_message


def test_a_trino_error_fails_the_job_without_the_password():
    c = _connector({"source_columns": [("id", "integer", "NO")], "target_columns": [],
                    "boom": "TrinoUserError: password=hunter2 rejected"}, password="hunter2")
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.FULL))
    assert st.status == SyncStatus.FAILED
    assert "hunter2" not in (st.error_message or "") and "rejected" in st.error_message


def test_a_source_with_no_catalog_yet_cannot_sync():
    c = TrinoSourceConnector(TrinoSourceConfig(name="crm", connector_type=T.POSTGRESQL, host="h",
                                               port=5432, database="d", username="u", password="p"))
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.FULL))
    assert st.status == SyncStatus.FAILED and "catalog" in st.error_message.lower()


def test_a_source_table_with_no_columns_is_a_failure_not_an_empty_table():
    c = _connector({"source_columns": [], "target_columns": []})
    st = asyncio.run(c.sync_to_iceberg("public.nope", "default.nope", SyncMode.FULL))
    assert st.status == SyncStatus.FAILED and "nope" in st.error_message
    assert not any(x.startswith("CREATE") for x in c._last_cursor.executed)


def test_a_pre_2_5_target_with_wider_columns_is_loaded_with_casts_not_refused():
    """The pandas path wrote int64/float64: the lake says bigint/double where the source
    says integer/real. The upgrade note promises existing connections need nothing."""
    c = _connector({"source_columns": [("id", "integer", "NO"), ("score", "real", "YES")],
                    "target_columns": [("id", "bigint"), ("score", "double")], "load": [(3,)]})
    st = asyncio.run(c.sync_to_iceberg("public.orders", "default.orders", SyncMode.FULL))
    assert st.status == SyncStatus.SUCCESS, st.error_message
    load = next(x for x in c._last_cursor.executed if x.startswith("CREATE OR REPLACE"))
    assert 'CAST("id" AS bigint) AS "id"' in load and 'CAST("score" AS double) AS "score"' in load
