"""The statements a Trino-backed sync runs.

A source that is a Trino catalog is copied into Iceberg by Trino itself: CREATE TABLE
IF NOT EXISTS, then DELETE + INSERT … SELECT (full) or MERGE / INSERT … SELECT with a
bound watermark (incremental), with new source columns added by ALTER TABLE first.
Nothing passes through the backend's memory. PII masking at ingest is part of the
SELECT list (pii_ko.mask_sql), so the raw value never reaches the lake.

Everything here is pure: builders take TableRefs and (name, trino_type) columns and
return SQL text; values bind as `?` parameters, never interpolated. Identifiers are
double-quoted with embedded quotes doubled, so a source column named `a"b` cannot
break out of its position.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from app.catalog_registry import TableRef
from .base import target_namespace

Column = Tuple[str, str]        # (name, trino type as information_schema reports it)

_DECIMAL = re.compile(r"^decimal\((\d+)\s*,\s*(\d+)\)$")
_TS = re.compile(r"^timestamp(\(\d+\))?( with time zone)?$")
_TIME = re.compile(r"^time(\(\d+\))?( with time zone)?$")
_VARCHARISH = re.compile(r"^(char|varchar)(\(\d+\))?$")


class SchemaChanged(ValueError):
    """A column the target already has arrives with a different type."""

    def __init__(self, column: str, old: str, new: str):
        self.column, self.old, self.new = column, old, new
        super().__init__(f"Column {column!r} changed type from {old} to {new}; Iceberg cannot "
                         f"alter it in place. Drop the target table or sync into a new one.")


def iceberg_type(trino_type: str) -> str:
    """The Iceberg column type a source column of `trino_type` lands as (Review Focus
    3). Iceberg has no tinyint/smallint/char/json/interval/time-with-zone and no
    precision below microseconds; decimals cap at 38 digits."""
    t = " ".join(str(trino_type or "").strip().lower().split())
    if t in ("tinyint", "smallint"):
        return "integer"
    if _VARCHARISH.match(t) or t in ("json", "objectid") or t.startswith("interval"):
        return "varchar"
    m = _TS.match(t)
    if m:
        return "timestamp(6) with time zone" if m.group(2) else "timestamp(6)"
    m = _TIME.match(t)
    if m:
        return "varchar" if m.group(2) else "time(6)"
    m = _DECIMAL.match(t)
    if m:
        p, sc = int(m.group(1)), int(m.group(2))
        return f"decimal({min(p, 38)},{min(sc, 38)})"
    return t


def quote(ident: str) -> str:
    if not isinstance(ident, str) or ident == "":
        raise ValueError("An identifier must be a non-empty string.")
    return '"' + ident.replace('"', '""') + '"'


def qualified(ref: TableRef) -> str:
    return ".".join(quote(p) for p in (ref.catalog, ref.namespace, ref.table) if p)


def _is_jsonish(trino_type: str) -> bool:
    t = str(trino_type or "").strip().lower()
    return t == "json" or t.startswith(("row(", "map("))


# Target column types that hold a narrower source type: a target written before 2.5
# (pandas → Arrow int64/float64) says bigint/double where the source says integer/real.
_WIDENS = {("integer", "bigint"), ("real", "double"), ("integer", "double"), ("bigint", "double")}


def compatible(source_type: str, target_type: str) -> bool:
    """Whether a target column of `target_type` can hold the source column as is or by a
    widening cast (the only type differences a sync tolerates). A decimal source loads
    into a double target: that is what the pandas path wrote for every NUMERIC column."""
    src, dst = iceberg_type(source_type), iceberg_type(target_type)
    if src.startswith("decimal(") and dst == "double":
        return True
    # A JSON source into a nested target written before 2.5 (pandas stored JSON objects as
    # Arrow structs): Trino casts JSON to ROW/ARRAY/MAP, matching row fields by name.
    if _is_jsonish(source_type) and dst.startswith(("row(", "array(", "map(")):
        return True
    return src == dst or (src, dst) in _WIDENS


REDACTED = "[개인정보]"


def column_expr(name: str, trino_type: str, *, pii: bool, target_type: Optional[str] = None,
                redact: bool = False) -> str:
    """One SELECT-list item: the column cast to what Iceberg holds — the target's existing
    type when the table already has the column — masked when PII. With `redact` (a column
    the user named as personal), a value no pattern matched is replaced whole: a name or an
    address matches no pattern and would otherwise be stored in the clear."""
    from app.guardrails import pii_ko
    col = quote(name)
    target = iceberg_type(target_type) if target_type else iceberg_type(trino_type)
    if pii and redact:
        masked = pii_ko.mask_sql(col)
        expr = (f"CASE WHEN {col} IS NULL THEN NULL WHEN {masked} = CAST({col} AS VARCHAR) "
                f"THEN '{REDACTED}' ELSE {masked} END")
    elif pii:
        expr = pii_ko.mask_sql(col)
    elif target == "varchar" and _is_jsonish(trino_type):
        expr = f"json_format(CAST({col} AS JSON))"
    elif target != " ".join(str(trino_type).strip().lower().split()):
        expr = f"CAST({col} AS {target})"
    else:
        expr = col
    return f"{expr} AS {col}"


def pii_set(columns: Sequence[Column], pii_columns: Optional[Iterable[str]]) -> Set[str]:
    """Which columns the SELECT masks: `['*']` → every column that lands as varchar;
    otherwise the named ones that exist and land as varchar (a number carries no text
    to mask, and a masked value is text)."""
    wanted = list(pii_columns or [])
    if not wanted:
        return set()
    text_cols = {n for n, t in columns if iceberg_type(t) == "varchar"}
    if wanted == ["*"]:
        return text_cols
    return {n for n in wanted if n in text_cols}


def redact_set(columns: Sequence[Column], pii_columns: Optional[Iterable[str]]) -> Set[str]:
    """The PII columns named one by one (not via '*'): never stored in the clear."""
    wanted = list(pii_columns or [])
    if not wanted or wanted == ["*"]:
        return set()
    return pii_set(columns, wanted)


_TRANSFORMS = {"identity", "year", "month", "day", "hour", "bucket", "truncate"}


def partition_clause(spec: Optional[list]) -> str:
    """`WITH (partitioning = ARRAY[…])` from [{"column", "transform", "buckets"|"width"}]."""
    parts: List[str] = []
    for item in spec or []:
        col, tr = item.get("column"), str(item.get("transform") or "identity").lower()
        if not col or tr not in _TRANSFORMS:
            continue
        q = quote(col).replace("'", "''")
        if tr == "identity":
            parts.append(q)
        elif tr == "bucket":
            parts.append(f"bucket({q}, {int(item.get('buckets') or 16)})")
        elif tr == "truncate":
            parts.append(f"truncate({q}, {int(item.get('width') or 4)})")
        else:
            parts.append(f"{tr}({q})")
    if not parts:
        return ""
    return "WITH (partitioning = ARRAY[" + ", ".join(f"'{p}'" for p in parts) + "])"


def build_create_schema(target: TableRef) -> str:
    """The target namespace, created if missing: a fresh Iceberg catalog (the kind
    job's Polaris) has no `default` schema and CREATE TABLE into it fails."""
    return f"CREATE SCHEMA IF NOT EXISTS {quote(target.catalog)}.{quote(target.namespace)}"


def build_create(target: TableRef, columns: Sequence[Column], partition_spec: Optional[list]) -> str:
    cols = ", ".join(f"{quote(n)} {iceberg_type(t)}" for n, t in columns)
    sql = f"CREATE TABLE IF NOT EXISTS {qualified(target)} ({cols})"
    clause = partition_clause(partition_spec)
    return f"{sql} {clause}" if clause else sql


def _select(source: TableRef, columns: Sequence[Column], pii: Set[str],
            existing: Optional[Sequence[Column]] = None, redact: Optional[Set[str]] = None) -> str:
    have = {n: t for n, t in (existing or [])}
    exprs = ", ".join(column_expr(n, t, pii=(n in pii), target_type=have.get(n), redact=(n in (redact or set())))
                      for n, t in columns)
    return f"SELECT {exprs} FROM {qualified(source)}"


def build_full(target: TableRef, source: TableRef, columns: Sequence[Column],
               pii_columns: Optional[Iterable[str]], existing: Optional[Sequence[Column]] = None,
               partition_spec: Optional[list] = None) -> List[str]:
    """One statement, one Iceberg commit: `CREATE OR REPLACE TABLE … AS SELECT`. A reader
    during the load sees the previous rows; a failed load leaves them (DELETE + INSERT
    had a window with none, and a failed INSERT left the table empty). The previous
    snapshot stays in the table's history."""
    partitioning = partition_clause(partition_spec)
    head = f"CREATE OR REPLACE TABLE {qualified(target)}" + (f" {partitioning}" if partitioning else "")
    return [f"{head} AS {_select(source, columns, pii_set(columns, pii_columns), existing, redact_set(columns, pii_columns))}"]


def _is_textual(trino_type: str) -> bool:
    t = str(trino_type).strip().lower()
    return t.startswith(("varchar", "char"))


def build_incremental(target: TableRef, source: TableRef, columns: Sequence[Column],
                      pii_columns: Optional[Iterable[str]], column: str, last_value,
                      key_columns: Optional[Sequence[str]],
                      existing: Optional[Sequence[Column]] = None) -> Tuple[List[Tuple[str, list]], str]:
    """Statements (sql, params) plus the watermark query. With keys a MERGE (changed rows
    update, new rows insert); without, an append. `last_value` None means a first run:
    every row, no predicate. The watermark is stored as text and the client binds text as
    varchar, which Trino does not coerce to a timestamp or a number: the parameter is
    CAST to the watermark column's own type (a textual column binds as it is)."""
    select = _select(source, columns, pii_set(columns, pii_columns), existing, redact_set(columns, pii_columns))
    params: list = []
    if last_value is not None:
        wm_type = next((t for n, t in columns if n == column), None)
        bound = "?" if wm_type is None or _is_textual(wm_type) else f"CAST(? AS {' '.join(str(wm_type).split())})"
        select += f" WHERE {quote(column)} > {bound}"
        params.append(last_value)
    keys = [k for k in (key_columns or []) if any(k == n for n, _ in columns)]
    if not keys:
        stmt = f"INSERT INTO {qualified(target)} {select}"
    else:
        names = [n for n, _ in columns]
        on = " AND ".join(f"t.{quote(k)} = s.{quote(k)}" for k in keys)
        updates = [f"{quote(n)} = s.{quote(n)}" for n in names if n not in keys]
        stmt = f"MERGE INTO {qualified(target)} t USING ({select}) s ON {on}"
        if updates:
            stmt += " WHEN MATCHED THEN UPDATE SET " + ", ".join(updates)
        stmt += (" WHEN NOT MATCHED THEN INSERT (" + ", ".join(quote(n) for n in names)
                 + ") VALUES (" + ", ".join(f"s.{quote(n)}" for n in names) + ")")
    watermark = f"SELECT max({quote(column)}) FROM {qualified(source)}"
    return [(stmt, params)], watermark


def build_evolve(target: TableRef, existing: Sequence[Column], wanted: Sequence[Column]) -> List[str]:
    """ADD COLUMN for every source column the target lacks; a shared column whose
    Iceberg type differs raises SchemaChanged — unless the target's type is wider
    (`compatible`): the load then casts up to it."""
    have = {n: t for n, t in existing}
    out: List[str] = []
    for n, t in wanted:
        want = iceberg_type(t)
        if n not in have:
            out.append(f"ALTER TABLE {qualified(target)} ADD COLUMN {quote(n)} {want}")
        elif not compatible(t, have[n]):
            raise SchemaChanged(n, iceberg_type(have[n]), want)
    return out


def safe_name(name: str) -> str:
    """The writer's rule for a table name: [a-zA-Z0-9_], lowercased."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", str(name or "")).lower()


def target_ref(source_table: str, target_table: Optional[str], catalog: Optional[str] = None) -> TableRef:
    """Where a sync of `source_table` ("schema.table") lands: catalog iceberg, the
    namespace the job names, the table's own name normalised. The routes build the
    default target as `datapond.default.<source_table>`, and a Trino source's table
    carries its schema, so that suffix is stripped before the namespace is read —
    otherwise the source schema would be mistaken for the target namespace."""
    src_table = str(source_table or "").split(".")[-1]
    target = str(target_table or "")
    for suffix in (f".{source_table}", f".{src_table}"):
        if source_table and target.endswith(suffix):
            target = target[: -len(suffix)]
            break
    else:
        target = target.rsplit(".", 1)[0] if "." in target else ""
    namespace = target_namespace(f"{target}.x") if target else "default"
    return TableRef(catalog or "iceberg", namespace, safe_name(src_table))
