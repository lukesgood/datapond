"""
DataPond RLS enforcement engine (Layer 1, MVP) — see docs/RLS_DESIGN.md.

The core is pure logic and unit-testable WITHOUT a running cluster:
the public entry point `enforce(sql, user, policies, masks)` takes the user
context + policy rows (already fetched from Postgres by the caller) and returns
a rewritten SQL string or raises RlsDenied.

Locked decisions (2026-06-02):
  - Hybrid enforcement; this module is the backend layer (real enforcement until
    Trino-native rules.json lands in P3).
  - default_deny: a referenced table with no applicable policy is DENIED.
  - admin gets RLS applied unless RLS_ADMIN_BYPASS=true.
  - Row filter is injected by wrapping each policy-bearing table reference in a
    filtered (and column-masked) subquery via sqlglot.

Attribute templating: filter_expression may reference the calling user's
attributes with `current_user_attribute('<key>')`. The key is whitelisted and
the substituted value is rendered as a safe SQL literal (no string interpolation
of raw user input into SQL).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import sqlglot
from sqlglot import exp


# ── Exceptions ──────────────────────────────────────────────────────────────

class RlsDenied(Exception):
    """Raised when a query is blocked by RLS (default_deny, unparseable, etc.)."""

    def __init__(self, message: str, table: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.table = table


# ── Inputs (caller fills these from Postgres / JWT) ─────────────────────────

@dataclass
class UserContext:
    user_id: str
    username: str
    roles: Sequence[str]                       # e.g. ["business_analyst"]
    attributes: Dict[str, Any] = field(default_factory=dict)  # users.attributes JSONB

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass
class RlsPolicy:
    """One row of rls_policies joined with rls_policy_roles."""
    id: str
    catalog: str
    schema: str
    table: str
    filter_expression: str
    priority: int = 0
    enabled: bool = True
    # role name -> is_exempt
    role_map: Dict[str, bool] = field(default_factory=dict)


@dataclass
class MaskPolicy:
    """One row of column_masking_policies joined with masking_policy_roles."""
    id: str
    catalog: str
    schema: str
    table: str
    column: str
    masking_type: str                          # full|partial_email|partial_ssn|partial_phone|hash|null|custom
    custom_expression: Optional[str] = None
    enabled: bool = True
    role_map: Dict[str, bool] = field(default_factory=dict)


@dataclass
class EnforceResult:
    sql: str                                   # rewritten SQL ready for Trino
    applied_policy_ids: List[str] = field(default_factory=list)
    applied_mask_ids: List[str] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)


# ── Config ──────────────────────────────────────────────────────────────────

def _admin_bypass_enabled() -> bool:
    return os.getenv("RLS_ADMIN_BYPASS", "false").lower() in ("1", "true", "yes")


# Default catalog/schema used to qualify unqualified table refs (matches queries.py).
# RLS_DEFAULT_CATALOG lets the Athena engine re-point the catalog (AwsDataCatalog).
DEFAULT_CATALOG = os.getenv("RLS_DEFAULT_CATALOG", os.getenv("TRINO_CATALOG", "iceberg"))
DEFAULT_SCHEMA = os.getenv("TRINO_SCHEMA", "default")

_ATTR_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_ATTR_CALL_RE = re.compile(r"current_user_attribute\(\s*'([^']*)'\s*\)")


# ── Attribute binding ───────────────────────────────────────────────────────

def sql_literal(value: Any) -> str:
    """Render a Python value as a safe SQL literal (single-quote escaped)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    return "'" + s.replace("'", "''") + "'"


def bind_attributes(expr: str, attributes: Dict[str, Any]) -> str:
    """
    Replace current_user_attribute('key') with the user's value as a SQL literal.
    Unknown/invalid keys -> NULL (so the predicate fails closed, not errors).
    """
    def _repl(m: "re.Match[str]") -> str:
        key = m.group(1)
        if not _ATTR_KEY_RE.match(key) or key not in attributes:
            return "NULL"
        return sql_literal(attributes[key])

    return _ATTR_CALL_RE.sub(_repl, expr)


