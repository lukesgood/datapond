"""
RLS Layer 3 — DuckDB / direct-S3 read guard (see docs/RLS_DESIGN.md §6).

The JupyterLab → DuckDB → SeaweedFS path reads Iceberg/parquet directly, bypassing
Trino/Polaris/RLS. Locked decision (2026-06-02): **block direct reads of sensitive
(policy-bearing) tables**; non-policy tables stay explorable.

Two layers:
  - SOFT (UX / sanctioned path): a Jupyter helper calls the backend check endpoint
    (`check_direct_read`) which reuses the engine with sensitive_block=True and tells
    the notebook to route sensitive tables through Trino/views.
  - HARD (real boundary): deny the shared Jupyter SeaweedFS S3 identity read access to
    the sensitive tables' S3 prefixes (`seaweedfs_deny_prefixes`). Since Jupyter uses
    ONE identity, sensitive tables become un-readable directly from any notebook.

This module is pure logic and unit-testable without a cluster.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import sqlglot
from sqlglot import exp

from .engine import RlsPolicy, _policy_key, _qualify


def sensitive_tables(policies: Sequence[RlsPolicy]) -> List[str]:
    """Canonical 'catalog.schema.table' keys that have ≥1 policy (= sensitive)."""
    return sorted({_policy_key(p) for p in policies if p.enabled})


def check_direct_read(sql: str, policies: Sequence[RlsPolicy]) -> Dict:
    """
    Decide whether a DuckDB/direct-read query touches a sensitive (policy-bearing)
    table. Unlike the Trino path, direct reads have NO default_deny — only sensitive
    tables are blocked; everything else stays explorable.
    Returns {"blocked": bool, "table": str|None, "reason": str|None}.
    Unparseable SQL fails closed (blocked) since we cannot prove it avoids sensitive tables.
    """
    sset = set(sensitive_tables(policies))
    if not sset:
        return {"blocked": False, "table": None, "reason": None}
    try:
        statements = [s for s in sqlglot.parse(sql, read="trino") if s is not None]
    except Exception:
        return {"blocked": True, "table": None,
                "reason": "쿼리를 파싱할 수 없어 직접읽기를 차단(민감테이블 포함 여부 불명)"}
    for stmt in statements:
        for tbl in stmt.find_all(exp.Table):
            key = _qualify(tbl)
            if key in sset:
                return {"blocked": True, "table": key,
                        "reason": f"민감 테이블 '{key}'은 직접읽기(DuckDB/S3) 차단 — Trino/뷰 사용"}
    return {"blocked": False, "table": None, "reason": None}


def default_warehouse_prefix(table_key: str, warehouse: str = "iceberg") -> str:
    """
    Best-effort S3 prefix for a table when no Polaris location lookup is wired.
    Convention: s3://<warehouse>/<schema>/<table> (catalog is the bucket-equiv warehouse).
    Real deployments should pass actual locations via `location_map`.
    """
    _catalog, schema, table = table_key.split(".")
    return f"{warehouse}/{schema}/{table}"


def seaweedfs_deny_prefixes(
    tables: Sequence[str],
    location_map: Optional[Dict[str, str]] = None,
    warehouse: str = "iceberg",
) -> List[str]:
    """
    S3 prefixes (bucket/key) the Jupyter identity must be denied Read on.
    `location_map`: table_key -> 's3://bucket/path' (from Polaris) when available;
    otherwise fall back to the warehouse-path convention.
    """
    out: List[str] = []
    location_map = location_map or {}
    for t in tables:
        loc = location_map.get(t)
        if loc:
            out.append(loc.replace("s3://", "").replace("s3a://", "").rstrip("/"))
        else:
            out.append(default_warehouse_prefix(t, warehouse))
    return sorted(set(out))
