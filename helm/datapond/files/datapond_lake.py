"""
datapond_lake — sanctioned DuckDB access helper for JupyterLab (RLS Layer 3).

Direct DuckDB reads from SeaweedFS bypass Trino/Polaris RLS. This helper routes
queries through a backend check so sensitive (policy-bearing) tables are blocked
from direct reads and the analyst is told to use Trino/views instead. Non-sensitive
tables run on embedded DuckDB as usual.

NOTE: this is the *soft* / UX layer — it can be bypassed by calling duckdb directly.
The hard boundary is the SeaweedFS S3 identity prefix-deny applied by the platform
(see docs/RLS_DESIGN.md §6 and GET /api/governance/rls/sensitive-tables). Use both.

Usage in a notebook:
    import datapond_lake as dp
    dp.sql("SELECT * FROM iceberg.public.events LIMIT 10")   # runs on DuckDB
    dp.sql("SELECT * FROM iceberg.sales.orders")             # raises SensitiveTableError
"""
from __future__ import annotations

import os
import urllib.request
import json

BACKEND = os.getenv("DATAPOND_BACKEND", "http://backend.datapond.svc.cluster.local:8000")
_CHECK_URL = BACKEND.rstrip("/") + "/api/governance/rls/check-direct-read"


class SensitiveTableError(RuntimeError):
    """Raised when a direct read targets a sensitive (RLS-protected) table."""


def _check(sql: str) -> dict:
    try:
        req = urllib.request.Request(
            _CHECK_URL, data=json.dumps({"sql": sql}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        # fail-closed: if we can't verify, block (can't prove it's non-sensitive)
        return {"blocked": True, "table": None,
                "reason": "거버넌스 백엔드에 연결할 수 없어 직접읽기를 차단합니다"}


def guard(sql: str) -> None:
    """Raise SensitiveTableError if `sql` touches a sensitive table. Else return None."""
    verdict = _check(sql)
    if verdict.get("blocked"):
        tbl = verdict.get("table") or "(알 수 없음)"
        raise SensitiveTableError(
            f"⛔ 민감 테이블 직접읽기 차단: {tbl}\n"
            f"   사유: {verdict.get('reason')}\n"
            f"   → Query Lab(Trino) 또는 제공된 보안 뷰를 사용하세요."
        )


def sql(query: str, con=None):
    """Run `query` on DuckDB after the sensitivity check. Returns a DuckDB relation."""
    guard(query)
    import duckdb
    if con is None:
        con = duckdb.connect()
        # configure SeaweedFS S3 access (same env Jupyter already has)
        ep = os.getenv("SEAWEEDFS_S3_ENDPOINT", "http://seaweedfs-s3:8333").replace("http://", "").replace("https://", "")
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"SET s3_endpoint='{ep}'; SET s3_url_style='path'; SET s3_use_ssl=false;")
        con.execute(f"SET s3_access_key_id='{os.getenv('AWS_ACCESS_KEY_ID','')}';")
        con.execute(f"SET s3_secret_access_key='{os.getenv('AWS_SECRET_ACCESS_KEY','')}';")
    return con.sql(query)
