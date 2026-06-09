"""
Iceberg writer for DataPond connectors.

Flow: pandas DataFrame → PyArrow Table → PyIceberg append/overwrite
  - Parquet 파일은 PyIceberg가 SeaweedFS S3에 직접 쓰고 단일 스냅샷으로 커밋한다.
  - 행 단위 INSERT VALUES 제거 → 스몰파일/스냅샷 폭발 및 SQL 인젝션 원천 차단.
  - 신규 테이블은 timestamp/date 컬럼 기준 day() 파티션을 자동 적용한다.

스파이크(2026-05-29, docs/LAKEHOUSE_P0_IMPLEMENTATION_PLAN.md)로 Polaris REST +
SeaweedFS S3 라운드트립 검증 완료.
"""
import logging
import re

import pandas as pd
import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError

from app.connectors.iceberg_catalog import get_catalog
from app.connectors.partitioning import infer_default_partition, apply_partition_spec

logger = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()


def _to_arrow(df: pd.DataFrame) -> pa.Table:
    """pandas → Arrow. Iceberg 비호환 타입(나노초 timestamp 등)을 정규화한다."""
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    return _normalize_for_iceberg(tbl)


def _normalize_for_iceberg(tbl: pa.Table) -> pa.Table:
    """
    Iceberg가 지원하지 않는 Arrow 타입을 캐스팅한다.
      - timestamp[ns] → timestamp[us]  (Iceberg는 마이크로초 정밀도까지만 지원)
      - large_string/large_binary → string/binary
    """
    new_fields = []
    changed = False
    for field in tbl.schema:
        t = field.type
        if pa.types.is_timestamp(t) and t.unit == "ns":
            t = pa.timestamp("us", tz=t.tz)
            changed = True
        elif pa.types.is_large_string(t):
            t = pa.string()
            changed = True
        elif pa.types.is_large_binary(t):
            t = pa.binary()
            changed = True
        new_fields.append(field.with_type(t))
    if not changed:
        return tbl
    return tbl.cast(pa.schema(new_fields))


def write_dataframe_to_iceberg(
    df: pd.DataFrame,
    table_name: str,
    schema: str = "default",
    mode: str = "overwrite",
    on_step=None,             # callable(step_name, message, extra={}) — 실시간 진행 보고
    partition_spec=None,      # list[dict] | None — None이면 timestamp 컬럼 기준 자동 추론
    join_cols=None,           # mode="upsert"일 때 머지 키(PK). 없으면 append로 폴백.
) -> int:
    """
    pandas DataFrame을 Iceberg 테이블에 쓴다 (PyIceberg).

    on_step 콜백으로 emit되는 step:
      schema_check → create (신규 시) → schema_evolution (append 시) → insert → done

    Returns: 기록된 행 수.
    """
    def step(name: str, msg: str, **extra):
        logger.info(f"[iceberg_writer] [{name}] {msg}")
        if on_step:
            on_step(name, msg, extra)

    if df is None or df.empty:
        step("skip", f"No rows for {schema}.{table_name}")
        return 0

    tbl_name = _safe_name(table_name)
    ident = (schema, tbl_name)
    fqtn = f"iceberg.{schema}.{tbl_name}"

    arrow = _to_arrow(df)
    cat = get_catalog()
    cat.create_namespace_if_not_exists((schema,))

    # ── 1. 테이블 확보 ─────────────────────────────────────────────────────────
    try:
        table = cat.load_table(ident)
        exists = True
        step("schema_check", f"Table {tbl_name} exists")
    except NoSuchTableError:
        table = None
        exists = False
        step("schema_check", f"Table {tbl_name} does not exist yet")

    # overwrite 모드에서 스키마 불일치 시 drop 후 재생성 (clean overwrite)
    if exists and mode == "overwrite" and not _schema_compatible(table, arrow):
        step("drop", f"Schema changed — dropping {tbl_name} for clean overwrite", action="drop")
        cat.drop_table(ident)
        table = None
        exists = False
        step("drop", f"Dropped {tbl_name}", action="done")

    if not exists:
        table = _create_table_with_partition(cat, ident, arrow, partition_spec, step)

    # ── 2. append/upsert 모드: 스키마 진화 (신규 컬럼 union-by-name) ─────────────
    if exists and mode in ("append", "upsert"):
        added = _evolve_schema(table, arrow, step)
        if added:
            table = cat.load_table(ident)
            step("schema_evolution", f"Schema evolved: added {len(added)} column(s): {', '.join(added)}",
                 action="done")

    # ── 3. 단일 커밋 쓰기 ──────────────────────────────────────────────────────
    rows = len(df)
    if mode == "upsert":
        # 증분 정확성: PK(join_cols) 기준 merge — 변경행 갱신 + 신규행 삽입(중복 방지).
        # 키 미지정 시 dedup 불가 → append 폴백(기존 동작). 삭제 반영은 CDC 경로 담당.
        aligned = _align_to_table(table, arrow)
        if join_cols:
            res = table.upsert(aligned, join_cols=list(join_cols))
            up = getattr(res, "rows_updated", None); ins = getattr(res, "rows_inserted", None)
            step("insert", f"Upsert by {join_cols}: +{ins if ins is not None else '?'} / ~{up if up is not None else '?'}",
                 rows_done=rows, rows_total=rows, pct=100)
            return rows
        step("insert", "upsert 모드이나 join_cols 미지정 → append 폴백")
        table.append(aligned)
    elif mode == "overwrite" and exists:
        # 컬럼 정렬 후 overwrite. 타입 변경 등 스키마 비호환이면 drop 후 재생성(과거 동작 유지).
        try:
            table.overwrite(_align_to_table(table, arrow))
        except Exception as e:
            step("drop", f"Overwrite 비호환 ({e}) — {tbl_name} 재생성", action="drop")
            cat.drop_table(ident)
            table = _create_table_with_partition(cat, ident, arrow, partition_spec, step)
            table.append(arrow)
    else:
        # 갓 생성/재생성된 빈 테이블 또는 append 모드
        table.append(_align_to_table(table, arrow))
    step("insert", f"Wrote {rows:,} rows ({mode}, 1 commit)",
         rows_done=rows, rows_total=rows, pct=100)

    step("done", f"Wrote {rows} rows → {fqtn}", rows=rows)
    return rows


