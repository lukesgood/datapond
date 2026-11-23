"""
Data Quality checks for DataPond connectors.
Runs after each sync: row count anomaly detection + null rate checks.
Results stored in connector_quality_checks table.
"""
import logging
import os
import uuid
from datetime import datetime
from typing import Iterable, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

from app.api.trino_util import TRINO_CATALOG, trino_conn

ROW_CHANGE_WARN_PCT = 20.0   # warn if row count changes ±20%
ROW_CHANGE_ALERT_PCT = 50.0  # alert if ±50%
NULL_RATE_WARN = 30.0        # warn if null rate >30% for any column
NULL_RATE_ALERT = 80.0       # alert if >80%


def _trino_conn():
    return trino_conn(timeout=30)


_QUALITY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS connector_quality_checks (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id     UUID NOT NULL,
    source_table      TEXT NOT NULL,
    checked_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    rows_current      BIGINT,
    rows_previous     BIGINT,
    row_change_pct    DOUBLE PRECISION,
    row_change_status TEXT,
    null_checks       JSONB,
    overall_status    TEXT,
    warnings          JSONB
);
CREATE INDEX IF NOT EXISTS idx_quality_conn_table_time
    ON connector_quality_checks (connection_id, source_table, checked_at DESC);
"""


async def ensure_quality_table(pool) -> None:
    """Idempotently create connector_quality_checks. The table was never added to
    schema/connectors.sql, so on DBs initialized from that schema it is missing —
    the writer's INSERT and the /quality endpoint's SELECT both fail without this.
    Best-effort; callers should not break if it can't run."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(_QUALITY_TABLE_DDL)
    except Exception as e:
        logger.warning(f"[quality] ensure table failed: {e}")


def _run_quality_check_sync(
    table_name: str,
    schema: str,
    rows_current: int,
    rows_previous: Optional[int],
    expected_nulls: Iterable[str] = (),
) -> dict:
    """
    Run quality checks against an Iceberg table via Trino.
    Returns check result dict.
    """
    fqtn = f"{TRINO_CATALOG}.{schema}.{table_name}"
    expected = {c.lower() for c in expected_nulls}
    warnings = []
    null_checks = {}
    overall_status = "ok"

    # 1. Row count anomaly
    row_change_pct = None
    row_change_status = "ok"
    if rows_previous is not None and rows_previous > 0:
        row_change_pct = ((rows_current - rows_previous) / rows_previous) * 100
        abs_pct = abs(row_change_pct)
        if abs_pct >= ROW_CHANGE_ALERT_PCT:
            row_change_status = "alert"
            overall_status = "alert"
            warnings.append({
                "type": "row_count_anomaly",
                "message": f"Row count changed {row_change_pct:+.1f}% (previous: {rows_previous:,}, current: {rows_current:,})",
                "severity": "alert",
            })
        elif abs_pct >= ROW_CHANGE_WARN_PCT:
            row_change_status = "warning"
            if overall_status == "ok":
                overall_status = "warning"
            warnings.append({
                "type": "row_count_anomaly",
                "message": f"Row count changed {row_change_pct:+.1f}% (previous: {rows_previous:,}, current: {rows_current:,})",
                "severity": "warning",
            })

    # 2. Null rate per column
    try:
        cur = _trino_conn().cursor()
        cur.execute(f"DESCRIBE {fqtn}")
        columns = [row[0] for row in cur.fetchall()]

        if columns and rows_current > 0:
            # Build single query for all null counts
            null_exprs = ", ".join(
                f"SUM(CASE WHEN \"{col}\" IS NULL THEN 1 ELSE 0 END) AS \"{col}\""
                for col in columns
            )
            cur2 = _trino_conn().cursor()
            cur2.execute(f"SELECT {null_exprs} FROM {fqtn}")
            row = cur2.fetchone()
            if row:
                for i, col in enumerate(columns):
                    null_count = row[i] or 0
                    null_rate = (null_count / rows_current) * 100
                    status = "ok"
                    if col.lower() in expected:
                        status = "expected"
                    elif null_rate >= NULL_RATE_ALERT:
                        status = "alert"
                        overall_status = "alert"
                        warnings.append({
                            "type": "high_null_rate", "column": col,
                            "message": f"Column '{col}' has {null_rate:.1f}% null values",
                            "severity": "alert",
                        })
                    elif null_rate >= NULL_RATE_WARN:
                        status = "warning"
                        if overall_status == "ok":
                            overall_status = "warning"
                        warnings.append({
                            "type": "high_null_rate", "column": col,
                            "message": f"Column '{col}' has {null_rate:.1f}% null values",
                            "severity": "warning",
                        })
                    null_checks[col] = {
                        "null_count": null_count,
                        "null_rate": round(null_rate, 2),
                        "status": status,
                    }
    except Exception as e:
        logger.warning(f"[quality] null check failed for {fqtn}: {e}")

    return {
        "rows_current": rows_current,
        "rows_previous": rows_previous,
        "row_change_pct": round(row_change_pct, 2) if row_change_pct is not None else None,
        "row_change_status": row_change_status,
        "null_checks": null_checks,
        "overall_status": overall_status,
        "warnings": warnings,
    }


