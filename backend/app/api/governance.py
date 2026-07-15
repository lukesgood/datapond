"""
Governance & Trust Layer API

Endpoints for audit log review, governance stats, PII detection, and SQL safety analysis.
All endpoints are read-only; data is derived from existing query_history table and
optional Trino information_schema queries.
"""
import os
import logging
from datetime import datetime, date
from typing import List, Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.connection import get_db
from app.models.query import QueryHistory

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Trino connection config (mirrors queries.py) ──────────────────────────────
TRINO_HOST = os.getenv("TRINO_HOST", "trino.datapond.svc.cluster.local")
_trino_port_raw = os.getenv("TRINO_PORT", "8080")
if _trino_port_raw.startswith("tcp://"):
    TRINO_PORT = int(_trino_port_raw.split(":")[-1])
else:
    TRINO_PORT = int(_trino_port_raw)
TRINO_USER = os.getenv("TRINO_USER", "datapond")

try:
    from trino.dbapi import connect as trino_connect
    TRINO_AVAILABLE = True
except ImportError:
    TRINO_AVAILABLE = False


# ── PII detection ─────────────────────────────────────────────────────────────

PII_COLUMN_PATTERNS = {
    "email":   ["email", "mail"],
    "phone":   ["phone", "mobile", "tel"],
    "ssn":     ["ssn", "social_security"],
    "card":    ["card_number", "credit_card", "pan"],
    "name":    ["full_name", "first_name", "last_name"],
    "address": ["address", "street", "postal", "zip"],
    "dob":     ["birth_date", "dob", "birthday"],
}


def detect_pii_columns(columns: List[str]) -> List[dict]:
    """Return list of {column, type} for columns matching PII patterns."""
    found = []
    for col in columns:
        col_lower = col.lower()
        for pii_type, patterns in PII_COLUMN_PATTERNS.items():
            if any(p in col_lower for p in patterns):
                found.append({"column": col, "type": pii_type})
                break
    return found


# ── SQL risk evaluation ───────────────────────────────────────────────────────

def evaluate_sql_risk(sql: str) -> str:
    """Return 'high', 'medium', or 'low' risk classification for a SQL statement."""
    sql_upper = sql.upper()
    high_keywords = ["DROP ", "TRUNCATE ", "DELETE ", "UPDATE ", "INSERT "]
    medium_keywords = ["SELECT *", "LIMIT 1000"]
    if any(kw in sql_upper for kw in high_keywords):
        return "high"
    if any(kw in sql_upper for kw in medium_keywords):
        return "medium"
    return "low"


# ── Response schemas ──────────────────────────────────────────────────────────

class AuditLogItem(BaseModel):
    id: str
    event_type: str
    query_text: Optional[str] = None
    user_id: Optional[str] = None
    status: str
    execution_time_ms: Optional[int] = None
    rows_returned: Optional[int] = None
    catalog: Optional[str] = None
    schema_name: Optional[str] = None
    created_at: str


class AuditLogResponse(BaseModel):
    items: List[AuditLogItem]
    total: int


class GovernanceStats(BaseModel):
    queries_today: int
    pii_detections: int


class PiiColumn(BaseModel):
    column: str
    type: str


class PiiTableEntry(BaseModel):
    table: str
    pii_columns: List[PiiColumn]


class PiiReport(BaseModel):
    tables: List[PiiTableEntry]
    scanned: bool = False  # False = no real scan ran (engine unsupported/unreachable) — NOT "clean"


class RiskDistribution(BaseModel):
    low: int
    medium: int
    high: int


class AiSafetyFlag(BaseModel):
    sql_preview: str
    risk: str
    user: str
    ts: str


class AiSafetyReport(BaseModel):
    risk_distribution: RiskDistribution
    recent_flags: List[AiSafetyFlag]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/governance/audit-log", response_model=AuditLogResponse)
