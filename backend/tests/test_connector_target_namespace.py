"""A sync writes to the namespace its job names.

Every connector called write_dataframe_to_iceberg without `schema=`, so every sync
landed in `default` while the job recorded its configured target — `sales.orders`
said in the job list, `default.orders` in the catalog, and the RAG sink (which reads
the namespace from the target) invalidated collections over a table that never
changed.
"""
import asyncio
import sys
import types

import pandas as pd

from app.connectors import database
from app.connectors.base import ConnectorType, SyncStatus, target_namespace
from app.connectors.custom import CustomConfig, CustomConnector
from app.connectors.database import DatabaseURLConfig, DatabaseURLConnector
from app.connectors.rest import RestConfig, RestConnector
from app.connectors.storage import S3Connector, StorageConfig


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Writer:
    def __init__(self):
        self.calls = []

    def __call__(self, df, table_name, schema="default", mode="overwrite", on_step=None,
                 partition_spec=None, join_cols=None):
        self.calls.append({"table": table_name, "schema": schema})
        return len(df)


def _patch_writer(monkeypatch):
    w = _Writer()
    fake = types.ModuleType("app.connectors.iceberg_writer")
    fake.write_dataframe_to_iceberg = w
    monkeypatch.setitem(sys.modules, "app.connectors.iceberg_writer", fake)
    return w


def test_the_namespace_is_the_part_before_the_table():
    assert target_namespace("datapond.sales.orders") == "sales"
    assert target_namespace("sales.orders") == "sales"
    assert target_namespace("orders") == "default"
    assert target_namespace(None) == "default"
    assert target_namespace("") == "default"
    # Same normalisation the writer applies to a table name.
    assert target_namespace("datapond.Sales-EU.orders") == "sales_eu"


def test_rest_writes_into_the_target_namespace(monkeypatch):
    w = _patch_writer(monkeypatch)
    r = RestConnector(RestConfig(name="r", connector_type=ConnectorType.REST_API,
                                 base_url="https://api.example.com"))

    async def _read(_src):
        return [{"a": 1}]
    monkeypatch.setattr(r, "read_data", _read)
    st = _run(r.sync_to_iceberg("endpoint", "datapond.sales.things"))
    assert st.status == SyncStatus.SUCCESS
    assert w.calls == [{"table": "things", "schema": "sales"}]


def test_custom_writes_into_the_target_namespace(monkeypatch):
    w = _patch_writer(monkeypatch)
    c = CustomConnector(CustomConfig(name="c", connector_type=ConnectorType.CUSTOM,
                                     code="def fetch_data():\n    return [{'id': 1}]"))
    st = _run(c.sync_to_iceberg("src", "datapond.ops.result"))
    assert st.status == SyncStatus.SUCCESS
    assert w.calls == [{"table": "result", "schema": "ops"}]


def test_s3_writes_into_the_target_namespace(monkeypatch):
    w = _patch_writer(monkeypatch)
    s = S3Connector(StorageConfig(name="s", connector_type=ConnectorType.S3, bucket="b"))

    async def _list(prefix=None, max_files=1000):
        return [{"key": "in/a.csv"}]
    monkeypatch.setattr(s, "list_files", _list)
    monkeypatch.setattr(s, "_get_client", lambda: None)
    monkeypatch.setattr(s, "_read_file_to_df", lambda client, key: pd.DataFrame({"x": [1]}))
    st = _run(s.sync_to_iceberg("in/", "datapond.raw.files"))
    assert st.status == SyncStatus.SUCCESS
    assert w.calls == [{"table": "files", "schema": "raw"}]


def test_database_syncs_write_into_the_target_namespace(monkeypatch):
    captured = {}

    def fake_rwc(engine, query, source_table, write_mode, incremental_column,
                 on_step=None, partition_spec=None, key_columns=None, pii_columns=None,
                 chunk_size=database.INGEST_CHUNK_SIZE, params=None, namespace="default"):
        captured["namespace"] = namespace
        return 1, None

    monkeypatch.setattr(database, "_read_write_chunked", fake_rwc)
    c = DatabaseURLConnector(DatabaseURLConfig(
        name="d", connector_type=ConnectorType.DATABASE_URL, database_url="sqlite:///:memory:"))
    st = _run(c.sync_to_iceberg("public.events", "datapond.sales.events"))
    assert st.status == SyncStatus.SUCCESS
    assert captured["namespace"] == "sales"
    assert st.metadata["iceberg_table"] == "iceberg.sales.events"


def test_the_chunked_writer_passes_the_namespace_through(monkeypatch):
    w = _patch_writer(monkeypatch)

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Engine:
        def connect(self): return self
        def execution_options(self, **kw): return _Conn()

    monkeypatch.setattr(database.pd, "read_sql",
                        lambda sql, conn=None, chunksize=None, params=None:
                        iter([pd.DataFrame({"id": [1]})]))
    database._read_write_chunked(_Engine(), "SELECT 1", "t", "overwrite", None,
                                 namespace="sales")
    assert w.calls == [{"table": "t", "schema": "sales"}]
