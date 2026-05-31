"""
Iceberg 파티션 적용 + 기본 추론.

스파이크(2026-05-29)로 검증된 패턴: PartitionSpec/PartitionField를 직접 조립하면
create_table 시 field-id 매칭에 실패한다. 반드시 update_spec(컬럼명 기반)으로 적용한다.
"""
import logging

import pyarrow as pa
from pyiceberg.transforms import (
    DayTransform, MonthTransform, YearTransform, IdentityTransform, BucketTransform,
)

logger = logging.getLogger(__name__)

_TRANSFORMS = {
    "day":      DayTransform,
    "month":    MonthTransform,
    "year":     YearTransform,
    "identity": IdentityTransform,
}


def infer_default_partition(schema: pa.Schema) -> list[dict]:
    """첫 timestamp/date 컬럼을 day() 파티션으로 추론. 없으면 무파티션([])."""
    for f in schema:
        if pa.types.is_timestamp(f.type) or pa.types.is_date(f.type):
            return [{"column": f.name, "transform": "day"}]
    return []


def apply_partition_spec(tbl, spec_def: list[dict]) -> str:
    """
    update_spec으로 컬럼명 기반 파티션을 추가한다. 이미 동일 파티션이면 무시.
    spec_def: [{"column": "ts", "transform": "day"}, {"column": "region", "transform": "identity"}, ...]
    반환: 적용된 spec의 문자열 표현 (로깅/진행표시용).
    """
    if not spec_def:
        return str(tbl.spec())

    existing_cols = {c for c in schema_field_names(tbl)}
    with tbl.update_spec() as us:
        for s in spec_def:
            col = s["column"]
            if col not in existing_cols:
                logger.warning(f"[partitioning] 파티션 컬럼 '{col}' 가 스키마에 없음 — 건너뜀")
                continue
            transform_name = s.get("transform", "identity")
            if transform_name == "bucket":
                transform = BucketTransform(num_buckets=int(s.get("buckets", 16)))
            else:
                transform_cls = _TRANSFORMS.get(transform_name)
                if transform_cls is None:
                    logger.warning(f"[partitioning] 알 수 없는 transform '{transform_name}' — 건너뜀")
                    continue
                transform = transform_cls()
            # 파티션 필드명이 기존 데이터 컬럼과 충돌하지 않도록 보정
            part_name = f"{col}_{transform_name}"
            while part_name in existing_cols:
                part_name += "_part"
            us.add_field(col, transform, part_name)
    return str(tbl.spec())


def schema_field_names(tbl) -> list[str]:
    """테이블 스키마의 최상위 컬럼명 목록."""
    return [f.name for f in tbl.schema().fields]