# ── Policy resolution ───────────────────────────────────────────────────────

def applicable_policies(policies: Sequence[RlsPolicy], user: UserContext) -> List[RlsPolicy]:
    """
    Filter to policies that apply to this user:
      - enabled
      - at least one of the user's roles is mapped non-exempt
      - if ANY of the user's roles is exempt for the policy -> policy skipped
    Returned sorted by priority asc (AND-combined later).
    """
    out: List[RlsPolicy] = []
    roles = set(user.roles)
    for p in policies:
        if not p.enabled:
            continue
        mapped = {r: p.role_map[r] for r in roles if r in p.role_map}
        if not mapped:
            continue                       # policy not targeted at this user's roles
        if any(is_exempt for is_exempt in mapped.values()):
            continue                       # an exempt role frees the user
        out.append(p)
    out.sort(key=lambda x: x.priority)
    return out


def combined_filter(policies: Sequence[RlsPolicy], user: UserContext) -> Optional[str]:
    """AND-combine bound filter expressions. None if no policies."""
    parts = [f"({bind_attributes(p.filter_expression, user.attributes)})" for p in policies]
    if not parts:
        return None
    return " AND ".join(parts)


# ── Column masking ──────────────────────────────────────────────────────────

def mask_expression(col: str, mask: MaskPolicy) -> str:
    """SQL expression that masks `col` according to mask.masking_type (Trino dialect)."""
    t = mask.masking_type
    if t == "null":
        return "NULL"
    if t == "full":
        return "'***'"
    if t == "hash":
        return f"to_hex(sha256(to_utf8(CAST({col} AS VARCHAR))))"
    if t == "partial_email":
        return f"regexp_replace(CAST({col} AS VARCHAR), '(^.).*(@.*$)', '$1***$2')"
    if t == "partial_ssn":
        return f"concat('***-**-', substr(CAST({col} AS VARCHAR), -4))"
    if t == "partial_phone":
        return f"concat('***-***-', substr(CAST({col} AS VARCHAR), -4))"
    if t == "custom" and mask.custom_expression:
        return mask.custom_expression
    return "'***'"                          # safe default


# ── Core enforcement ────────────────────────────────────────────────────────

def _qualify(table: exp.Table) -> str:
    """Return canonical catalog.schema.table (lowercased) for a sqlglot Table node."""
    parts = [p for p in (table.catalog, table.db, table.name) if p]
    if len(parts) == 1:
        parts = [DEFAULT_CATALOG, DEFAULT_SCHEMA, parts[0]]
    elif len(parts) == 2:
        parts = [DEFAULT_CATALOG, parts[0], parts[1]]
    return ".".join(p.lower() for p in parts)


def _policy_key(p) -> str:
    return f"{p.catalog}.{p.schema}.{p.table}".lower()


