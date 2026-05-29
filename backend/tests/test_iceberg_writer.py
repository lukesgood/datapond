"""
Unit tests for the PyIceberg writer's pure helpers (no catalog/cluster needed).

전체 end-to-end(Polaris REST + SeaweedFS S3) 검증은 운영 클러스터에서 수행하며
(docs/LAKEHOUSE_P0_IMPLEMENTATION_PLAN.md 스파이크), 여기서는 클러스터 없이도
회귀를 잡을 수 있는 순수 로직만 테스트한다.
"""
import datetime

import pandas as pd
import pyarrow as pa
import pytest

from app.connectors.iceberg_writer import (
    _safe_name, _normalize_for_iceberg, _align_to_table,
)
from app.connectors.partitioning import infer_default_partition


def test_safe_name():
    assert _safe_name("My Table-1") == "my_table_1"
    assert _safe_name("public.orders") == "public_orders"


def test_normalize_ns_timestamp_to_us():
    """Iceberg는 마이크로초까지만 지원 — pandas datetime64[ns]를 us로 캐스팅해야 한다."""
    df = pd.DataFrame({
        "id": [1, 2],
        "ts": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-02 00:00:00"]),  # ns
    })
    arrow = pa.Table.from_pandas(df, preserve_index=False)
    assert arrow.schema.field("ts").type.unit == "ns"

    normalized = _normalize_for_iceberg(arrow)
    assert normalized.schema.field("ts").type.unit == "us"
    # 값은 보존
    assert normalized.column("id").to_pylist() == [1, 2]


def test_normalize_large_string():
    arrow = pa.table({"s": pa.array(["a", "b"], type=pa.large_string())})
    out = _normalize_for_iceberg(arrow)
    assert out.schema.field("s").type == pa.string()


def test_normalize_noop_when_compatible():
    arrow = pa.table({"id": pa.array([1], type=pa.int64()),
                      "ts": pa.array([datetime.datetime(2026, 1, 1)], type=pa.timestamp("us"))})
    out = _normalize_for_iceberg(arrow)
    assert out is arrow  # 변경 없으면 동일 객체 반환


def test_infer_default_partition_timestamp():
    schema = pa.schema([("id", pa.int64()), ("created_at", pa.timestamp("us"))])
    assert infer_default_partition(schema) == [{"column": "created_at", "transform": "day"}]


def test_infer_default_partition_date():
    schema = pa.schema([("id", pa.int64()), ("d", pa.date32())])
    assert infer_default_partition(schema) == [{"column": "d", "transform": "day"}]


def test_infer_default_partition_none():
    schema = pa.schema([("id", pa.int64()), ("name", pa.string())])
    assert infer_default_partition(schema) == []


class _FakeField:
    def __init__(self, name): self.name = name


class _FakeSchema:
    def __init__(self, names): self.fields = [_FakeField(n) for n in names]


class _FakeTable:
    """_align_to_table는 table.schema().fields만 사용 → 최소 더블로 충분."""
    def __init__(self, names): self._names = names
    def schema(self): return _FakeSchema(self._names)


def test_align_reorders_and_fills_missing_with_null():
    table = _FakeTable(["id", "amount", "region"])
    arrow = pa.table({"amount": pa.array([1.0, 2.0]), "id": pa.array([1, 2])})  # region 없음, 순서 다름
    out = _align_to_table(table, arrow)
    assert out.schema.names == ["id", "amount", "region"]
    assert out.column("region").null_count == 2
    assert out.column("id").to_pylist() == [1, 2]


def test_align_noop_when_already_matching():
    table = _FakeTable(["id", "amount"])
    arrow = pa.table({"id": pa.array([1]), "amount": pa.array([1.0])})
    out = _align_to_table(table, arrow)
    assert out is arrow