def _create_table_with_partition(cat, ident, arrow, partition_spec, step):
    """테이블 생성 + 파티션 적용 후 (재)로드한 테이블 반환."""
    table = cat.create_table(ident, schema=arrow.schema)
    spec_def = partition_spec if partition_spec is not None else infer_default_partition(arrow.schema)
    if spec_def:
        applied = apply_partition_spec(table, spec_def)
        table = cat.load_table(ident)
        step("create", f"Created {ident[1]} (partition={applied})", action="done")
    else:
        step("create", f"Created {ident[1]} (unpartitioned)", action="done")
    return table


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _schema_compatible(table, arrow: pa.Table) -> bool:
    """기존 테이블 컬럼 집합이 arrow 컬럼 집합과 동일한지(이름 기준)."""
    existing = {f.name for f in table.schema().fields}
    incoming = set(arrow.schema.names)
    return existing == incoming


def _evolve_schema(table, arrow: pa.Table, step) -> list[str]:
    """arrow에만 있는 신규 컬럼을 union_by_name으로 추가. 반환: 추가된 컬럼명."""
    existing = {f.name for f in table.schema().fields}
    new_cols = [n for n in arrow.schema.names if n not in existing]
    if not new_cols:
        return []
    try:
        with table.update_schema() as update:
            update.union_by_name(arrow.schema)
        return new_cols
    except Exception as e:
        step("schema_evolution", f"Schema evolution warning: {e}")
        return []


def _align_to_table(table, arrow: pa.Table) -> pa.Table:
    """
    테이블 스키마 기준으로 arrow 컬럼을 정렬하고, 누락 컬럼은 해당 필드 타입의 null로 채운다.
    (append 시 일부 컬럼이 없는 배치를 안전하게 쓰기 위함. 누락 컬럼을 type=null로 채우면
    PyIceberg append가 스키마 비호환으로 거부하므로 반드시 필드 타입을 지정한다.)
    """
    from pyiceberg.io.pyarrow import schema_to_pyarrow
    table_schema = schema_to_pyarrow(table.schema())
    table_names = [f.name for f in table_schema]
    incoming = set(arrow.schema.names)
    if list(arrow.schema.names) == table_names:
        return arrow
    cols = {name: arrow.column(name) for name in arrow.schema.names}
    n = arrow.num_rows
    arrays = []
    for field in table_schema:
        if field.name in incoming:
            arrays.append(cols[field.name])
        else:
            arrays.append(pa.nulls(n, type=field.type))
    return pa.table(arrays, names=table_names)
