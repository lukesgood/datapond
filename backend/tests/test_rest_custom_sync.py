"""
Unit tests: REST + Custom connectors actually WRITE to Iceberg (not fake-success).

Before this, both connectors read their records and returned SUCCESS with
rows_processed=len(records) but never committed anything, and their signatures
didn't even accept the key_columns/pii_columns the sync orchestrator always passes
(TypeError on any real sync). These tests pin: the write is invoked, rows_processed
is the real written count, the mode is overwrite/upsert (never append — both sources
re-produce their full result set each run), and empty input is an honest 0-row no-op.
"""
import asyncio
import sys
import types

from app.connectors.base import ConnectorType, SyncStatus
from app.connectors.custom import CustomConnector, CustomConfig
from app.connectors.rest import RestConnector, RestConfig


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _RecordingWriter:
    """Stand-in for write_dataframe_to_iceberg — records the call, returns row count."""
    def __init__(self):
        self.calls = []

    def __call__(self, df, table_name, mode="overwrite", on_step=None,
                 partition_spec=None, join_cols=None):
        self.calls.append({"rows": len(df), "table": table_name, "mode": mode,
                           "join_cols": join_cols})
        return len(df)


def _patch_writer(monkeypatch):
    """Inject a fake app.connectors.iceberg_writer so the connector's lazy
    `from .iceberg_writer import write_dataframe_to_iceberg` resolves to our
    recorder — avoids importing the pyarrow/pyiceberg native chain in the test."""
    w = _RecordingWriter()
    fake = types.ModuleType("app.connectors.iceberg_writer")
    fake.write_dataframe_to_iceberg = w
    monkeypatch.setitem(sys.modules, "app.connectors.iceberg_writer", fake)
    return w


def _custom(code):
    return CustomConnector(CustomConfig(
        name="c", connector_type=ConnectorType.CUSTOM, code=code))


def _rest():
    return RestConnector(RestConfig(
        name="r", connector_type=ConnectorType.REST_API, base_url="https://api.example.com"))


FETCH_3 = "def fetch_data():\n    return [{'id': 1}, {'id': 2}, {'id': 3}]"
FETCH_EMPTY = "def fetch_data():\n    return []"


# ── Custom connector ─────────────────────────────────────────────────────────

def test_custom_writes_rows_overwrite(monkeypatch):
    w = _patch_writer(monkeypatch)
    st = _run(_custom(FETCH_3).sync_to_iceberg("src", "iceberg.default.t"))
    assert st.status == SyncStatus.SUCCESS
    assert st.rows_processed == 3          # real written count, not a proxy
    assert len(w.calls) == 1               # the write actually happened
    assert w.calls[0]["mode"] == "overwrite" and w.calls[0]["table"] == "t"
    assert w.calls[0]["join_cols"] is None


def test_custom_upsert_when_key_columns(monkeypatch):
    w = _patch_writer(monkeypatch)
    st = _run(_custom(FETCH_3).sync_to_iceberg(
        "src", "iceberg.default.t", key_columns=["id"]))
    assert st.status == SyncStatus.SUCCESS
    assert w.calls[0]["mode"] == "upsert" and w.calls[0]["join_cols"] == ["id"]


def test_custom_empty_is_zero_row_success_no_write(monkeypatch):
    w = _patch_writer(monkeypatch)
    st = _run(_custom(FETCH_EMPTY).sync_to_iceberg("src", "iceberg.default.t"))
    assert st.status == SyncStatus.SUCCESS and st.rows_processed == 0
    assert w.calls == []                   # nothing written for an empty result


def test_custom_accepts_pii_columns_kwarg(monkeypatch):
    # regression: the orchestrator always passes pii_columns=; must not TypeError
    _patch_writer(monkeypatch)
    st = _run(_custom(FETCH_3).sync_to_iceberg(
        "src", "iceberg.default.t", pii_columns=["id"]))
    assert st.status == SyncStatus.SUCCESS


# ── REST connector ───────────────────────────────────────────────────────────

def test_rest_writes_rows_overwrite(monkeypatch):
    w = _patch_writer(monkeypatch)
    r = _rest()
    async def _fake_read(_src):
        return [{"a": 1}, {"a": 2}]
    monkeypatch.setattr(r, "read_data", _fake_read)
    st = _run(r.sync_to_iceberg("endpoint", "iceberg.default.things"))
    assert st.status == SyncStatus.SUCCESS
    assert st.rows_processed == 2
    assert w.calls[0]["mode"] == "overwrite" and w.calls[0]["table"] == "things"


def test_rest_empty_is_zero_row_success_no_write(monkeypatch):
    w = _patch_writer(monkeypatch)
    r = _rest()
    async def _fake_read(_src):
        return []
    monkeypatch.setattr(r, "read_data", _fake_read)
    st = _run(r.sync_to_iceberg("endpoint", "iceberg.default.things"))
    assert st.status == SyncStatus.SUCCESS and st.rows_processed == 0
    assert w.calls == []
