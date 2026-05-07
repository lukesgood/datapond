"""
Iceberg writer for DataPond connectors.

Flow: pandas DataFrame → Trino CREATE TABLE IF NOT EXISTS → Trino INSERT
On schema mismatch: DROP + recreate (full mode only).
Data files (Parquet) are written by Trino directly to SeaweedFS S3.
"""

import os
import logging
import re
from datetime import datetime

import pandas as pd
import trino

logger = logging.getLogger(__name__)

TRINO_HOST        = os.getenv("TRINO_SERVICE_HOST", "trino.datapond.svc.cluster.local")
TRINO_PORT        = int(os.getenv("TRINO_SERVICE_PORT", "8080"))
ICEBERG_WAREHOUSE = os.getenv("ICEBERG_WAREHOUSE", "s3a://iceberg/warehouse")
TRINO_CATALOG     = "iceberg"


def _trino_conn():
    return trino.dbapi.connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        user="datapond",
        catalog=TRINO_CATALOG,
        schema="default",
        http_scheme="http",
        request_timeout=300,
    )


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()


def _pandas_to_trino_type(dtype) -> str:
    s = str(dtype)
    if "int64" in s:      return "BIGINT"
    if "int32" in s:      return "INTEGER"
    if "int" in s:        return "BIGINT"
    if "float64" in s:    return "DOUBLE"
    if "float" in s:      return "REAL"
    if "bool" in s:       return "BOOLEAN"
    if "datetime64" in s: return "TIMESTAMP(6)"
    if "date" in s:       return "DATE"
    return "VARCHAR"


def _col_defs(df: pd.DataFrame) -> str:
    return ",\n    ".join(
        f'"{_safe_name(col)}" {_pandas_to_trino_type(df[col].dtype)}'
        for col in df.columns
    )


def _values_row(row, df: pd.DataFrame) -> str:
    parts = []
    for col in df.columns:
        val = row[col]
        dtype = str(df[col].dtype)
        try:
            if val is None or pd.isna(val):
                parts.append("NULL")
                continue
        except (TypeError, ValueError):
            pass

        if "int" in dtype:
            parts.append(str(int(val)))
        elif "float" in dtype:
            parts.append(str(float(val)))
        elif "bool" in dtype:
            parts.append(str(bool(val)).lower())
        elif "datetime" in dtype:
            try:
                ts = pd.Timestamp(val)
                parts.append(f"TIMESTAMP '{ts.strftime('%Y-%m-%d %H:%M:%S.%f')}'")
            except Exception:
                parts.append("NULL")
        else:
            escaped = str(val).replace("'", "''")
            parts.append(f"'{escaped}'")

    return f"({', '.join(parts)})"


def _table_exists(cur, catalog: str, schema: str, tbl: str) -> bool:
    try:
        cur.execute(f"DESCRIBE {catalog}.{schema}.{tbl}")
        cur.fetchall()
        return True
    except Exception:
        return False


def _schemas_match(cur, catalog: str, schema: str, tbl: str, df: pd.DataFrame) -> bool:
    """Check if existing table column names AND types match the DataFrame."""
    try:
        cur.execute(f"DESCRIBE {catalog}.{schema}.{tbl}")
        rows = cur.fetchall()
        existing = {row[0].lower(): row[1].lower() for row in rows}
        new = {_safe_name(c).lower(): _pandas_to_trino_type(df[c].dtype).lower()
               for c in df.columns}
        if set(existing.keys()) != set(new.keys()):
            return False
        # Normalise type comparison: varchar == varchar(n), timestamp(6) == timestamp(6)
        for col in new:
            e_type = existing[col].split("(")[0]  # strip precision
            n_type = new[col].split("(")[0]
            if e_type != n_type:
                return False
        return True
    except Exception:
        return True  # table doesn't exist — no conflict


