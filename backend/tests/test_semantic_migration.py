"""Migration 0023: the semantic layer's tables, and versions that cannot be edited."""
import re
from pathlib import Path

from app.migration_rules import review_migration

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
PY = VERSIONS / "0023_semantic_metrics.py"
SQL = VERSIONS / "0023_semantic_metrics.sql"


def _sql() -> str:
    return SQL.read_text()


def test_files_exist_and_chain_from_0022():
    body = PY.read_text()
    assert 'revision: str = "0023_semantic_metrics"' in body
    assert 'down_revision: Union[str, None] = "0022_audit_rows_outlive_users"' in body
    assert "run_sql_file" in body


def test_it_is_the_highest_revision():
    stems = sorted(p.stem for p in VERSIONS.glob("*.py") if re.fullmatch(r"\d{4}_[a-z0-9_]+", p.stem))
    assert stems[-1] == "0023_semantic_metrics"


def test_three_tables_are_created_idempotently():
    sql = _sql()
    for table in ("semantic_metrics", "semantic_metric_versions", "semantic_joins"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in sql


def test_metric_names_are_constrained_in_the_database():
    assert "^[a-z][a-z0-9_]{0,62}$" in _sql()


def test_versions_have_an_update_and_delete_trigger():
    sql = _sql()
    assert "BEFORE UPDATE OR DELETE ON public.semantic_metric_versions" in sql
    assert "reject_metric_version_mutation" in sql


def test_no_foreign_key_to_users():
    """Like the audit tables after 0022: deleting a user must not need to touch a version."""
    assert "REFERENCES public.users" not in _sql()


def test_migration_rules_do_not_flag_it():
    assert review_migration("0023_semantic_metrics", _sql(), PY.read_text()) == []


def test_tool_call_log_accepts_metric_rows():
    """metric.query rows carry resource_kind 'metric'; 0008's CHECK allowed only three
    values, so 0023 widens it the way 0010 widened the outcome CHECK."""
    sql = _sql()
    assert "pg_get_constraintdef(oid) ILIKE '%resource_kind%'" in sql
    assert "CHECK (resource_kind IN ('collection', 'tables', 'none', 'metric'))" in sql
    assert "NOT VALID" in sql