async def run_and_store_quality_checks(
    pool: asyncpg.Pool,
    connection_id: str,
    table_results: list[tuple],  # (table, target, ok, rows, status)
    schema: str = "default",
) -> dict:
    """
    Run quality checks for all successfully synced tables and persist results.
    Best-effort, errors are swallowed. Returns {table: overall_status} (ok/warning/alert)
    so a caller can gate on it (await instead of create_task).
    """
    import asyncio
    import json as _json

    statuses: dict = {}

    from app.connectors import trino_sync

    for table, target, ok, rows_current, _ in table_results:
        if not ok or rows_current == 0:
            continue
        try:
            async with pool.acquire() as conn:
                # Previous count under either spelling: checks written before 2.5 say
                # `orders`, later ones `public.orders` — the same lake table.
                prev = await conn.fetchval(
                    """SELECT rows_current FROM connector_quality_checks
                       WHERE connection_id=$1 AND source_table = ANY($2::text[])
                       ORDER BY checked_at DESC LIMIT 1""",
                    uuid.UUID(connection_id), spellings(table)
                )
                expected = await _expected_nulls(conn, connection_id, table)

            # The lake table the sync wrote, not the source name: `public.orders` lands
            # in default.orders, and `iceberg.default.public.orders` does not exist — the
            # null checks of every schema-qualified table used to fail on it.
            ref = trino_sync.target_ref(table, target)
            result = await asyncio.to_thread(
                _run_quality_check_sync, ref.table, ref.namespace or schema, rows_current, prev, expected
            )

            # Persist
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO connector_quality_checks
                       (connection_id, source_table, checked_at,
                        rows_current, rows_previous, row_change_pct, row_change_status,
                        null_checks, overall_status, warnings)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                    uuid.UUID(connection_id), table, datetime.utcnow(),
                    result["rows_current"], result["rows_previous"],
                    result["row_change_pct"], result["row_change_status"],
                    _json.dumps(result["null_checks"]),
                    result["overall_status"],
                    _json.dumps(result["warnings"]),
                )
            statuses[table] = result["overall_status"]
            logger.info(f"[quality] {table}: {result['overall_status']} "
                        f"({len(result['warnings'])} warnings)")
        except Exception as e:
            logger.warning(f"[quality] check failed for {table}: {e}")
    return statuses


def spellings(source_table: str) -> List[str]:
    """`public.orders` and `orders`: the names one source table's checks were written
    under (bare before 2.5, schema-qualified after)."""
    bare = source_table.split(".")[-1]
    return [source_table] if bare == source_table else [source_table, bare]


def canonical(source_table: str) -> str:
    """The key checks of one table group under, whatever spelling they were written in."""
    return source_table.split(".")[-1].lower()


async def _expected_nulls(conn, connection_id: str, source_table: str) -> List[str]:
    try:
        raw = await conn.fetchval(
            """SELECT expected_null_columns FROM connector_sync_jobs
               WHERE connection_id=$1 AND source_table = ANY($2::text[])
               ORDER BY (source_table = $3) DESC LIMIT 1""",
            uuid.UUID(connection_id), spellings(source_table), source_table)
    except Exception:          # before migration 0034
        return []
    return parse_columns(raw)


def parse_columns(raw) -> List[str]:
    import json as _json
    if raw is None:
        return []
    try:
        v = _json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    return [str(c) for c in v] if isinstance(v, list) else []


def with_expected(check: dict, expected: Iterable[str]) -> dict:
    """A stored check read with today's expected-null columns: those columns' null
    warnings go, their status reads "expected", and the overall status is recomputed
    from what is left. A mark therefore takes effect on the check already shown, not
    only on the next sync."""
    exp = {c.lower() for c in expected}
    null_checks = {}
    for col, nc in (check.get("null_checks") or {}).items():
        nc = dict(nc)
        if col.lower() in exp:
            nc["status"] = "expected"
        elif nc.get("status") == "expected":     # mark removed since the check ran
            rate = nc.get("null_rate") or 0
            nc["status"] = "alert" if rate >= NULL_RATE_ALERT else "warning" if rate >= NULL_RATE_WARN else "ok"
        null_checks[col] = nc
    warnings = [w for w in (check.get("warnings") or []) if w.get("type") != "high_null_rate"]
    for col, nc in null_checks.items():
        if nc.get("status") in ("warning", "alert"):
            warnings.append({"type": "high_null_rate", "column": col, "severity": nc["status"],
                             "message": f"Column '{col}' has {nc.get('null_rate', 0):.1f}% null values"})
    levels = [w["severity"] for w in warnings]
    overall = "alert" if "alert" in levels else "warning" if "warning" in levels else "ok"
    return {**check, "null_checks": null_checks, "warnings": warnings, "overall_status": overall,
            "expected_null_columns": sorted(c for c in null_checks if c.lower() in exp)}
