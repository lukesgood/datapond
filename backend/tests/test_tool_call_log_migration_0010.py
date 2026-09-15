"""0010 widens tool_call_log.outcome to admit 'refused' — checked as text, like 0008/0009."""
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0010_tool_call_log_refused.sql").read_text(encoding="utf-8")
PY_TEXT = (VERSIONS / "0010_tool_call_log_refused.py").read_text(encoding="utf-8")


def test_revision_chain_points_at_the_tool_ids_revision():
    assert 'revision: str = "0010_tool_call_log_refused"' in PY_TEXT
    assert 'down_revision: Union[str, None] = "0009_tool_call_log_tool_ids"' in PY_TEXT


def test_the_new_constraint_is_a_superset_added_not_validated():
    assert "CHECK (outcome IN ('ok', 'degraded', 'error', 'refused'))" in SQL
    assert "NOT VALID" in SQL


def test_the_old_constraint_is_found_by_definition_not_by_a_guessed_name():
    assert "pg_get_constraintdef(oid) ILIKE '%outcome%degraded%'" in SQL
    assert "DROP CONSTRAINT %I" in SQL


def test_no_forbidden_ddl():
    from app.migration_rules import review_migration
    assert review_migration("0010_tool_call_log_refused", SQL, docstring=PY_TEXT) == []