def enforce(
    sql: str,
    user: UserContext,
    policies: Sequence[RlsPolicy],
    masks: Sequence[MaskPolicy] = (),
    *,
    sensitive_block: bool = False,
    dialect: str = "trino",
) -> EnforceResult:
    """
    Apply RLS to `sql` for `user`. Returns rewritten SQL or raises RlsDenied.

    `policies`/`masks` are ALL candidate rows for the tables in this query
    (caller pre-fetches by table; over-fetching is fine — we filter by table here).

    `sensitive_block=True` is used by the DuckDB/direct-read guard: any referenced
    table that HAS a policy is treated as sensitive and denied entirely.
    """
    if user.is_admin and _admin_bypass_enabled():
        return EnforceResult(sql=sql, tables=[])

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:                  # unparseable -> fail closed
        raise RlsDenied(f"쿼리를 파싱할 수 없어 차단됨(default_deny): {e}")

    statements = [s for s in statements if s is not None]
    if not statements:
        raise RlsDenied("빈 쿼리")

    # index policies/masks by canonical table key
    pol_by_table: Dict[str, List[RlsPolicy]] = {}
    for p in policies:
        pol_by_table.setdefault(_policy_key(p), []).append(p)
    mask_by_table: Dict[str, List[MaskPolicy]] = {}
    for m in masks:
        mask_by_table.setdefault(_policy_key(m), []).append(m)

    applied_pids: List[str] = []
    applied_mids: List[str] = []
    seen_tables: List[str] = []

    for stmt in statements:
        for tbl in list(stmt.find_all(exp.Table)):
            key = _qualify(tbl)
            if key not in seen_tables:
                seen_tables.append(key)

            tbl_policies = pol_by_table.get(key, [])

            # default_deny: a referenced table with no policy is blocked
            if not tbl_policies:
                if user.is_admin and _admin_bypass_enabled():
                    continue
                raise RlsDenied(
                    f"테이블 '{key}'에 RLS 정책이 없어 차단됨(default_deny). 정책 등록 필요.",
                    table=key,
                )

            # DuckDB/direct-read guard: policy-bearing table = sensitive -> block
            if sensitive_block:
                raise RlsDenied(
                    f"민감 테이블 '{key}'은 직접읽기(DuckDB/S3) 차단 — Trino/뷰 경로 사용.",
                    table=key,
                )

            eff = applicable_policies(tbl_policies, user)
            filt = combined_filter(eff, user)

            # build masked projection
            tbl_masks = [m for m in mask_by_table.get(key, []) if m.enabled]
            eff_masks = [m for m in tbl_masks if _mask_applies(m, user)]

            if filt is None and not eff_masks:
                # user is exempt from all policies on this table -> pass through,
                # but table IS registered so access is allowed.
                continue

            _wrap_table(tbl, key, filt, eff_masks, dialect)
            applied_pids.extend(p.id for p in eff)
            applied_mids.extend(m.id for m in eff_masks)

    rewritten = statements[0].sql(dialect=dialect) if len(statements) == 1 \
        else ";\n".join(s.sql(dialect=dialect) for s in statements)
    return EnforceResult(
        sql=rewritten,
        applied_policy_ids=applied_pids,
        applied_mask_ids=applied_mids,
        tables=seen_tables,
    )


def _mask_applies(mask: MaskPolicy, user: UserContext) -> bool:
    roles = set(user.roles)
    mapped = {r: mask.role_map[r] for r in roles if r in mask.role_map}
    if not mapped:
        return False
    return not any(mapped.values())          # any exempt role -> mask not applied


def _wrap_table(tbl: exp.Table, key: str, filt: Optional[str], masks: List[MaskPolicy],
                dialect: str = "trino") -> None:
    """
    Replace `tbl` in-place with a filtered/masked subquery, preserving its alias:
        FROM cat.sch.t  ->  FROM (SELECT * [EXCEPT(masked), <mask> AS col] FROM cat.sch.t
                                   [WHERE <filt>]) AS <alias>
    Masked columns use Trino's `SELECT * EXCEPT (col), <expr> AS col` so the column
    keeps its name/position semantics while the value is masked.
    """
    alias = tbl.alias or tbl.name
    catalog, schema, name = key.split(".")

    if masks:
        except_clause = ", ".join(m.column for m in masks)
        overrides = ", ".join(f"{mask_expression(m.column, m)} AS {m.column}" for m in masks)
        select_sql = f"SELECT * EXCEPT ({except_clause}), {overrides} FROM {catalog}.{schema}.{name}"
    else:
        select_sql = f"SELECT * FROM {catalog}.{schema}.{name}"

    if filt:
        select_sql += f" WHERE {filt}"

    inner = sqlglot.parse_one(select_sql, read=dialect)
    subquery = exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias)))
    tbl.replace(subquery)