def write_dataframe_to_iceberg(
    df: pd.DataFrame,
    table_name: str,
    schema: str = "default",
    mode: str = "overwrite",
    on_step=None,   # callable(step, message, extra={}) for real-time progress
) -> int:
    """
    Write a pandas DataFrame to an Iceberg table via Trino.

    Steps emitted via on_step callback:
      schema_check → drop (if mismatch) → create → clear → insert(batch N/total)

    Returns number of rows written.
    """
    def step(name: str, msg: str, **extra):
        logger.info(f"[iceberg_writer] [{name}] {msg}")
        if on_step:
            on_step(name, msg, extra)

    if df.empty:
        step("skip", f"No rows for {schema}.{table_name}")
        return 0

    tbl      = _safe_name(table_name)
    location = f"{ICEBERG_WAREHOUSE}/{schema}/{tbl}"
    fqtn     = f"{TRINO_CATALOG}.{schema}.{tbl}"

    # ── 1. Drop existing table (overwrite = always fresh) ────────────────────
    #      This prevents Parquet file accumulation across syncs.
    if mode == "overwrite":
        step("schema_check", f"Checking existing table {tbl}…")
        check_cur = _trino_conn().cursor()
        exists = _table_exists(check_cur, TRINO_CATALOG, schema, tbl)
        if exists:
            # Try Trino DROP first, fall back to S3 wipe + catalog unregister
            step("drop", f"Dropping {tbl} for clean overwrite…", action="drop")
            dropped = False
            try:
                drop_cur = _trino_conn().cursor()
                drop_cur.execute(f"DROP TABLE {fqtn}")
                drop_cur.fetchall()
                dropped = True
                step("drop", f"Dropped {tbl}", action="done")
            except Exception:
                pass

            if not dropped:
                # S3 wipe + catalog unregister
                try:
                    import boto3
                    from botocore.config import Config
                    import os
                    s3 = boto3.client("s3",
                        endpoint_url=f"http://{os.getenv('S3_ENDPOINT','seaweedfs-s3:8333')}",
                        aws_access_key_id=os.getenv("S3_ACCESS_KEY","datapond"),
                        aws_secret_access_key=os.getenv("S3_SECRET_KEY","datapond_dev"),
                        config=Config(signature_version="s3v4"), region_name="us-east-1",
                    )
                    bucket = "iceberg"
                    prefix = f"warehouse/{schema}/{tbl}/"
                    while True:
                        resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
                        objs = resp.get("Contents", [])
                        if not objs: break
                        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objs]})
                    # Unregister from catalog
                    unreg_cur = _trino_conn().cursor()
                    unreg_cur.execute(f"CALL iceberg.system.unregister_table(schema_name=>'{schema}', table_name=>'{tbl}')")
                    unreg_cur.fetchall()
                    step("drop", f"Wiped S3 + unregistered {tbl}", action="done")
                except Exception as e:
                    step("drop", f"Wipe partial: {e}", action="skip")
        else:
            step("schema_check", f"Table {tbl} does not exist yet", action="ok")

    # ── 2. Create table ───────────────────────────────────────────────────────
    step("create", f"Creating table {tbl}…")
    create_cur = _trino_conn().cursor()
    create_cur.execute(f"""
CREATE TABLE IF NOT EXISTS {fqtn} (
    {_col_defs(df)}
) WITH (
    format = 'PARQUET',
    location = '{location}'
)""")
    create_cur.fetchall()
    step("create", f"Table {tbl} ready", action="done")

    # ── 4. Insert batches ─────────────────────────────────────────────────────
    BATCH = 500
    total = 0
    total_rows = len(df)
    for start in range(0, total_rows, BATCH):
        batch  = df.iloc[start:start + BATCH]
        values = ",\n    ".join(_values_row(row, df) for _, row in batch.iterrows())
        ins_cur = _trino_conn().cursor()
        ins_cur.execute(f"INSERT INTO {fqtn} VALUES\n    {values}")
        ins_cur.fetchall()
        total += len(batch)
        pct = round(total / total_rows * 100)
        step("insert", f"Inserted {total}/{total_rows} rows ({pct}%)",
             rows_done=total, rows_total=total_rows, pct=pct)

    step("done", f"Wrote {total} rows → {fqtn}", rows=total)
    return total
