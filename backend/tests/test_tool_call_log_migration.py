"""The tool call log migration, checked as text — there is no database in this test
environment (see test_audit_append_only.py for the same approach)."""
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0008_tool_call_log.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0008_tool_call_log.py").read_text(encoding="utf-8")


def test_revision_chain_points_at_seed_roles():
    assert 'revision: str = "0008_tool_call_log"' in PY
    assert 'down_revision: Union[str, None] = "0007_seed_roles"' in PY


def test_table_columns_present():
    for col in ("actor_id", "actor_username", "actor_kind", "tool", "resource_kind",
                "resource", "request_hash", "request_masked", "hit_count",
                "citation_sources", "pii_masked", "outcome", "duration_ms",
                "client_address", "via", "occurred_at"):
        assert re.search(rf"^\s+{col}\s", SQL, re.M), col


def test_tool_and_outcome_are_constrained():
    assert "CHECK (tool IN ('ai.search', 'ai.rag', 'ai.sql', 'query.execute'))" in SQL
    assert "CHECK (outcome IN ('ok', 'degraded', 'error'))" in SQL
    assert "CHECK (actor_kind IN ('human', 'service'))" in SQL


def test_append_only_trigger_and_prune_function():
    assert "CREATE TRIGGER tool_call_log_append_only" in SQL
    assert "BEFORE UPDATE OR DELETE ON public.tool_call_log" in SQL
    assert "EXECUTE FUNCTION public.reject_audit_log_mutation()" in SQL
    assert "REVOKE UPDATE ON TABLE public.tool_call_log FROM CURRENT_USER" in SQL
    assert "CREATE OR REPLACE FUNCTION public.prune_tool_call_log(cutoff_ts timestamptz)" in SQL
    assert "set_config('datapond.audit_retention_delete', 'on', true)" in SQL


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0008_tool_call_log", SQL) == []
