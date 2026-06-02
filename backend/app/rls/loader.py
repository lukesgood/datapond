"""
RLS policy/context loader — bridges Postgres (auth.sql schema) to the engine.

Resilient by design: if the full auth.sql schema (user_roles, users.attributes,
rls_policies, ...) is not deployed, each loader falls back gracefully so the
caller can decide (under default_deny + RLS_ENABLED gating) how to proceed.

See docs/RLS_DESIGN.md.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg

from .engine import UserContext, RlsPolicy, MaskPolicy

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(str(os.getenv("POSTGRES_PORT", "5432")).split(":")[-1]),
            database=os.getenv("POSTGRES_DB", "datapond"),
            user=os.getenv("POSTGRES_USER", "datapond"),
            password=os.getenv("POSTGRES_PASSWORD", "dev_password"),
            min_size=1, max_size=5,
        )
    return _pool


async def load_user_context(jwt_user: Dict[str, Any]) -> UserContext:
    """
    Build UserContext from JWT + Postgres. Roles come from user_roles when present,
    else the single JWT role. Attributes come from users.attributes (JSONB) when present.
    """
    uid = jwt_user.get("id")
    username = jwt_user.get("username") or "unknown"
    roles: List[str] = []
    attributes: Dict[str, Any] = {}

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # roles via user_roles (full schema) — fall back to JWT role
            try:
                rows = await conn.fetch(
                    """SELECT r.name FROM user_roles ur JOIN roles r ON ur.role_id = r.id
                       WHERE ur.user_id = $1
                         AND (ur.expires_at IS NULL OR ur.expires_at > NOW())""",
                    uid,
                )
                roles = [r["name"] for r in rows]
            except Exception:
                roles = []
            # attributes JSONB
            try:
                row = await conn.fetchrow("SELECT attributes FROM users WHERE id = $1", uid)
                if row and row["attributes"]:
                    attributes = row["attributes"] if isinstance(row["attributes"], dict) \
                        else json.loads(row["attributes"])
            except Exception:
                attributes = {}
    except Exception as e:
        logger.warning(f"[rls] context load failed, using JWT only: {e}")

    if not roles:
        jwt_role = jwt_user.get("role")
        roles = [jwt_role] if jwt_role else []

    return UserContext(user_id=str(uid), username=username, roles=roles, attributes=attributes)


async def load_all_users() -> List[UserContext]:
    """
    Load every active user with roles + attributes, for Trino rules.json generation.
    Falls back to the minimal users table (role column) when user_roles is absent.
    """
    out: List[UserContext] = []
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM users")  # schema-agnostic
            role_rows = []
            try:
                role_rows = await conn.fetch(
                    """SELECT ur.user_id, r.name FROM user_roles ur JOIN roles r ON ur.role_id = r.id
                       WHERE ur.expires_at IS NULL OR ur.expires_at > NOW()""")
            except Exception:
                role_rows = []
    except Exception as e:
        logger.warning(f"[rls] load_all_users failed: {e}")
        return []

    roles_by_user: Dict[str, List[str]] = {}
    for rr in role_rows:
        roles_by_user.setdefault(str(rr["user_id"]), []).append(rr["name"])

    for r in rows:
        d = dict(r)
        # active filter works for both schemas (is_active bool / status enum)
        if d.get("is_active") is False:
            continue
        if d.get("status") not in (None, "active"):
            continue
        uid = str(d.get("id"))
        raw_attr = d.get("attributes")
        attrs = raw_attr if isinstance(raw_attr, dict) else (json.loads(raw_attr) if raw_attr else {})
        roles = roles_by_user.get(uid) or ([d["role"]] if d.get("role") else [])
        out.append(UserContext(user_id=uid, username=d.get("username") or uid,
                               roles=roles, attributes=attrs))
    return out


async def load_policies() -> List[RlsPolicy]:
    """Load all enabled RLS policies with their role mappings. [] if table absent."""
    out: List[RlsPolicy] = []
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT p.id, p.catalog_name, p.schema_name, p.table_name,
                          p.filter_expression, p.priority, p.enabled,
                          r.name AS role_name, pr.is_exempt
                   FROM rls_policies p
                   LEFT JOIN rls_policy_roles pr ON pr.policy_id = p.id
                   LEFT JOIN roles r ON r.id = pr.role_id
                   WHERE p.enabled = true"""
            )
    except Exception as e:
        logger.warning(f"[rls] policy load skipped (schema not present?): {e}")
        return []

    by_id: Dict[str, RlsPolicy] = {}
    for r in rows:
        pid = str(r["id"])
        pol = by_id.get(pid)
        if pol is None:
            pol = RlsPolicy(
                id=pid, catalog=r["catalog_name"], schema=r["schema_name"],
                table=r["table_name"], filter_expression=r["filter_expression"],
                priority=r["priority"] or 0, enabled=r["enabled"], role_map={},
            )
            by_id[pid] = pol
        if r["role_name"]:
            pol.role_map[r["role_name"]] = bool(r["is_exempt"])
    return list(by_id.values())


async def load_masks() -> List[MaskPolicy]:
    """Load all enabled column-masking policies with role mappings. [] if absent."""
    out: Dict[str, MaskPolicy] = {}
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT m.id, m.catalog_name, m.schema_name, m.table_name, m.column_name,
                          m.masking_type, m.custom_expression, m.enabled,
                          r.name AS role_name, mr.is_exempt
                   FROM column_masking_policies m
                   LEFT JOIN masking_policy_roles mr ON mr.policy_id = m.id
                   LEFT JOIN roles r ON r.id = mr.role_id
                   WHERE m.enabled = true"""
            )
    except Exception as e:
        logger.warning(f"[rls] mask load skipped: {e}")
        return []

    for r in rows:
        mid = str(r["id"])
        m = out.get(mid)
        if m is None:
            m = MaskPolicy(
                id=mid, catalog=r["catalog_name"], schema=r["schema_name"],
                table=r["table_name"], column=r["column_name"],
                masking_type=str(r["masking_type"]), custom_expression=r["custom_expression"],
                enabled=r["enabled"], role_map={},
            )
            out[mid] = m
        if r["role_name"]:
            m.role_map[r["role_name"]] = bool(r["is_exempt"])
    return list(out.values())


async def audit_denial(user: UserContext, raw_sql: str, denied_reason: str,
                       table: Optional[str] = None) -> None:
    """
    Best-effort write of an RLS denial to auth_audit_log (event_type=permission_denied).
    Successful queries are recorded by QueryHistory, not here. Never raises.
    """
    import hashlib
    try:
        pool = await _get_pool()
        sql_hash = hashlib.sha256(raw_sql.encode()).hexdigest()[:16]
        details = {"sql_hash": sql_hash, "table": table, "layer": "backend_rls"}
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO auth_audit_log
                     (event_type, user_id, user_email, resource, action, result, failure_reason, details)
                   VALUES ('permission_denied', $1, $2, $3, 'query', 'failure', $4, $5)""",
                user.user_id, user.username, table, denied_reason, json.dumps(details),
            )
    except Exception as e:
        logger.debug(f"[rls] audit skipped: {e}")