def get_audit_log(
    event_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    Return paginated audit log entries derived from query_history.

    event_type filter (optional): 'query_executed', 'query_error', 'query_timeout'
    maps to the status column values ('success', 'error', 'timeout').
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be non-negative")

    # Map frontend event_type names to DB status values
    status_filter_map = {
        "query_executed": "success",
        "query_error":    "error",
        "query_timeout":  "timeout",
    }

    try:
        query = db.query(QueryHistory)

        if event_type:
            mapped_status = status_filter_map.get(event_type)
            if mapped_status:
                query = query.filter(QueryHistory.status == mapped_status)
            # unknown event_type → no rows (consistent with strict filtering)

        total = query.count()
        items = (
            query.order_by(QueryHistory.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        def _event_type(status: str) -> str:
            return {
                "success": "query_executed",
                "error":   "query_error",
                "timeout": "query_timeout",
            }.get(status, "query_executed")

        return AuditLogResponse(
            items=[
                AuditLogItem(
                    id=str(item.id),
                    event_type=_event_type(item.status),
                    query_text=item.query_text,
                    user_id=str(item.user_id) if item.user_id else None,
                    status=item.status,
                    execution_time_ms=item.execution_time_ms,
                    rows_returned=item.rows_returned,
                    catalog=item.catalog,
                    schema_name=item.schema,
                    created_at=item.created_at.isoformat() if item.created_at else "",
                )
                for item in items
            ],
            total=total,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("governance/audit-log error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch audit log: {exc}")


@router.get("/governance/stats", response_model=GovernanceStats)
def get_governance_stats(db: Session = Depends(get_db)):
    """
    Return high-level governance statistics.

    Only metrics with a genuine data source are returned: queries_today
    (query_history) and pii_detections (real column scan, see
    /governance/pii-report). Metrics with no dedicated storage/enforcement
    counter (AI SQL execution count, blocked-query count) are intentionally
    omitted rather than reported as a fabricated 0 — see the frontend, which
    drops those stat cards accordingly.
    """
    try:
        today = date.today()
        queries_today = (
            db.query(func.count(QueryHistory.id))
            .filter(func.date(QueryHistory.created_at) == today)
            .scalar()
            or 0
        )

        pii_tables = _scan_pii_tables()  # None if no scan ran
        pii_detections = sum(len(t.pii_columns) for t in pii_tables) if pii_tables else 0

        return GovernanceStats(
            queries_today=queries_today,
            pii_detections=pii_detections,
        )

    except Exception as exc:
        logger.error("governance/stats error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch governance stats: {exc}")


def _scan_pii_tables() -> Optional[List[PiiTableEntry]]:
    """
    Scan columns of tables in the active query engine's catalog for PII patterns.

    Returns:
      - a list (possibly empty) when a real Trino scan RAN — [] means "scanned,
        no PII columns found".
      - None when a scan COULD NOT run (engine isn't Trino, package missing, or
        Trino unreachable). None ≠ []: the caller must surface "not scanned",
        never "clean". NEVER fabricates rows.
    """
    # Skip entirely on a non-Trino engine (e.g. the live Athena/Glue foundation)
    # so we don't attempt a doomed 10s Trino connection on every governance load.
    engine = os.getenv("QUERY_ENGINE", "trino").strip().lower()
    if engine != "trino":
        logger.info("governance/pii-report: query engine is %s (not trino); no PII scan available", engine)
        return None
    if not TRINO_AVAILABLE:
        logger.info("governance/pii-report: trino package not installed; no PII scan available on this engine")
        return None

    try:
        conn = trino_connect(
            host=TRINO_HOST,
            port=TRINO_PORT,
            user=TRINO_USER,
            catalog="iceberg",
            schema="information_schema",
            http_scheme="http",
            request_timeout=10,
        )
        cursor = conn.cursor()

        # Fetch all column names from iceberg information_schema
        cursor.execute(
            "SELECT table_schema, table_name, column_name "
            "FROM iceberg.information_schema.columns "
            "ORDER BY table_schema, table_name, ordinal_position"
        )
        rows: List[Any] = cursor.fetchall()
        cursor.close()
        conn.close()

        # Group by table, run PII detector on column names
        table_map: dict = {}
        for schema_name, table_name, column_name in rows:
            key = f"{schema_name}.{table_name}"
            table_map.setdefault(key, []).append(column_name)

        result: List[PiiTableEntry] = []
        for tbl_key, col_names in sorted(table_map.items()):
            hits = detect_pii_columns(col_names)
            if hits:
                result.append(
                    PiiTableEntry(
                        table=tbl_key,
                        pii_columns=[PiiColumn(**h) for h in hits],
                    )
                )

        return result

    except Exception as exc:
        logger.warning("governance/pii-report: Trino unavailable (%s); no scan (no fabricated data)", exc)
        return None


@router.get("/governance/pii-report", response_model=PiiReport)
def get_pii_report():
    """
    Scan columns of recently queried tables for PII patterns.

    Real Trino information_schema scan only — no fabricated/mock fallback.
    Returns {tables: []} when no genuine scan can run (e.g. the live
    Athena/Glue foundation profile, which has no Trino information_schema
    to scan) or when the scan finds nothing.
    """
    scanned = _scan_pii_tables()
    return PiiReport(tables=scanned or [], scanned=scanned is not None)


# ── RLS / Masking policy management (P2) ──────────────────────────────────────
# Admin-only CRUD over rls_policies / column_masking_policies (auth.sql schema).
# Uses asyncpg via the RLS loader's pool. See docs/RLS_DESIGN.md.

try:
    from app.rls import loader as _rls_loader
    from app.rls.engine import enforce as _rls_enforce, RlsDenied as _RlsDenied, UserContext as _UserCtx
    from app.api.auth import get_current_user as _get_current_user
    _RLS_ADMIN_OK = True
except Exception as _e:  # pragma: no cover
    logger.warning("rls admin endpoints disabled: %s", _e)
    _RLS_ADMIN_OK = False

    async def _get_current_user(*a, **k):  # type: ignore
        return None


class RlsPolicyIn(BaseModel):
    name: str
    description: Optional[str] = None
    catalog_name: str
    schema_name: str
    table_name: str
    filter_expression: str
    enabled: bool = True
    priority: int = 0
    role_names: List[str] = []          # roles this policy applies to
    exempt_role_names: List[str] = []   # roles exempt from it


class MaskPolicyIn(BaseModel):
    name: str
    description: Optional[str] = None
    catalog_name: str
    schema_name: str
    table_name: str
    column_name: str
    masking_type: str
    custom_expression: Optional[str] = None
    enabled: bool = True
    role_names: List[str] = []
    exempt_role_names: List[str] = []


class RlsPreviewIn(BaseModel):
    sql: str
    roles: List[str] = []
    attributes: dict = {}


async def _require_admin(user: Optional[dict]) -> dict:
    if not _RLS_ADMIN_OK:
        raise HTTPException(status_code=503, detail="RLS 관리 비활성(의존성 누락)")
    if not user:
        raise HTTPException(status_code=401, detail="인증 필요")
    # JWT role or user_roles must include admin / security.manage_rls
    if user.get("role") == "admin":
        return user
    try:
        ctx = await _rls_loader.load_user_context(user)
        if "admin" in ctx.roles:
            return user
    except Exception:
        pass
    raise HTTPException(status_code=403, detail="admin 권한 필요")


def _validate_bool_expr(expr: str) -> None:
    """Best-effort: reject filter expressions that don't parse as a condition."""
    try:
        import sqlglot
        sqlglot.parse_one(f"SELECT 1 WHERE {expr}", read="trino")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"filter_expression 파싱 실패: {e}")


@router.get("/governance/roles")
async def list_roles(user: Optional[dict] = Depends(_get_current_user)):
    """List role names for policy assignment UI."""
    await _require_admin(user)
    try:
        pool = await _rls_loader._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name, display_name FROM roles ORDER BY name")
        return [{"name": r["name"], "display_name": r["display_name"]} for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("roles list failed: %s", e)
        return []


@router.get("/governance/rls/policies")
async def list_rls_policies(user: Optional[dict] = Depends(_get_current_user)):
    """List RLS policies with their role mappings."""
    await _require_admin(user)
    pols = await _rls_loader.load_policies()
    return [
        {
            "id": p.id, "catalog_name": p.catalog, "schema_name": p.schema,
            "table_name": p.table, "filter_expression": p.filter_expression,
            "priority": p.priority, "enabled": p.enabled,
            "roles": [r for r, ex in p.role_map.items() if not ex],
            "exempt_roles": [r for r, ex in p.role_map.items() if ex],
        }
        for p in pols
    ]


@router.post("/governance/rls/policies")
async def create_rls_policy(body: RlsPolicyIn, user: Optional[dict] = Depends(_get_current_user)):
    """Create an RLS policy + role mappings."""
    admin = await _require_admin(user)
    _validate_bool_expr(body.filter_expression)
    pool = await _rls_loader._get_pool()
    import uuid as _uuid
    async with pool.acquire() as conn:
        async with conn.transaction():
            pid = await conn.fetchval(
                """INSERT INTO rls_policies
                     (name, description, catalog_name, schema_name, table_name,
                      filter_expression, enabled, priority, created_by)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
                body.name, body.description, body.catalog_name, body.schema_name,
                body.table_name, body.filter_expression, body.enabled, body.priority,
                _uuid.UUID(admin["id"]) if admin.get("id") else None,
            )
            for rn in body.role_names:
                await conn.execute(
                    """INSERT INTO rls_policy_roles (policy_id, role_id, is_exempt)
                       SELECT $1, id, false FROM roles WHERE name = $2
                       ON CONFLICT DO NOTHING""", pid, rn)
            for rn in body.exempt_role_names:
                await conn.execute(
                    """INSERT INTO rls_policy_roles (policy_id, role_id, is_exempt)
                       SELECT $1, id, true FROM roles WHERE name = $2
                       ON CONFLICT (policy_id, role_id) DO UPDATE SET is_exempt = true""", pid, rn)
            await _audit_policy_event(conn, admin, "rls_policy_created", str(pid), body.name)
    return {"id": str(pid), "message": "RLS 정책 생성됨"}


@router.patch("/governance/rls/policies/{policy_id}")
async def update_rls_policy(policy_id: str, body: dict, user: Optional[dict] = Depends(_get_current_user)):
    """Update enabled / filter_expression / priority of an RLS policy."""
    admin = await _require_admin(user)
    if "filter_expression" in body:
        _validate_bool_expr(body["filter_expression"])
    import uuid as _uuid
    sets, vals, idx = [], [], 1
    for col in ("filter_expression", "priority", "enabled", "description"):
        if col in body:
            sets.append(f"{col} = ${idx}"); vals.append(body[col]); idx += 1
    if not sets:
        raise HTTPException(status_code=400, detail="변경할 항목 없음")
    vals.append(_uuid.UUID(policy_id))
    pool = await _rls_loader._get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            f"UPDATE rls_policies SET {', '.join(sets)}, updated_at = NOW() WHERE id = ${idx}", *vals)
        await _audit_policy_event(conn, admin, "rls_policy_updated", policy_id, None)
    if res == "UPDATE 0":
        raise HTTPException(status_code=404, detail="정책 없음")
    return {"message": "RLS 정책 수정됨"}


@router.delete("/governance/rls/policies/{policy_id}")
async def delete_rls_policy(policy_id: str, user: Optional[dict] = Depends(_get_current_user)):
    admin = await _require_admin(user)
    import uuid as _uuid
    pool = await _rls_loader._get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM rls_policies WHERE id = $1", _uuid.UUID(policy_id))
        await _audit_policy_event(conn, admin, "rls_policy_deleted", policy_id, None)
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="정책 없음")
    return {"message": "RLS 정책 삭제됨"}


@router.get("/governance/masking/policies")
async def list_mask_policies(user: Optional[dict] = Depends(_get_current_user)):
    await _require_admin(user)
    masks = await _rls_loader.load_masks()
    return [
        {
            "id": m.id, "catalog_name": m.catalog, "schema_name": m.schema,
            "table_name": m.table, "column_name": m.column, "masking_type": m.masking_type,
            "custom_expression": m.custom_expression, "enabled": m.enabled,
            "roles": [r for r, ex in m.role_map.items() if not ex],
        }
        for m in masks
    ]


@router.post("/governance/masking/policies")
async def create_mask_policy(body: MaskPolicyIn, user: Optional[dict] = Depends(_get_current_user)):
    admin = await _require_admin(user)
    valid = {"full", "partial_email", "partial_ssn", "partial_phone", "hash", "null", "custom"}
    if body.masking_type not in valid:
        raise HTTPException(status_code=400, detail=f"masking_type은 {sorted(valid)} 중 하나")
    pool = await _rls_loader._get_pool()
    import uuid as _uuid
    async with pool.acquire() as conn:
        async with conn.transaction():
            mid = await conn.fetchval(
                """INSERT INTO column_masking_policies
                     (name, description, catalog_name, schema_name, table_name, column_name,
                      masking_type, custom_expression, enabled, created_by)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id""",
                body.name, body.description, body.catalog_name, body.schema_name,
                body.table_name, body.column_name, body.masking_type, body.custom_expression,
                body.enabled, _uuid.UUID(admin["id"]) if admin.get("id") else None,
            )
            for rn in body.role_names:
                await conn.execute(
                    """INSERT INTO masking_policy_roles (policy_id, role_id, is_exempt)
                       SELECT $1, id, false FROM roles WHERE name = $2 ON CONFLICT DO NOTHING""", mid, rn)
            await _audit_policy_event(conn, admin, "masking_policy_created", str(mid), body.name)
    return {"id": str(mid), "message": "마스킹 정책 생성됨"}


@router.delete("/governance/masking/policies/{policy_id}")
async def delete_mask_policy(policy_id: str, user: Optional[dict] = Depends(_get_current_user)):
    admin = await _require_admin(user)
    import uuid as _uuid
    pool = await _rls_loader._get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM column_masking_policies WHERE id = $1", _uuid.UUID(policy_id))
        await _audit_policy_event(conn, admin, "masking_policy_deleted", policy_id, None)
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="정책 없음")
    return {"message": "마스킹 정책 삭제됨"}


@router.post("/governance/rls/preview")
async def preview_rls(body: RlsPreviewIn, user: Optional[dict] = Depends(_get_current_user)):
    """
    Simulate enforcement for a sample query as a hypothetical user
    (admin tool — pick roles + attributes, see the rewritten SQL or denial).
    """
    await _require_admin(user)
    ctx = _UserCtx(user_id="preview", username="preview",
                   roles=body.roles or [], attributes=body.attributes or {})
    policies = await _rls_loader.load_policies()
    masks = await _rls_loader.load_masks()
    try:
        res = _rls_enforce(body.sql, ctx, policies, masks)
        return {"allowed": True, "rewritten_sql": res.sql,
                "applied_policies": res.applied_policy_ids,
                "applied_masks": res.applied_mask_ids, "tables": res.tables}
    except _RlsDenied as d:
        return {"allowed": False, "reason": d.message, "table": d.table}


class DirectReadIn(BaseModel):
    sql: str


@router.get("/governance/rls/sensitive-tables")
async def get_sensitive_tables(user: Optional[dict] = Depends(_get_current_user)):
    """
    List policy-bearing (sensitive) tables + the SeaweedFS prefixes that the Jupyter
    S3 identity should be denied (RLS Layer 3 / DuckDB guard). See docs/RLS_DESIGN.md §6.
    Auth optional: the Jupyter guard calls this; if unauth and RLS off, returns empty.
    """
    if not _RLS_ADMIN_OK:
        return {"tables": [], "deny_prefixes": []}
    from app.rls.duckdb_guard import sensitive_tables, seaweedfs_deny_prefixes
    policies = await _rls_loader.load_policies()
    tables = sensitive_tables(policies)
    warehouse = os.getenv("ICEBERG_WAREHOUSE", "iceberg")
    return {"tables": tables, "deny_prefixes": seaweedfs_deny_prefixes(tables, warehouse=warehouse)}


@router.post("/governance/rls/check-direct-read")
async def check_direct_read_endpoint(body: DirectReadIn):
    """
    Used by the JupyterLab DuckDB helper: returns whether a query touches a sensitive
    table (must be routed via Trino/views) before a direct S3 read. Unauth-friendly.
    """
    if not _RLS_ADMIN_OK:
        return {"blocked": False, "table": None, "reason": None}
    from app.rls.duckdb_guard import check_direct_read
    policies = await _rls_loader.load_policies()
    return check_direct_read(body.sql, policies)


@router.get("/governance/rls/trino-rules")
async def get_trino_rules(user: Optional[dict] = Depends(_get_current_user)):
    """
    Generate the Trino file-based access control rules.json (Layer 2) from current
    users + policies + masks. Read-only preview — does not apply. See docs/RLS_DESIGN.md.
    """
    await _require_admin(user)
    from app.rls.trino_acl import generate_rules, rules_summary
    users = await _rls_loader.load_all_users()
    policies = await _rls_loader.load_policies()
    masks = await _rls_loader.load_masks()
    default_deny = os.getenv("RLS_DEFAULT_DENY", "true").lower() in ("1", "true", "yes")
    admin_bypass = os.getenv("RLS_ADMIN_BYPASS", "false").lower() in ("1", "true", "yes")
    rules = generate_rules(users, policies, masks,
                           default_deny=default_deny, admin_bypass=admin_bypass)
    return {"rules": rules, "summary": rules_summary(rules),
            "users": len(users), "policies": len(policies), "masks": len(masks)}


@router.post("/governance/rls/trino-rules/apply")
async def apply_trino_rules(user: Optional[dict] = Depends(_get_current_user)):
    """
    Write the generated rules.json into the Trino access-control ConfigMap so Trino's
    file-based access control picks it up (security.refresh-period auto-reload).
    Best-effort; requires in-cluster k8s RBAC on configmaps. See helm/.../trino-rls.
    """
    admin = await _require_admin(user)
    import json as _json
    from app.rls.trino_acl import generate_rules, rules_summary
    users = await _rls_loader.load_all_users()
    policies = await _rls_loader.load_policies()
    masks = await _rls_loader.load_masks()
    default_deny = os.getenv("RLS_DEFAULT_DENY", "true").lower() in ("1", "true", "yes")
    admin_bypass = os.getenv("RLS_ADMIN_BYPASS", "false").lower() in ("1", "true", "yes")
    rules = generate_rules(users, policies, masks,
                           default_deny=default_deny, admin_bypass=admin_bypass)
    cm_name = os.getenv("TRINO_ACL_CONFIGMAP", "trino-access-control")
    namespace = os.getenv("POD_NAMESPACE", "datapond")
    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        v1 = client.CoreV1Api()
        v1.patch_namespaced_config_map(
            name=cm_name, namespace=namespace,
            body={"data": {"rules.json": _json.dumps(rules, indent=2)}},
        )
    except Exception as e:
        logger.warning("apply trino rules failed: %s", e)
        raise HTTPException(status_code=503,
                            detail=f"ConfigMap '{cm_name}' 갱신 실패(RBAC/배선 확인): {e}")
    pool = await _rls_loader._get_pool()
    async with pool.acquire() as conn:
        await _audit_policy_event(conn, admin, "rls_policy_updated", cm_name, "trino-rules-apply")
    return {"applied": True, "configmap": cm_name, "summary": rules_summary(rules),
            "note": "Trino security.refresh-period 주기 후 반영됩니다"}


async def _audit_policy_event(conn, admin: dict, event_type: str, target: str, name: Optional[str]) -> None:
    """Write a policy-change event to auth_audit_log. Best-effort within the txn."""
    import json as _json, uuid as _uuid
    try:
        await conn.execute(
            """INSERT INTO auth_audit_log
                 (event_type, user_id, user_email, resource, action, result, details)
               VALUES ($1,$2,$3,$4,'manage_policy','success',$5)""",
            event_type,
            _uuid.UUID(admin["id"]) if admin.get("id") else None,
            admin.get("username"), target, _json.dumps({"name": name}),
        )
    except Exception as e:
        logger.debug("policy audit skipped: %s", e)


@router.get("/governance/ai-safety", response_model=AiSafetyReport)
def get_ai_safety(db: Session = Depends(get_db)):
    """
    Evaluate recent query history for SQL safety risk.

    Classifies each query as high / medium / low risk and returns
    distribution counts plus the 5 most recent flagged queries.
    """
    try:
        # Fetch last 200 queries for analysis
        recent = (
            db.query(QueryHistory)
            .order_by(QueryHistory.created_at.desc())
            .limit(200)
            .all()
        )

        distribution = {"low": 0, "medium": 0, "high": 0}
        flags: List[AiSafetyFlag] = []

        for item in recent:
            risk = evaluate_sql_risk(item.query_text or "")
            distribution[risk] += 1

            if risk in ("high", "medium"):
                flags.append(
                    AiSafetyFlag(
                        sql_preview=(item.query_text or "")[:120],
                        risk=risk,
                        user=str(item.user_id) if item.user_id else "unknown",
                        ts=item.created_at.isoformat() if item.created_at else "",
                    )
                )

        # Return at most 5 most-recent flagged items (list is already newest-first)
        top_flags = flags[:5]

        return AiSafetyReport(
            risk_distribution=RiskDistribution(**distribution),
            recent_flags=top_flags,
        )

    except Exception as exc:
        logger.error("governance/ai-safety error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch AI safety report: {exc}")
